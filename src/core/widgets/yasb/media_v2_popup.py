"""Snapshot-driven media popup. No media service ownership or DSP claims."""

import logging
from collections import Counter

from PyQt6.QtCore import QEasingCurve, QEvent, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
)

from core.utils.qobject import is_valid_qobject
from core.utils.tooltip import set_tooltip
from core.utils.utilities import PopupWidget, refresh_widget_style
from core.widgets.services.media.audio_device import AudioOutputState, DefaultAudioOutputService
from core.widgets.yasb.media_v2_background import MediaSurface
from core.widgets.yasb.media_v2_border import MediaBorder
from core.widgets.yasb.media_v2_components import (
    MediaButton,
    MediaComboBox,
    MediaText,
    SeekSlider,
    TransportControls,
    format_time,
    identify,
    media_title,
    track_identity,
)
from core.widgets.yasb.media_v2_disc import DiscArt
from core.widgets.yasb.media_v2_equalizer import EqualizerPanel
from core.widgets.yasb.media_v2_motion import RevealEffect, animate, settle
from core.widgets.yasb.media_v2_styles import media_styles

logger = logging.getLogger("MediaV2")


def session_option_labels(sessions):
    """Return stable, distinct selector labels without exposing native sessions."""
    bases = [session.player.application_name or session.player.app_id or "Media" for session in sessions]
    totals = Counter(bases)
    ordinals = Counter()
    used = Counter()
    labels = []
    for session, base in zip(sessions, bases):
        ordinals[base] += 1
        if totals[base] == 1:
            label = base
        else:
            hint = (session.title or session.metadata.subtitle or session.album).strip()
            if hint:
                if len(hint) > 42:
                    hint = hint[:39].rstrip() + "…"
                label = f"{base} — {hint}"
            else:
                label = f"{base} {ordinals[base]}"
        used[label] += 1
        if used[label] > 1:
            label = f"{label} ({used[label]})"
        labels.append(label)
    return tuple(labels)


