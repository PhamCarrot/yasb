"""Independent YASB media widget. Configuration type: yasb.media_v2.MediaWidgetV2."""

import asyncio
import logging
from collections import OrderedDict

from PyQt6.QtCore import QBuffer, QByteArray, QEasingCurve, QIODevice, QSize, Qt, QTimer, pyqtProperty, pyqtSlot
from PyQt6.QtGui import QImage, QImageReader, QPixmap
from PyQt6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QVBoxLayout

from core.utils.qobject import is_valid_qobject
from core.utils.tooltip import set_tooltip
from core.utils.utilities import refresh_widget_style
from core.validation.widgets.yasb.media_v2 import MediaV2Config
from core.widgets.base import BaseWidget
from core.widgets.services.media.backend import MediaBackend
from core.widgets.services.media.model import MediaState
from core.widgets.yasb.media_v2_components import (
    AlbumArt,
    InfoButton,
    MediaText,
    TransportControls,
    format_time,
    identify,
    media_title,
    track_identity,
)
from core.widgets.yasb.media_v2_motion import animate, settle
from core.widgets.yasb.media_v2_popup import MediaPopup
from core.widgets.yasb.media_v2_styles import media_styles

logger = logging.getLogger("MediaV2")


def decode_artwork(data, extent):
    """Worker-only QImage decode/resize. QPixmap creation stays on the GUI thread."""
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isEmpty() or size.width() * size.height() > 100_000_000:
        return QImage()
    reader.setScaledSize(size.scaled(QSize(extent, extent), Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    if not image.isNull():
        image = image.scaled(
            extent, extent, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
    return image


class MediaWidgetV2(BaseWidget):
    validation_schema = MediaV2Config

    def __init__(self, config: MediaV2Config, backend=None):
        super().__init__(class_name=f"media-v2-widget {config.class_name}".strip())
        self.config = config
        self.s = lambda value: round(value * config.scale)
        self.backend = backend
        self._state = MediaState()
        self._pixmap = QPixmap()
        self._art_key = None
        self._art_task = None
        self._art_cache = OrderedDict()
        self._rendered_identity = None
        self._compact = float(config.compact)
        self._compact_target = config.compact
        self._sync_widget_class()
        self._visibility = 0.0 if config.hide_empty else 1.0
        self._shown = not config.hide_empty
        self.dialog = None
        identify(self, "media-v2")
        self.setAccessibleName("Media Widget V2")
        if config.use_default_styles:
            self.setStyleSheet(media_styles(config))
        # Match the normal BaseWidget hierarchy: widget -> widget-container -> content.
        self._init_container()
        self.bar_surface = identify(QFrame(self._widget_container), "media-v2-bar", "media-v2-bar")
        self._widget_container_layout.addWidget(self.bar_surface)
        self._opacity = QGraphicsOpacityEffect(self._widget_container)
        self._widget_container.setGraphicsEffect(self._opacity)
        self._opacity.setOpacity(self._visibility)
        self._opacity.setEnabled(self._visibility < 1.0)
        self._row = QHBoxLayout(self.bar_surface)
        self.info = InfoButton(self.bar_surface)
        self._info_row = QHBoxLayout(self.info)
        self._info_row.setContentsMargins(0, 0, 0, 0)
        self.art = AlbumArt(self.info)
        self.art.shape = config.artwork_shape
        self._info_row.addWidget(self.art, 0, Qt.AlignmentFlag.AlignVCenter)
        self.text_column = identify(QFrame(self.info), "media-v2-text")
        self.text_column.setVisible(config.layout != "minimal")
        self.text_column.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        column = QVBoxLayout(self.text_column)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        bar_scrolling = config.scrolling_label
        self.title = MediaText(
            "media-v2-title",
            self.text_column,
            elide=not bar_scrolling.enabled,
            classes="media-title title",
            scrollable=bar_scrolling.enabled,
            scroll_speed=bar_scrolling.speed,
            scroll_delay=bar_scrolling.delay,
        )
        self.time = MediaText("media-v2-time", self.text_column, elide=True, classes="media-time")
        column.addWidget(self.title)
        column.addWidget(self.time)
        self._info_row.addWidget(self.text_column)
        self._row.addWidget(self.info)
        self.controls = TransportControls(
            config.scale * config.controls.scale,
            self.bar_surface,
            compact=config.compact,
        )
        self._row.addWidget(self.controls)
        self._wire_controls(self.controls)
        self._popup_input_mode = None
        self.info.clicked.connect(self._activate_info)
        self.callback_left = config.callbacks.on_left
        self.callback_middle = config.callbacks.on_middle
        self.callback_right = config.callbacks.on_right
        self.register_callback("toggle_media_menu", self.toggle_media_menu)
        self.register_callback("play_pause", lambda: self._action("play_pause"))
        self.register_callback("previous", lambda: self._action("previous"))
        self.register_callback("next", lambda: self._action("next"))
        self.register_callback("automatic_selection", lambda: self._select_session(None))
        self.register_callback("toggle_compact", self.toggle_compact)
        self._layout_metrics()
        self._render()
        if config.hide_empty:
            self.hide()
        # YASB constructs widgets before qasync starts; acquire the singleton only
        # after its event loop is running. No widget owns/closes the shared service.
        QTimer.singleShot(0, self._connect_backend)

    @pyqtSlot()
    def _connect_backend(self):
        if self.backend is None:
            self.backend = MediaBackend.shared()
        self.backend.state_changed.connect(self._on_state)
        self.backend.action_finished.connect(self._action_finished)
        self._on_state(self.backend.state)

    def _sync_widget_class(self):
        tokens = ["widget", "media-v2-widget", *self.config.class_name.split()]
        if self._compact_target:
            tokens.append("compact")
        value = " ".join(dict.fromkeys(token for token in tokens if token))
        if self._widget_frame.property("class") != value:
            self._widget_frame.setProperty("class", value)
            refresh_widget_style(self._widget_frame)

    def _wire_controls(self, controls):
        controls.previous.clicked.connect(lambda: self._action("previous"))
        controls.play.clicked.connect(lambda: self._action("play_pause"))
        controls.next.clicked.connect(lambda: self._action("next"))

    def _action(self, action):
        if self.backend:
            getattr(self.backend, action)()

    def _select_session(self, sid):
        if self.backend:
            self.backend.select_session(sid)

    def _activate_info(self):
        input_mode = self.info.take_activation_mode()
        self._popup_input_mode = input_mode
        self._run_callback(self.callback_left)
        if self._popup_input_mode == input_mode:
            self._popup_input_mode = None

    @pyqtSlot(object)
    def _on_state(self, state):
        old_identity = track_identity(self._state.active)
        self._state = state
        identity = track_identity(state.active)
        self._update_artwork(identity)
        self._render()
        if old_identity != identity:
            self.title.reset_scroll(empty=state.active is None)
        visible = state.active is not None or not self.config.hide_empty
        if visible != self._shown:
            self._shown = visible
            if visible:
                self.show()
            elif self.dialog:
                self.dialog.hide_animated()
            animation = animate(self, "reveal", float(visible), 600, QEasingCurve.Type.OutQuint)
            if not getattr(self, "_visibility_connected", False):
                animation.finished.connect(self._finish_visibility)
                self._visibility_connected = True

    def _update_artwork(self, identity):
        active = self._state.active
        artwork = active.artwork if active else None
        cache_key = (
            None if not artwork or not artwork.data else (artwork.content_hash or hash(artwork.data), self.s(448))
        )
        key = (identity, cache_key)
        if key == self._art_key:
            return
        identity_changed = self._art_key is not None and self._art_key[0] != identity
        self._art_key = key
        if cache_key is None:
            self._pixmap = QPixmap()
            return
        cached = self._art_cache.get(cache_key)
        if cached is not None:
            self._art_cache.move_to_end(cache_key)
            self._pixmap = cached
            self._render()
            return
        if identity_changed:
            # Never present a previous session's cover while the newly
            # selected identity is still decoding. Same-track progressive
            # replacements retain the current pixmap until ready.
            self._pixmap = QPixmap()
        # Cancelling to_thread does not cancel its decoder. Coalesce rapid track
        # changes behind one worker instead of accumulating abandoned decodes.
        if self._art_task and not self._art_task.done():
            return
        self._art_task = asyncio.get_running_loop().create_task(self._load_latest_art())
        # Disconnect each finished task so track changes do not accumulate slots.
        task = self._art_task
        cancel = lambda: task.cancel()
        self.destroyed.connect(cancel)
        task.add_done_callback(lambda done: self._release_task(cancel))

    def _release_task(self, cancel):
        if is_valid_qobject(self):
            self.destroyed.disconnect(cancel)

    def _remember_art(self, cache_key, pixmap):
        self._art_cache[cache_key] = pixmap
        self._art_cache.move_to_end(cache_key)
        while len(self._art_cache) > 4:
            self._art_cache.popitem(last=False)

    async def _load_latest_art(self):
        while is_valid_qobject(self):
            key = self._art_key
            active = self._state.active
            if not active or not active.artwork.data:
                return
            cache_key = (active.artwork.content_hash or hash(active.artwork.data), self.s(448))
            cached = self._art_cache.get(cache_key)
            if cached is not None:
                self._art_cache.move_to_end(cache_key)
                if key == self._art_key:
                    self._pixmap = cached
                    self._render()
                return
            await self._load_art(key, active.artwork.data, cache_key)
            if not is_valid_qobject(self) or key == self._art_key:
                return

    async def _load_art(self, key, data, cache_key):
        try:
            image = await asyncio.to_thread(decode_artwork, data, self.s(448))
            if not is_valid_qobject(self):
                return
            pixmap = QPixmap.fromImage(image)
            self._remember_art(cache_key, pixmap)
            if key == self._art_key:
                self._pixmap = pixmap
                if image.isNull():
                    logger.debug("Media artwork decode returned no image")
                self._render()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Unable to load media artwork", exc_info=True)
            if is_valid_qobject(self):
                failed = QPixmap()
                self._remember_art(cache_key, failed)
                if key == self._art_key:
                    self._pixmap = failed
                    self._render()

    def _render(self):
        active = self._state.active
        identity = track_identity(active)
        identity_changed = identity != self._rendered_identity
        self.title.setText(media_title(active))
        self.time.setText(
            f"{format_time(active.position if active.timeline.known else None)} / {format_time(active.duration)}"
            if active
            else ""
        )
        self.time.setVisible(active is not None)
        set_tooltip(
            self.info,
            "\n".join(
                filter(
                    None,
                    (
                        active.title if active else "Nothing playing",
                        active.artist if active else "",
                        active.album if active else "",
                        active.player.application_name if active else "",
                        self._state.error,
                    ),
                )
            ),
        )
        self.art.set_artwork(
            self._pixmap,
            bool(active and active.is_playing),
            clear_previous=identity_changed,
        )
        self._rendered_identity = identity
        self.controls.set_state(active)
        if self.dialog and self.dialog.isVisible():
            self.dialog.set_state(self._state, self._pixmap)

    def toggle_media_menu(self):
        input_mode = self._popup_input_mode or "keyboard"
        self._popup_input_mode = None
        if self.dialog is None:
            self.dialog = MediaPopup(self, self.config)
            self._wire_controls(self.dialog.controls)
            self.dialog.session_selected.connect(self._select_session)
            self.dialog.seek_requested.connect(self._seek)
            self.dialog.dismissed.connect(self._popup_dismissed)
        if self.dialog.isVisible() and not self.dialog._is_closing:
            self.dialog.hide_animated(restore_focus=input_mode == "keyboard")
        else:
            self.dialog.set_state(self._state, self._pixmap)
            self.dialog.open_at_parent(focus_first=input_mode == "keyboard")
            self.info.setAccessibleDescription("Expanded media player")

    def _popup_dismissed(self, restore_focus):
        self.info.setAccessibleDescription("Collapsed media player")
        if restore_focus and self.isVisible() and self.info.isEnabled():
            self.info.setFocus(Qt.FocusReason.PopupFocusReason)

    def _seek(self, seconds, identity):
        if self.backend and identity == track_identity(self.backend.state.active):
            self.backend.seek(seconds)
        elif self.dialog:
            self.dialog.progress.reject_seek()

    @pyqtSlot(str, str, bool)
    def _action_finished(self, sid, action, accepted):
        if sid != self._state.active_session_id:
            return
        if not accepted:
            self.info.setAccessibleDescription(f"Player did not accept {action}")
            if self.dialog and action == "seek":
                self.dialog.progress.reject_seek()
                self.dialog.set_state(self._state, self._pixmap)

    def wheelEvent(self, event):
        if self.backend and event.angleDelta().y():
            self.backend.switch_session(1 if event.angleDelta().y() > 0 else -1)
            event.accept()
        else:
            event.ignore()

    def toggle_compact(self):
        self._compact_target = not self._compact_target
        self._sync_widget_class()
        animate(self, "compactAmount", float(self._compact_target), 600, QEasingCurve.Type.OutQuint)

    @pyqtProperty(float)
    def compactAmount(self):
        return self._compact

    @compactAmount.setter
    def compactAmount(self, value):
        self._compact = value
        self._layout_metrics()

    @pyqtProperty(float)
    def reveal(self):
        return self._visibility

    @reveal.setter
    def reveal(self, value):
        self._visibility = value
        self._opacity.setEnabled(value < 1.0)
        self._opacity.setOpacity(value)
        self.setFixedWidth(round(self.bar_surface.width() * value))

    def _finish_visibility(self):
        if not self._shown:
            self.hide()

    def _layout_metrics(self):
        c = self._compact
        side = self.s(8 - 2 * c)
        gap = self.s(8 - 2 * c)
        info_gap = self.s(10 - 2 * c)
        art = self.s(28 - 2 * c)
        column = self.s(120 - 4 * c)
        if self.config.layout == "minimal":
            column = info_gap = 0
        height = self.s(self.config.bar_height)
        control_scale = self.config.scale * self.config.controls.scale
        self.controls.set_metrics(scale=control_scale, compact=c, maximum_size=height)
        button = self.controls.play.width()
        spacing = self.controls.layout().spacing()
        self._row.setContentsMargins(side, 0, side, 0)
        self._row.setSpacing(gap)
        self._info_row.setSpacing(info_gap)
        self.art.setFixedSize(art, art)
        self.art.radius = self.s(10 - c)
        self.text_column.setFixedWidth(column)
        self.info.setFixedSize(art + info_gap + column, height)
        for control in (self.controls.previous, self.controls.play, self.controls.next):
            control.set_shape(self.config.controls_shape, self.s(10 - c))
        width = 2 * side + art + info_gap + column + gap + 3 * button + 2 * spacing
        self.bar_surface.setFixedSize(width, height)
        self._widget_container.setFixedSize(width, height)
        self.setFixedHeight(height)
        self.setFixedWidth(round(width * self._visibility))
        # The stylesheet owns rounded geometry; integer masks create jagged edges.
        self.bar_surface.clearMask()

    def hideEvent(self, event):
        settle(self)
        if self.dialog:
            self.dialog.hide_animated()
        super().hideEvent(event)
