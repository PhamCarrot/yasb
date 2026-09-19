"""Native YASB audio visualizer with optional selected-media labeling."""

import logging
import time
from typing import Any

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QBrush, QColor, QHideEvent, QLinearGradient, QResizeEvent, QShowEvent
from PyQt6.QtWidgets import QWIDGETSIZE_MAX, QGraphicsOpacityEffect, QGridLayout, QLabel

from core.utils.utilities import ScrollingLabel
from core.validation.widgets.yasb.audio_visualizer import AudioVisualizerConfig
from core.widgets.base import BaseWidget
from core.widgets.services.audio_visualizer.loopback import AudioVisualizerCaptureService
from core.widgets.services.audio_visualizer.paint import AudioVizCanvas
from core.widgets.services.audio_visualizer.spectrum import (
    FFT_SIZE,
    SpectrumAnalyzer,
    layout_mono,
    layout_stereo,
)
from core.widgets.services.media.backend import MediaBackend
from core.widgets.services.media.model import MediaSessionState
from core.widgets.services.media.tokenizer import clean_string

logger = logging.getLogger("AudioVisualizerWidget")
_ELLIPSIS = "..."
_FADE_MAX_RATIO = 0.45


def format_media_label(
    session: MediaSessionState,
    template: str,
    separator: str,
    *,
    max_length: int,
    scrolling: bool,
) -> str:
    """Format one selected-session label without leaving orphan separators."""
    title = (session.title or "").strip()
    artist = (session.artist or "").strip()
    if not title and not artist:
        return ""
    values = {"title": title, "artist": artist, "s": separator}
    try:
        text = clean_string(template, values).format_map(values).strip()
    except KeyError, ValueError, IndexError:
        logger.warning("Invalid media label format %r, falling back to the title", template)
        text = title
    if scrolling or max_length <= 0 or len(text) <= max_length:
        return text
    if max_length <= len(_ELLIPSIS):
        return text[:max_length]
    return text[: max_length - len(_ELLIPSIS)].rstrip() + _ELLIPSIS


class _MarqueeLabel(ScrollingLabel):
    """ScrollingLabel with a pause before each pass and a clipped edge fade."""

    def __init__(
        self,
        *,
        max_chars: int | None,
        options: dict[str, Any],
        delay_ms: int,
        fade_width: int,
    ) -> None:
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
        if self._holding:
            if hasattr(self, "_scroll_timer") and self._scroll_timer.isActive():
                self._scroll_timer.stop()
            return
        super()._sync_scroll_timer()

    @pyqtSlot()
    def _scroll_text(self) -> None:
        super()._scroll_text()
        if self._scrolling_needed and not self._holding and self._offset == 0 and self.isVisible():
            self._begin_hold()

    def _restart(self) -> None:
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

    def hideEvent(self, event) -> None:
        if self._hold_timer is not None:
            self._hold_timer.stop()
        self._holding = False
        super().hideEvent(event)

    def showEvent(self, event: QShowEvent | None) -> None:
        super().showEvent(event)
        self._restart()

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        self._refresh_fade()

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
            gradient.setColorAt(0.0, opaque)
            gradient.setColorAt(1.0, opaque)
        self._fade_effect.setOpacityMask(QBrush(gradient))


def _sensitivity_mult(value: int) -> float:
    """Map config 0–100 (default 50 = 1.0*) to analyzer gain."""
    return max(0.1, min(2.0, value / 50.0))


