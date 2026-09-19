"""Audio visualizer with selected media metadata drawn over its canvas."""

import logging
from typing import Any

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QBrush, QColor, QLinearGradient, QResizeEvent, QShowEvent
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QGridLayout, QLabel

from core.utils.utilities import ScrollingLabel
from core.validation.widgets.yasb.media_visualizer import MediaVisualizerConfig
from core.widgets.services.media.backend import MediaBackend
from core.widgets.services.media.model import MediaSessionState
from core.widgets.services.media.tokenizer import clean_string
from core.widgets.yasb.audio_visualizer import AudioVisualizerWidget

logger = logging.getLogger("MediaVisualizerWidget")

_ELLIPSIS = "..."
# Each edge fade is capped to this share of the label width so a readable
# band always remains in the middle, even on very narrow labels.
_FADE_MAX_RATIO = 0.45


class _MarqueeLabel(ScrollingLabel):
    """ScrollingLabel with a pause before each pass and an edge fade.

    Metrics, the scroll timer and painting are the inherited implementation
    used by the Media widgets. This class only:

    - holds the scroll timer for ``delay_ms`` whenever the text (re)starts
      from its first pixel (new title, label shown, or a completed pass);
    - masks its own left/right edges with a ``QGraphicsOpacityEffect`` while
      scrolling, so clipped text fades out instead of cutting off. Static
      text that fits is never masked.
    """

    def __init__(
        self,
        *,
        max_chars: int | None,
        options: dict[str, Any],
        delay_ms: int,
        fade_width: int,
    ) -> None:
        # Read by the overridden _sync_scroll_timer during the base __init__.
        self._holding = False
        self._hold_timer: QTimer | None = None
        self._fade_effect: QGraphicsOpacityEffect | None = None
        self._delay_ms = max(0, delay_ms)
        self._fade_width = max(0, fade_width)
        super().__init__(None, "", max_chars, options)

        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._hold_timer.timeout.connect(self._release_hold)

        if self._fade_width > 0:
            self._fade_effect = QGraphicsOpacityEffect(self)
            self._fade_effect.setOpacity(1.0)
            self.setGraphicsEffect(self._fade_effect)
            self._refresh_fade()

    # -- pause before scrolling -------------------------------------------

    def _begin_hold(self) -> None:
        if self._delay_ms <= 0 or self._hold_timer is None:
            return
        self._holding = True
        if self._scroll_timer.isActive():
            self._scroll_timer.stop()
        self._hold_timer.start(self._delay_ms)

    def _release_hold(self) -> None:
        self._holding = False
        self._sync_scroll_timer()

    def _sync_scroll_timer(self) -> None:
        # The base class calls this from every tick, show and resize; while
        # holding, the scroll timer must stay stopped.
        if self._holding:
            if hasattr(self, "_scroll_timer") and self._scroll_timer.isActive():
                self._scroll_timer.stop()
            return
        super()._sync_scroll_timer()

    @pyqtSlot()
    def _scroll_text(self) -> None:
        super()._scroll_text()
        # Offset 0 again means a full pass completed: pause on the start.
        if self._scrolling_needed and not self._holding and self._offset == 0 and self.isVisible():
            self._begin_hold()

    def _restart(self) -> None:
        """Park the text at its first pixel and (re)arm the pause."""
        if self._hold_timer is not None:
            self._hold_timer.stop()
        self._holding = False
        if self._scrolling_needed:
            self._offset = 0
            self._begin_hold()
        self._refresh_fade()
        self.update()

    def setText(self, a0: str | None) -> None:
        if a0 == self.text():
            return
        super().setText(a0)
        self._restart()

    def hideEvent(self, event):
        if self._hold_timer is not None:
            self._hold_timer.stop()
        self._holding = False
        super().hideEvent(event)

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        self._restart()

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        self._refresh_fade()

    # -- edge fade ---------------------------------------------------------

    def _refresh_fade(self) -> None:
        if self._fade_effect is None:
            return
        transparent = QColor(0, 0, 0, 0)
        opaque = QColor(0, 0, 0, 255)
        gradient = QLinearGradient(0.0, 0.0, 1.0, 0.0)
        gradient.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
        if self._scrolling_needed:
            ratio = min(_FADE_MAX_RATIO, self._fade_width / max(1.0, float(self.width())))
            gradient.setColorAt(0.0, transparent)
            gradient.setColorAt(ratio, opaque)
            gradient.setColorAt(1.0 - ratio, opaque)
            gradient.setColorAt(1.0, transparent)
        else:
            # Text that fits is not clipped, so it gets no fade.
            gradient.setColorAt(0.0, opaque)
            gradient.setColorAt(1.0, opaque)
        self._fade_effect.setOpacityMask(QBrush(gradient))