class MediaPopup(PopupWidget):
    seek_requested = pyqtSignal(float, object)
    session_selected = pyqtSignal(object)
    dismissed = pyqtSignal(bool)

    def __init__(self, parent, config):
        super().__init__(
            parent,
            blur=config.popup.blur,
            round_corners=config.popup.round_corners,
            round_corners_type=config.popup.round_corners_type,
            border_color=config.popup.border_color,
            persistent=True,
        )
        self.config = config
        self._intro = []
        self._open_pos = QPoint()
        self._closed_pos = QPoint()
        self.s = lambda value: round(value * config.scale)
        self._state = None
        self._content_key = None
        self._seek_identity = None
        self._session_options = None
        self._output_service = None
        self._restore_focus_on_dismiss = False
        identify(self, "media-v2-popup", "media-v2-popup")
        self.setAccessibleName("Media player")
        if config.use_default_styles:
            self.setStyleSheet(media_styles(config))
        self._escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._escape.activated.connect(lambda: self.hide_animated(restore_focus=True))
        self._fade_animation.setDuration(760)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea(self)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(False)
        identify(self.scroll.viewport(), "media-viewport")
        root.addWidget(self.scroll)
        self.border = identify(
            MediaBorder(self.s(config.border_radius), config.scale, options=config.popup.border),
            "media-border",
        )
        top_height = 464 if config.popup.artwork_position == "top" else 224
        self.border.setFixedSize(self.s(625), self.s(top_height + 42 + (302 if config.popup.show_equalizer else 0)))
        self.scroll.setWidget(self.border)
        border_layout = QVBoxLayout(self.border)
        border_layout.setContentsMargins(*([self.border.content_inset] * 4))
        self.surface = identify(
            MediaSurface(config.popup.background, self.border.content_radius, self.border),
            "media-surface",
            "media-surface",
        )
        border_layout.addWidget(self.surface)
        self.surface.palette_changed.connect(self.border.set_palette)
        main = QVBoxLayout(self.surface)
        main.setContentsMargins(*([self.s(18)] * 4))
        main.setSpacing(0)
        top = identify(QFrame(self.surface), "media-main")
        top.setFixedHeight(self.s(top_height))
        main.addWidget(top)
        row = QVBoxLayout(top) if config.popup.artwork_position == "top" else QHBoxLayout(top)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(self.s(16))
        self.art = DiscArt(config.popup.disc, top)
        self.art.setFixedSize(self.s(224), self.s(224))
        details = identify(QFrame(top), "media-details")
        if config.popup.artwork_position == "right":
            row.addWidget(details, 1)
            row.addWidget(self.art)
        else:
            if config.popup.artwork_position != "hidden":
                row.addWidget(self.art, 0, Qt.AlignmentFlag.AlignCenter)
            else:
                self.art.hide()
            row.addWidget(details, 1)
        detail_layout = QVBoxLayout(details)
        detail_layout.setContentsMargins(0, 0, 0, self.s(28))
        detail_layout.setSpacing(self.s(6))
        detail_layout.addStretch()
        scrolling = config.popup.scrolling_label
        self.title = MediaText(
            "media-v2-title",
            details,
            elide=not config.popup.scroll_title,
            classes="media-title title",
            scrollable=config.popup.scroll_title,
            scroll_speed=scrolling.speed,
            scroll_delay=scrolling.delay,
        )
        self.title.setFixedHeight(self.s(25))
        self.artist = MediaText(
            "media-v2-artist",
            details,
            elide=not config.popup.scroll_artist,
            classes="media-artist artist",
            scrollable=config.popup.scroll_artist,
            scroll_speed=scrolling.speed,
            scroll_delay=scrolling.delay,
        )
        self.artist.setFixedHeight(self.s(18))
        output = identify(QFrame(details), "media-v2-output", "media-output")
        source_row = QHBoxLayout(output)
        source_row.setContentsMargins(0, 0, 0, 0)
        source_row.setSpacing(self.s(9))
        self.device = identify(
            MediaText(
                "media-v2-output-label",
                output,
                elide=True,
                classes="media-output-label label",
                scrollable=False,
            ),
            "media-v2-output-label",
            "media-output-label",
            "label",
        )
        self.device.setFixedHeight(self.s(22))
        self.device.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        source_row.addWidget(self.device, 1)
        self._output_service = DefaultAudioOutputService.instance()
        self._output_service.default_output_changed.connect(self._on_output_changed)
        self._on_output_changed(self._output_service.state)
        self.source = MediaButton(output, "media-source")
        self.source.setObjectName("media-source")
        self.source.setFixedHeight(self.s(22))
        self.source.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.source.setAccessibleName("Media player selection")
        self.source.clicked.connect(self._open_session_menu)
        self.selector = MediaComboBox(output)
        self.selector.setObjectName("media-player-selector")
        self.selector.setAccessibleName("Media player selection")
        self.selector.setFixedSize(self.s(140), self.s(22))
        self.selector.setMaxVisibleItems(7)
        self.selector.activated.connect(self._select_session)
        source_row.addWidget(self.source, 1)
        source_row.addWidget(self.selector)
        timeline = identify(QFrame(details), "media-v2-timeline", "media-timeline")
        inline = config.popup.timestamps == "inline"
        timeline_layout = QHBoxLayout(timeline) if inline else QVBoxLayout(timeline)
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        timeline_layout.setSpacing(self.s(4))
        self.progress = SeekSlider(
            config.scale,
            timeline,
            smoothing_ms=config.popup.progress.smoothing_ms,
            show_handle=config.popup.progress.show_handle,
        )
        self.elapsed = MediaText("media-v2-elapsed", timeline, classes="playback-time elapsed")
        self.duration = MediaText("media-v2-duration", timeline, classes="playback-time duration")
        self.duration.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for label in (self.elapsed, self.duration):
            label.setFixedHeight(self.s(15))
            label.setMinimumWidth(self.s(50))
        if inline:
            self.elapsed.setFixedWidth(self.s(55))
            self.duration.setFixedWidth(self.s(55))
            timeline_layout.addWidget(self.elapsed)
            timeline_layout.addWidget(self.progress, 1)
            timeline_layout.addWidget(self.duration)
        else:
            times = QHBoxLayout()
            times.addWidget(self.elapsed, 1)
            times.addWidget(self.duration, 1)
            if config.popup.timestamps == "above":
                timeline_layout.addLayout(times)
                timeline_layout.addWidget(self.progress)
            else:
                timeline_layout.addWidget(self.progress)
                timeline_layout.addLayout(times)
            if config.popup.timestamps == "hidden":
                self.elapsed.hide()
                self.duration.hide()
        self.controls = TransportControls(config.scale * config.popup.controls.scale, details, popup=True)
        for control in (self.controls.previous, self.controls.play, self.controls.next):
            control.set_shape(config.controls_shape, self.s(config.border_radius))
        sections = {
            "title": self.title,
            "artist": self.artist,
            "output": output,
            "timeline": timeline,
            "controls": self.controls,
        }
        for name, widget in sections.items():
            widget.setVisible(name in config.popup.detail_order)
        for name in config.popup.detail_order:
            widget = sections[name]
            if name in ("timeline", "controls"):
                detail_layout.addSpacing(self.s(6))
            if name == "controls":
                detail_layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter)
            else:
                detail_layout.addWidget(widget)
        detail_layout.addStretch()
        self.progress.interaction_started.connect(self._begin_seek)
        self.progress.preview_changed.connect(self._preview_seek)
        self.progress.seek_requested.connect(self._finish_seek)
        self._intro.extend(
            (
                RevealEffect(self.art, 70, 810, scale=0.72, back=True),
                RevealEffect(self.title, 150, 760, offset=(self.s(25), 0)),
                RevealEffect(self.artist, 150, 760, offset=(self.s(25), 0)),
                RevealEffect(output, 150, 760, offset=(self.s(25), 0)),
                RevealEffect(timeline, 230, 760, offset=(self.s(18), self.s(9)), back=True),
                RevealEffect(self.controls, 230, 760, offset=(0, self.s(18)), back=True),
            )
        )
        if config.popup.show_equalizer:
            # QSS owns divider thickness and margins; no fixed-height clamp.
            separator = identify(QFrame(self.surface), "media-v2-separator", "separator", "media-separator")
            separator.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            separator.setVisible(config.popup.show_separator)
            self.equalizer = EqualizerPanel(
                config.popup.equalizer,
                config.scale,
                self.surface,
                effect_parent=self.surface,
            )
            if config.popup.equalizer_position == "top":
                main.insertWidget(0, self.equalizer)
                main.insertWidget(1, separator)
            else:
                main.addWidget(separator)
                main.addWidget(self.equalizer)
            self._intro.append(RevealEffect(separator, 310, 660, scale=0.8))
            self._intro.extend(self.equalizer.intro)

    def _on_output_changed(self, state: AudioOutputState):
        if not is_valid_qobject(self):
            return
        name = state.friendly_name
        full_name = name or "No output device"
        self.device.setText(full_name)
        self.device.setAccessibleName(full_name)

    def set_state(self, state, pixmap):
        old_identity = track_identity(self._state.active) if self._state else None
        active = state.active
        self._state = state
        changed = old_identity != track_identity(active)
        if changed or not (active and active.is_seekable):
            self.progress.cancel_interaction()
            self._seek_identity = None
        # Timeline snapshots must not rebuild selectors, repaint art or process backgrounds.
        content_key = (
            tuple((s.player, s.metadata, s.metadata_ready, s.playback) for s in state.sessions),
            state.active_session_id,
            state.manual_session_id,
            pixmap.cacheKey(),
        )
        if content_key != self._content_key:
            self._content_key = content_key
            self.title.setText(media_title(active))
            self.artist.setText("By " + (active.artist or "Unknown artist") if active else "")
            if changed:
                self.title.reset_scroll(empty=active is None)
                self.artist.reset_scroll(empty=active is None)
            album = active.album if active else ""
            title_tip = "\n".join(value for value in (active.title if active else "", album) if value)
            if title_tip:
                set_tooltip(self.title, title_tip)
            self.art.setAccessibleDescription(
                " — ".join(value for value in (active.title if active else "", album) if value)
            )
            self.art.set_artwork(
                pixmap,
                bool(active and active.is_playing),
                clear_previous=changed,
            )
            self.surface.set_artwork(pixmap, clear_previous=changed)
            self.surface.set_media_state(active is not None, bool(active and active.is_playing))
            self.controls.set_state(active)
            self._update_sessions(state)
            playback = active.playback.state.value if active else "empty"
            classes = f"media-v2-popup {playback}"
            if self.property("class") != classes:
                self.setProperty("class", classes)
                refresh_widget_style(self, self._popup_content)
        self.progress.setEnabled(bool(active and active.is_seekable))
        velocity = 0.0
        if active and active.is_playing and active.duration:
            velocity = active.playback.rate / active.duration
        self.progress.set_progress(active.progress if active else None, reset=changed, velocity=velocity)
        if not self.progress.interacting:
            self._set_times(active.position if active and active.timeline.known else None)

    def _set_times(self, position):
        active = self._state.active if self._state else None
        duration = active.duration if active else None
        self.elapsed.setText(format_time(position))
        if self.config.popup.time_display == "remaining" and duration is not None and position is not None:
            self.duration.setText("−" + format_time(max(0, duration - position)))
        else:
            self.duration.setText(format_time(duration))
        self.progress.setAccessibleDescription(f"{format_time(position)} of {format_time(duration)}")

    def _update_sessions(self, state):
        sessions = state.usable_sessions
        labels = session_option_labels(sessions)
        options = [(None, "Automatic")] + [(session.session_id, label) for session, label in zip(sessions, labels)]
        if options != self._session_options:
            self._session_options = options
            self.selector.blockSignals(True)
            self.selector.clear()
            for sid, name in options:
                self.selector.addItem(name, sid)
            self.selector.blockSignals(False)

        active = state.active
        selected_id = state.manual_session_id
        self.selector.blockSignals(True)
        self.selector.setCurrentIndex(next((i for i, option in enumerate(options) if option[0] == selected_id), 0))
        self.selector.blockSignals(False)
        self.selector.sync_popup()

        name = active.player.application_name if active else "Offline"
        self.source.setText("Via " + name)
        pinned = bool(state.manual_session_id)
        self.source.set_base_classes("media-source", "pinned" if pinned else "automatic")
        self.selector.set_mode("pinned" if pinned else "automatic")
        self.source.setEnabled(bool(sessions))
        self.source.setAccessibleDescription(
            ("Pinned" if pinned else "Automatic selection") + f"; active player: {name}"
        )
        self.selector.setAccessibleDescription(self.source.accessibleDescription())
        self.selector.hide()
        self.source.show()

    def _open_session_menu(self):
        if not self.source.isEnabled() or self.selector.count() <= 1:
            return
        self.selector.open_at(self.source)

    def _select_session(self, index):
        self.progress.cancel_interaction()
        self.session_selected.emit(self.selector.itemData(index))

    def _begin_seek(self):
        self._seek_identity = track_identity(self._state.active) if self._state else None

    def _preview_seek(self, fraction):
        active = self._state.active if self._state else None
        if active and active.is_seekable and active.duration is not None:
            self._set_times(fraction * active.duration)

    def _finish_seek(self, fraction):
        active = self._state.active if self._state else None
        if (
            active
            and active.is_seekable
            and active.duration is not None
            and self._seek_identity == track_identity(active)
        ):
            self.seek_requested.emit(fraction * active.duration, self._seek_identity)
        self._seek_identity = None

    def open_at_parent(self, *, focus_first=False):
        self._restore_focus_on_dismiss = False
        self.border.ensurePolished()
        self.border.layout().activate()
        self.border.setFixedHeight(self.border.layout().totalSizeHint().height())
        if hasattr(self, "equalizer"):
            self.equalizer.sync_effect_overlay()
        self.setFixedSize(self.border.size())
        self.setPosition(
            alignment=self.config.popup.alignment,
            direction=self.config.popup.direction,
            offset_left=self.s(self.config.popup.offset_left),
            offset_top=self.s(self.config.popup.offset_top),
        )
        self._open_pos = QPoint(self.pos())
        direction_sign = 1 if self.config.popup.direction == "up" else -1
        self._closed_pos = QPoint(self._open_pos.x(), self._open_pos.y() + self.s(12) * direction_sign)
        if self.isVisible():
            self._fade_animation.stop()
            self._is_closing = False
            self._fade_animation.setDuration(760)
            self._fade_animation.setEasingCurve(QEasingCurve.Type.OutQuart)
            self._fade_animation.setStartValue(self.windowOpacity())
            self._fade_animation.setEndValue(1.0)
            self._fade_animation.start()
            animate(self, "pos", self._open_pos, 760, QEasingCurve.Type.OutQuart)
        else:
            self.move(self._closed_pos)
            self.show()
        if focus_first:
            targets = (self.controls.play, self.source, self.controls.previous, self.controls.next, self.progress)
            target = next((item for item in targets if item.isVisible() and item.isEnabled()), None)
            if target is not None:
                target.setFocus(Qt.FocusReason.PopupFocusReason)

    def showEvent(self, event):
        self._fade_animation.setDuration(760)
        super().showEvent(event)
        self._fade_animation.setEasingCurve(QEasingCurve.Type.OutQuart)
        animate(self, "pos", self._open_pos, 760, QEasingCurve.Type.OutQuart)
        for effect in self._intro:
            if effect.widget.isVisible():
                effect.replay()
        if "output" in self.config.popup.detail_order and self._output_service is not None:
            self._output_service.request_refresh()

    def hide_animated(self, restore_focus=False):
        self._restore_focus_on_dismiss = self._restore_focus_on_dismiss or bool(restore_focus)
        if self._is_closing or not self.isVisible():
            return
        self.progress.cancel_interaction()
        self._seek_identity = None
        self._fade_animation.setDuration(180)
        animate(self, "pos", self._closed_pos, 180, QEasingCurve.Type.InCubic)
        super().hide_animated()

    def event(self, event):
        if event.type() == QEvent.Type.WindowDeactivate and hasattr(self, "selector") and self.selector.menu_active:
            return False
        return super().event(event)

    def eventFilter(self, obj, event):
        if self.selector.menu_active:
            return False
        return super().eventFilter(obj, event)

    def hideEvent(self, event):
        settle(self)
        for effect in self._intro:
            effect.finish()
        self.progress.cancel_interaction()
        self._seek_identity = None
        super().hideEvent(event)
        restore_focus = self._restore_focus_on_dismiss
        self._restore_focus_on_dismiss = False
        self.dismissed.emit(restore_focus)