def _wave_points(width: int) -> int:
    return max(4, min(128, width // 5))


def _resolve_edge_fade(edge_fade: int | list[int]) -> tuple[int, int]:
    # The config validator guarantees a list here is exactly [left, right].
    if isinstance(edge_fade, list):
        return int(edge_fade[0]), int(edge_fade[1])
    fade = int(edge_fade)
    return fade, fade


class _ReaderToken:
    """A widget's claim on the shared capture stream.

    Deliberately holds no reference to the widget, so it can be handed to the
    ``destroyed`` signal without keeping the widget alive.

    ``attach`` opens the claim (visible); ``set_visible`` follows the bar as it
    hides and shows, and only ``detach`` (on widget destruction) drops it.
    """

    __slots__ = ("_service", "_framerate", "_channels", "_attached", "_visible")

    def __init__(
        self,
        service: AudioVisualizerCaptureService,
        framerate: int,
        channels: frozenset[str],
    ) -> None:
        self._service = service
        self._framerate = framerate
        self._channels = channels
        self._attached = False
        self._visible = True

    def attach(self) -> None:
        if self._attached:
            return
        self._attached = True
        self._visible = True
        self._service.attach(self._framerate, self._channels)

    def detach(self) -> None:
        if not self._attached:
            return
        self._service.detach(self._framerate, self._channels, self._visible)
        self._attached = False
        self._visible = True

    def set_visible(self, visible: bool) -> None:
        if not self._attached or visible == self._visible:
            return
        self._visible = visible
        self._service.set_reader_visible(visible)


class AudioVisualizerWidget(BaseWidget):
    validation_schema = AudioVisualizerConfig

    def __init__(self, config: AudioVisualizerConfig) -> None:
        super().__init__(class_name=f"audio-visualizer-widget {config.class_name}".strip())
        self.config = config
        self._stereo = config.channels == "stereo"
        self._audio_active = False
        self._idle_hidden = False
        self._last_render_ns = 0
        self._frame_interval_ns = 1_000_000_000 // max(1, config.framerate)

        edge_left, edge_right = _resolve_edge_fade(config.edge_fade)

        self._init_container()
        smoothness = config.smoothness / 100.0
        sensitivity = _sensitivity_mult(config.sensitivity)

        columns, canvas_width, item_width, item_gap = self._resolve_style_metrics(config)
        if self._stereo:
            right_bands = max(2, columns // 2)
            left_bands = max(2, columns - right_bands)
        else:
            left_bands = right_bands = columns

        def make_analyzer(bands: int) -> SpectrumAnalyzer:
            return SpectrumAnalyzer(
                bands=bands,
                fft_size=FFT_SIZE,
                f_min=float(config.freq_min),
                f_max=float(config.freq_max),
                sensitivity=sensitivity,
                smoothness=smoothness,
                auto_gain=config.auto_gain,
            )

        self._analyzer_l = make_analyzer(left_bands)
        self._analyzer_r = make_analyzer(right_bands) if self._stereo else None

        self._canvas = AudioVizCanvas(
            style=config.style,
            height=config.height,
            columns=columns,
            canvas_width=canvas_width,
            item_width=item_width,
            item_gap=item_gap,
            mirror=config.mirror,
            stereo=self._stereo,
            edge_fade_left=edge_left,
            edge_fade_right=edge_right,
        )
        self._widget_container_layout.setContentsMargins(0, 0, 0, 0)
        self._widget_container_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
        self._label: QLabel | None = None
        self._media: MediaBackend | None = None
        self._media_key = None
        self._label_text = ""

        if config.visualizer_opacity < 1.0:
            effect = QGraphicsOpacityEffect(self._canvas)
            effect.setOpacity(config.visualizer_opacity)
            self._canvas.setGraphicsEffect(effect)

        if config.show_label:
            self._init_media_label()
            QTimer.singleShot(0, self._connect_media)
        else:
            self._widget_container_layout.addWidget(self._canvas)

        self._collapse_animation = QPropertyAnimation(self, b"maximumWidth", self)
        self._collapse_animation.setDuration(150)
        self._collapse_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._collapse_animation.finished.connect(self._on_collapse_finished)

        self.callback_left = config.callbacks.on_left
        self.callback_middle = config.callbacks.on_middle
        self.callback_right = config.callbacks.on_right

        frame_ms = max(8, 1000 // max(1, config.framerate))
        self._fade_timer = QTimer(self)
        self._fade_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._fade_timer.setInterval(frame_ms)
        self._fade_timer.timeout.connect(self._on_fade_tick)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._hide_timer.setInterval(config.hide_idle_after)
        self._hide_timer.timeout.connect(self._hide_for_idle)

        # Tell the shared service which spectra to compute for us: both for
        # stereo, otherwise just the one the mono mix draws from.
        channels = frozenset({"left", "right"}) if self._stereo else frozenset({config.mono_option})

        self._service = AudioVisualizerCaptureService.instance()
        self._token = _ReaderToken(self._service, config.framerate, channels)
        token = self._token
        self.destroyed.connect(lambda *_: token.detach())

        self._service.frame_ready.connect(self._on_frame)
        self._service.audio_stopped.connect(self._on_audio_stopped)
        self._service.format_changed.connect(self._apply_sample_rate)
        self._apply_sample_rate(self._service.sample_rate)

        if config.hide_idle:
            # Start collapsed so the bar never reserves space for a silent
            # visualizer, but stay attached so the stream can wake us.
            self._idle_hidden = True
            self._apply_collapsed(True, animate=False)
            self._token.attach()

    def _init_media_label(self) -> None:
        stack = QGridLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        stack.addWidget(self._canvas, 0, 0, Qt.AlignmentFlag.AlignCenter)

        scroll = self.config.scrolling_label
        if scroll.enabled:
            self._label = _MarqueeLabel(
                max_chars=self.config.max_label_length or None,
                options={
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
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._label.hide()
        if scroll.enabled:
            stack.addWidget(self._label, 0, 0, Qt.AlignmentFlag.AlignCenter)
        else:
            stack.addWidget(self._label, 0, 0)
        self._widget_container_layout.addLayout(stack)

    @pyqtSlot()
    def _connect_media(self) -> None:
        self._media = MediaBackend.shared()
        self._media.state_changed.connect(self._refresh_label)
        self._refresh_label()

    def _refresh_label(self, _state=None) -> None:
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
        self._label.setText(text)
        self._label.setVisible(bool(text))

    def _format_label(self, session: MediaSessionState) -> str:
        return format_media_label(
            session,
            self.config.label,
            self.config.separator,
            max_length=self.config.max_label_length,
            scrolling=self.config.scrolling_label.enabled,
        )

    def _apply_collapsed(self, collapsed: bool, *, animate: bool = True) -> None:
        """Collapse to zero width rather than ``hide()``, eased so the bar
        reflows smoothly instead of the widget popping in or out.

        A hidden widget stops receiving show/hide events, so it cannot tell
        when the bar itself is hidden and would keep the capture stream open
        forever. A zero-width widget stays visually gone but still gets the
        bar's show/hide events, so ``hideEvent`` can always release the stream.
        """
        target = 0 if collapsed else self.sizeHint().width()
        if not animate:
            self._collapse_animation.stop()
            self.setMinimumWidth(0)
            self.setMaximumWidth(target)
            self.updateGeometry()
            return
        current = self.width()
        self._collapse_animation.stop()
        self.setMinimumWidth(0)
        self._collapse_animation.setStartValue(current)
        self._collapse_animation.setEndValue(target)
        self._collapse_animation.start()

    def _on_collapse_finished(self) -> None:
        if self._idle_hidden:
            return
        self.setMaximumWidth(QWIDGETSIZE_MAX)
        self.updateGeometry()

    @staticmethod
    def _resolve_style_metrics(config: AudioVisualizerConfig) -> tuple[int, int, int, int]:
        if config.style == "waves":
            width = config.waves.width
            return _wave_points(width), width, 1, 0
        if config.style == "dots":
            d = config.dots
            return d.count, d.count * max(2, d.size + d.gap), d.size, d.gap
        b = config.bars
        return b.count, b.count * (b.width + b.gap), b.width, b.gap

    def _apply_sample_rate(self, sample_rate: int) -> None:
        self._analyzer_l.set_sample_rate(sample_rate)
        if self._analyzer_r is not None:
            self._analyzer_r.set_sample_rate(sample_rate)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._token.attach()
        # Resume the shared stream. If the bar just blinked (auto-hide, a
        # maximised window) it was only frozen, so this costs nothing.
        self._token.set_visible(True)
        if self._idle_hidden:
            # The bar came back while we were idle-collapsed: stay collapsed
            # and wait for audio to expand us again.
            return
        if not self._service.is_active:
            self._reset_visual()
            if self.config.hide_idle:
                self._hide_timer.start()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        # The idle collapse never calls hide(), so any hide event here means
        # the bar, a monitor change or a minimise hid us. Freeze the shared
        # stream (it stays open, so a re-show resumes instantly). _idle_hidden
        # and the collapsed width are left as they are.
        self._fade_timer.stop()
        self._hide_timer.stop()
        self._audio_active = False
        self._reset_visual()
        self._token.set_visible(False)

    def _reset_visual(self) -> None:
        self._analyzer_l.reset()
        if self._analyzer_r is not None:
            self._analyzer_r.reset()
        self._canvas.reset()

    def _on_frame(self) -> None:
        if self._audio_active:
            if time.monotonic_ns() - self._last_render_ns < self._frame_interval_ns:
                return
        else:
            self._audio_active = True
            self._fade_timer.stop()
            self._hide_timer.stop()
            if self._idle_hidden:
                self._idle_hidden = False
                self._apply_collapsed(False)
        self._render()

    def _frame_delta(self) -> float:
        """Seconds since the last frame, so smoothing is framerate-independent."""
        now = time.monotonic_ns()
        previous = self._last_render_ns
        self._last_render_ns = now
        if not previous:
            return 1.0 / max(1, self.config.framerate)
        return (now - previous) / 1_000_000_000.0

    def _render(self) -> None:
        dt = self._frame_delta()
        magnitudes = self._service.magnitudes
        if self._stereo and self._analyzer_r is not None:
            samples = layout_stereo(
                self._analyzer_l.map_bands(magnitudes("left"), dt),
                self._analyzer_r.map_bands(magnitudes("right"), dt),
                self.config.reverse,
            )
        else:
            bands = self._analyzer_l.map_bands(magnitudes(self.config.mono_option), dt)
            samples = layout_mono(bands, self.config.reverse)
        self._canvas.set_samples(samples)

    def _on_audio_stopped(self) -> None:
        if not self._audio_active:
            return
        self._audio_active = False
        if self._idle_hidden:
            return
        # Walk the bars down to zero rather than leaving them frozen on the
        # last captured frame. The timer stops itself once they settle.
        self._fade_timer.start()
        if self.config.hide_idle:
            self._hide_timer.start()

    def _on_fade_tick(self) -> None:
        dt = self._frame_delta()
        left, moving = self._analyzer_l.decay(dt)
        if self._stereo and self._analyzer_r is not None:
            right, moving_r = self._analyzer_r.decay(dt)
            samples = layout_stereo(left, right, self.config.reverse)
            moving = moving or moving_r
        else:
            samples = layout_mono(left, self.config.reverse)
        self._canvas.set_samples(samples)
        if not moving:
            self._fade_timer.stop()

    def _hide_for_idle(self) -> None:
        if self._audio_active or self._idle_hidden:
            return
        self._fade_timer.stop()
        self._reset_visual()
        self._idle_hidden = True
        self._apply_collapsed(True)