class MediaVisualizerWidget(AudioVisualizerWidget):
    validation_schema = MediaVisualizerConfig

    def __init__(self, config: MediaVisualizerConfig) -> None:
        # The base widget owns capture, spectrum analysis and idle behavior.
        super().__init__(config)
        self.config: MediaVisualizerConfig = config
        self._widget_frame.setProperty("class", f"widget media-visualizer-widget {config.class_name}".strip())

        self._label: QLabel | None = None
        self._media: MediaBackend | None = None
        self._media_key = None
        self._label_text = ""

        # Apply opacity only to the canvas so the sibling label stays legible.
        if config.visualizer_opacity < 1.0:
            effect = QGraphicsOpacityEffect(self._canvas)
            effect.setOpacity(config.visualizer_opacity)
            self._canvas.setGraphicsEffect(effect)

        if not config.show_label:
            return

        # The label is added after the canvas so it paints in front.
        self._widget_container_layout.removeWidget(self._canvas)
        stack = QGridLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        stack.addWidget(self._canvas, 0, 0, Qt.AlignmentFlag.AlignCenter)

        scroll = config.scrolling_label
        if scroll.enabled:
            self._label = _MarqueeLabel(
                # ScrollingLabel caps its width at this many average characters;
                # anything wider scrolls. None (from 0) means unbounded.
                max_chars=config.max_label_length or None,
                options={
                    # One pixel per tick, so pixels/second -> ms per tick.
                    "update_interval_ms": round(1000 / scroll.speed),
                    "style": scroll.style,
                    "separator": scroll.separator,
                    "always_scroll": False,
                    "label_padding": 0,
                },
                delay_ms=scroll.delay,
                fade_width=scroll.fade_width if scroll.edge_fade else 0,
            )
        else:
            self._label = QLabel()
        self._label.setProperty("class", "media-label")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Let clicks reach the visualizer widget and its configured callbacks.
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._label.hide()
        if scroll.enabled:
            # Size the marquee to its own hint (capped at max_label_length) and
            # centre it: short titles stay static, long ones scroll in place.
            stack.addWidget(self._label, 0, 0, Qt.AlignmentFlag.AlignCenter)
        else:
            stack.addWidget(self._label, 0, 0)
        self._widget_container_layout.addLayout(stack)

        # Shared singleton: no second session manager. Signals are emitted on
        # the Qt thread by the qasync loop, and both connections are plain
        # bound-method slots, so Qt drops them when this widget is destroyed.
        QTimer.singleShot(0, self._connect_media)

    @pyqtSlot()
    def _connect_media(self):
        self._media = MediaBackend.shared()
        self._media.state_changed.connect(self._refresh_label)
        self._refresh_label()

    def _refresh_label(self, state=None) -> None:
        """Ignore timeline-only snapshots; format only changed session metadata."""
        if self._label is None or self._media is None:
            return
        session = self._media.state.active
        key = (session.session_id, session.title, session.artist) if session else None
        if key == self._media_key:
            return
        self._media_key = key
        text = self._format_label(session) if session is not None else ""
        if text == self._label_text:
            return
        self._label_text = text
        if text:
            self._label.setText(text)
            self._label.show()
        else:
            # No usable media: clear rather than leave a stale title behind.
            self._label.setText("")
            self._label.hide()

    def _format_label(self, session: MediaSessionState) -> str:
        title = (session.title or "").strip()
        artist = (session.artist or "").strip()
        if not title and not artist:
            return ""
        values = {"title": title, "artist": artist, "s": self.config.separator}
        try:
            # clean_string drops empty placeholders and any {s} separator that
            # no longer has a value on both sides, so "{artist}{s}{title}"
            # never renders as " - Title".
            text = clean_string(self.config.label, values).format_map(values)
        except KeyError, ValueError, IndexError:
            logger.warning("Invalid media label format %r, falling back to the title", self.config.label)
            text = title
        text = text.strip()
        if self.config.scrolling_label.enabled:
            # The marquee shows the full text and scrolls what does not fit.
            return text
        return self._truncate(text)

    def _truncate(self, text: str) -> str:
        limit = self.config.max_label_length
        if limit <= 0 or len(text) <= limit:
            return text
        if limit <= len(_ELLIPSIS):
            return text[:limit]
        return text[: limit - len(_ELLIPSIS)].rstrip() + _ELLIPSIS
