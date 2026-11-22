"""Lyrics lookup and playback controls for the Media V2 popup."""

from __future__ import annotations

import math

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QHideEvent, QPainter, QPaintEvent, QPalette, QShowEvent
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from core.validation.widgets.yasb.media_v2 import MediaLyricsConfig
from core.widgets.services.media.lyrics import LyricsService, LyricsState
from core.widgets.services.media.lyrics_provider import LyricsQuery
from core.widgets.services.media.model import MediaSessionState
from core.widgets.yasb.media_v2_components import MediaButton, identify
from core.widgets.yasb.media_v2_lyrics_view import LyricsView
from core.widgets.yasb.media_v2_motion import FrameClock


class LyricsNote(QWidget):
    def paintEvent(self, a0: QPaintEvent | None) -> None:
        if a0 is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = self.height() / 28
        painter.translate((self.width() - self.height()) / 2, 0)
        painter.scale(side, side)
        painter.setOpacity(0.75)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.palette().color(QPalette.ColorRole.WindowText))
        painter.drawEllipse(QRectF(5, 16, 12, 11))
        painter.drawRoundedRect(QRectF(13, 2, 4, 20), 1, 1)
        painter.drawRoundedRect(QRectF(13, 2, 11, 5), 1, 1)


class MediaLyricsPanel(QFrame):
    seek_requested = pyqtSignal(float, object)

    def __init__(
        self,
        scale: float,
        parent: QWidget,
        *,
        options: MediaLyricsConfig | None = None,
        service: LyricsService | None = None,
        clock: FrameClock | None = None,
    ) -> None:
        super().__init__(parent)
        identify(self, "media-lyrics", "media-lyrics")
        self.scale = scale
        self.options = options or MediaLyricsConfig()
        self._service = service
        self._connected = False
        self._token = object()
        self._active = False
        self._leaving = False
        self._snapshot: MediaSessionState | None = None
        self._candidate: LyricsQuery | None = None
        self._query: LyricsQuery | None = None
        self._association: tuple[str, int] | None = None
        self._watched_query: LyricsQuery | None = None
        self._rendered_query: LyricsQuery | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            0,
            round(self.options.margins.vertical * scale),
            0,
            round(self.options.margins.vertical * scale),
        )
        layout.setSpacing(0)
        self.view = LyricsView(scale, self, self.options, clock=clock)
        self.view.seek_requested.connect(self.seek_requested)
        layout.addWidget(self.view, 1)
        self.placeholder = QWidget(self)
        idle = QVBoxLayout(self.placeholder)
        idle.setContentsMargins(
            round(self.options.margins.placeholder * scale),
            0,
            round(self.options.margins.placeholder * scale),
            0,
        )
        idle.setSpacing(round(self.options.line_spacing * scale))
        idle.addStretch(1)
        note = identify(LyricsNote(self.placeholder), "media-lyrics-note", "media-lyrics-status")
        note.setFixedHeight(round(28 * scale))
        note.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        idle.addWidget(note)
        self.message = identify(
            QLabel("Nothing playing", self.placeholder), "media-lyrics-status", "media-lyrics-status"
        )
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        idle.addWidget(self.message)
        idle.addStretch(1)
        layout.addWidget(self.placeholder, 1)
        self.view.hide()
        self.retry_button = MediaButton(self, "lyrics-retry", "lyrics-action")
        self.retry_button.setText("Retry")
        self.retry_button.setAccessibleName("Retry lyric lookup")
        self.retry_button.clicked.connect(self.retry)
        self._render()

    def _owner(self) -> LyricsService:
        if self._service is None or getattr(self._service, "closed", False):
            previous = self._service
            if previous is not None and self._connected:
                try:
                    previous.changed.disconnect(self._changed)
                except RuntimeError, TypeError:
                    pass
                self._connected = False
            self._service = LyricsService.shared()
        configure = getattr(self._service, "configure", None)
        if callable(configure):
            configure(
                providers=tuple(self.options.active_provider_order()),
                spacing_ms=self.options.request_spacing_ms,
                timeout_ms=self.options.request_timeout_ms,
                credentials=self.options.provider_credentials(),
                prefer_word_timed=self.options.prefer_word_timed,
            )
        if not self._connected:
            self._service.changed.connect(self._changed)
            service, token = self._service, self._token
            self.destroyed.connect(lambda: service.unwatch(token))
            self._connected = True
        return self._service

    def set_state(self, snapshot: MediaSessionState | None) -> None:
        association = (
            (snapshot.session_id, snapshot.seek_revision)
            if snapshot is not None and snapshot.seek_revision is not None
            else None
        )
        query = None
        if association is not None and snapshot is not None:
            duration = snapshot.duration
            duration_ms = round(duration * 1000) if duration and math.isfinite(duration) and duration > 0 else None
            try:
                query = LyricsQuery(snapshot.title, snapshot.artist, snapshot.album, duration_ms).normalized()
            except ValueError:
                pass
        if association != self._association or query != self._candidate:
            self.cancel_interaction()
            if self._query is not None and self._service is not None:
                self._query = None
                self._watched_query = None
                self._service.unwatch(self._token)
        self._snapshot, self._association, self._candidate = snapshot, association, query
        self._reconcile()
        self._position()

    def _position(self) -> None:
        if self._leaving:
            return
        snapshot = self._snapshot
        position = round(snapshot.position * 1000) if snapshot and snapshot.timeline.known else None
        identity = self._association if snapshot and snapshot.is_seekable else None
        self.view.set_position(
            position,
            identity,
            playing=bool(snapshot and snapshot.is_playing),
            rate=snapshot.playback.rate if snapshot else 1.0,
        )

    def set_active(self, active: bool) -> None:
        if active:
            self._leaving = False
        elif self._active and self.isVisible():
            self._leaving = True
        self._active = active
        if not active:
            self.view.finish_line_motion()
            self.cancel_interaction()
        self._reconcile()

    def cancel_interaction(self) -> None:
        self.view.cancel_interaction()

    def _reconcile(self) -> None:
        query = self._candidate if self._active and self.isVisible() else None
        self.view.accept_input = query is not None
        if query != self._query:
            # watch emits synchronously: publish the new association first.
            self._query = query
        watched = query if self.options.auto_lookup else None
        service_closed = self._service is None or getattr(self._service, "closed", False)
        if watched != self._watched_query or watched is not None and service_closed:
            if self._watched_query is not None and self._service is not None:
                self._service.unwatch(self._token)
            self._watched_query = watched
            if watched is not None:
                self._owner().watch(self._token, watched)
        self._render()

    def _changed(self, query: LyricsQuery) -> None:
        if query == self._query:
            self._render()

    def _render(self) -> None:
        # Release demand immediately and retain the last painted page until
        # the section's outgoing presentation has finished.
        if self._leaving:
            return
        state = (
            self._service.state(self._query) if self._service is not None and self._query is not None else LyricsState()
        )
        document = state.document if state.status == "ready" else None
        # A later provider's better document for the same track replaces the
        # current one in place instead of resetting the list.
        self.view.set_document(document, replace=document is not None and self._rendered_query == self._query)
        self._rendered_query = self._query if document is not None else None
        has_text = bool(document and (document.lines or document.plain))
        self.view.setVisible(has_text)
        self.placeholder.setVisible(not has_text)
        if document and document.instrumental:
            message = "Instrumental"
        elif self._candidate is None:
            message = "Reading track metadata…" if self._snapshot else "Nothing playing"
        else:
            message = {
                "idle": "Select Lyrics to look up this track",
                "loading": "Searching lyrics…",
                "missing": "No lyrics found",
                "error": "Could not load lyrics",
                "ready": "No lyrics found",
            }[state.status]
        if state.detail and state.status in ("missing", "error"):
            message += "\n" + state.detail[:256]
        self.message.setText(message)
        provenance = "\n".join((document.source, *document.warnings)) if document else state.detail
        self.view.setToolTip(provenance)
        self.view.setAccessibleDescription(
            ("Timed lyrics" if document and document.lines else "Plain lyrics") + "\n" + provenance
        )
        self.retry_button.setEnabled(self._query is not None and bool(self._query.artist) and state.status != "loading")
        self.retry_button.setVisible(self._active and state.status in ("missing", "error"))
        self._position()

    def retry(self) -> None:
        if self._query is not None:
            owner = self._owner()
            if self._watched_query is None:
                self._watched_query = self._query
                owner.watch(self._token, self._query)
            owner.retry(self._query)

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        self._reconcile()

    def hideEvent(self, a0: QHideEvent | None) -> None:
        self._leaving = False
        self.cancel_interaction()
        super().hideEvent(a0)
        self._reconcile()
