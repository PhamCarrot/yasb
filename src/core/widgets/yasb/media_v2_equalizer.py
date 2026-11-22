"""Visual equalizer controls with optional Equalizer APO controller delegation."""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast

import PyQt6.QtCore as QtCore
from PyQt6.QtCore import QAbstractAnimation, QEasingCurve, QEvent, QPoint, QPointF, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QHideEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPen,
    QRadialGradient,
    QResizeEvent,
    QShowEvent,
)
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

from core.validation.widgets.yasb.media_v2 import MediaEqualizerConfig, MediaV2EqualizerPresetMotionConfig
from core.widgets.services.media.equalizer_apo import EqualizerApoController
from core.widgets.yasb.media_v2_components import CancellableSlider, MediaButton, MediaText, identify
from core.widgets.yasb.media_v2_motion import RevealEffect, animate, settle

pyqtProperty: Callable[..., Any] = getattr(QtCore, "pyqtProperty")

PRESETS = {
    "Flat": (0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    "Bass": (5, 7, 5, 2, 1, 0, 0, 0, 1, 2),
    "Treble": (-2, -1, 0, 1, 2, 3, 4, 5, 6, 6),
    "Vocal": (-2, -1, 1, 3, 5, 5, 4, 2, 1, 0),
    "Pop": (2, 4, 2, 0, 1, 2, 4, 2, 1, 2),
    "Rock": (5, 4, 2, -1, -2, -1, 2, 4, 5, 6),
    "Jazz": (3, 3, 1, 1, 1, 1, 2, 1, 2, 3),
    "Classic": (0, 1, 2, 2, 2, 2, 1, 2, 3, 4),
}


def lightning_state(milliseconds: float):
    progress = 10 * QEasingCurve(QEasingCurve.Type.OutSine).valueForProgress(min(1.0, milliseconds / 650))
    fade = QEasingCurve(QEasingCurve.Type.OutQuad).valueForProgress(max(0.0, min(1.0, (milliseconds - 800) / 800)))
    return progress, fade


def band_effect_state(milliseconds: float, index: int):
    """Return the per-band hit, sweep, ring and flash state."""
    progress, fade = lightning_state(milliseconds)
    distance = progress - index
    hit = math.sin(distance * math.pi) if 0.0 <= distance < 1.0 else 0.0
    if distance <= 0.4:
        return hit, 0.0, 0.0, 0.0, fade

    threshold = min(1.0, max(0.0, (index + 0.4) / 10))
    fired_at = math.asin(threshold) * 2 / math.pi * 650
    elapsed = max(0.0, milliseconds - fired_at)
    track = QEasingCurve(QEasingCurve.Type.OutQuart).valueForProgress(min(1.0, elapsed / 1000))
    ring = 1 - QEasingCurve(QEasingCurve.Type.OutExpo).valueForProgress(min(1.0, elapsed / 1500))
    flash = 1 - QEasingCurve(QEasingCurve.Type.OutSine).valueForProgress(min(1.0, elapsed / 1500))
    return hit, track, ring, flash, fade


def preset_band_state(mode: str, phase: float, index: int, count: int = 10):
    """Return clipped-highlight progress, opacity and overshoot for one band."""
    if mode == "ripple":
        order = index
        stagger = 60.0
    elif mode == "center_pulse":
        order = max(0, round(abs(index - (count - 1) / 2) - 0.5))
        stagger = 120.0
    else:
        return 0.0, 0.0, 0.0

    local = (float(phase) - order * stagger) / 800.0
    if local <= 0.0 or local >= 1.0:
        return 0.0, 0.0, 0.0
    curve = QEasingCurve(QEasingCurve.Type.OutBack)
    curve.setOvershoot(0.6)
    eased = curve.valueForProgress(local)
    progress = max(0.0, min(1.0, eased))
    opacity = math.sin(local * math.pi)
    overshoot = max(0.0, eased - 1.0)
    return progress, opacity, overshoot


class GainSlider(CancellableSlider):
    """One-dB user slider with a high-resolution presentation range for animation."""

    SCALE = 100
    pointer_released = pyqtSignal()

    def __init__(self, parent: QWidget | None) -> None:
        super().__init__(Qt.Orientation.Vertical, parent)
        self.gain_value = 0.0
        self.programmatic = False
        self.pointer_held = False
        self._handle_press: QPoint | None = None
        self._effect_phase = 1600.0
        self._effect_index = 0
        self.effect_mode = "none"
        self._effect_accent = QColor("#cba6f7")
        self.travel_share = 0.0
        self.setRange(-12 * self.SCALE, 12 * self.SCALE)
        self.setSingleStep(self.SCALE)
        self.setPageStep(self.SCALE)

    def mousePressEvent(self, ev: QMouseEvent | None) -> None:
        if self.pointer_held and ev is not None and ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        if ev is not None and ev.button() == Qt.MouseButton.LeftButton:
            self.pointer_held = True
            option = QStyleOptionSlider()
            self.initStyleOption(option)
            handle = cast(QStyle, self.style()).subControlRect(
                QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self
            )
            point = ev.position().toPoint()
            self._handle_press = point if handle.contains(point) else None
        self.programmatic = self._handle_press is not None
        try:
            super().mousePressEvent(ev)
        finally:
            self.programmatic = False

    def mouseMoveEvent(self, ev: QMouseEvent | None) -> None:
        if ev is not None and ev.position().toPoint() == self._handle_press:
            return
        self._handle_press = None
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev: QMouseEvent | None) -> None:
        if self.pointer_held and ev is not None and ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        held = self.pointer_held
        self.pointer_held = False
        self._handle_press = None
        down = self.isSliderDown()
        super().mouseReleaseEvent(ev)
        if held and not down:
            self.pointer_released.emit()

    def cancel_interaction(self) -> None:
        self.pointer_held = False
        self._handle_press = None
        super().cancel_interaction()

    def _get_gain(self):
        return self.gain_value

    def _set_gain(self, value: float):
        self.gain_value = max(-12.0, min(12.0, float(value)))
        self.programmatic = True
        super().setValue(round(self.gain_value * self.SCALE))
        self.programmatic = False

    gain: float = pyqtProperty(float, _get_gain, _set_gain)

    def gain_from_slider(self, value: float | None = None):
        raw = super().value() if value is None else value
        return raw / self.SCALE

    @property
    def effect_index(self) -> int:
        return self._effect_index

    @property
    def effect_accent(self) -> QColor:
        return QColor(self._effect_accent)

    def set_effect(self, phase: float, index: int, accent: QColor, mode: str | None = None):
        self._effect_phase = phase
        self._effect_index = index
        if mode is not None:
            self.effect_mode = mode
        self._effect_accent = QColor(accent)
        self.update()

    def effect_fill_path(self):
        """Return the same rounded, style-derived fill path used by internal effects."""
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = cast(QStyle, self.style()).subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self
        )
        handle = cast(QStyle, self.style()).subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self
        )
        fill = QRectF(groove)
        fill.setTop(max(fill.top(), QPointF(handle.center()).y()))
        path = QPainterPath()
        radius = max(0.0, min(fill.width(), fill.height()) / 2)
        path.addRoundedRect(fill, radius, radius)
        return fill, path

    def paintEvent(self, ev: QPaintEvent | None):
        if ev is None:
            return None
        super().paintEvent(ev)
        effect = PRESET_EFFECTS.get(self.effect_mode)
        if self._effect_phase >= 1600 or effect is None or effect.band is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        effect.band(self, painter, self._effect_phase / 1600)

    def paint_preset_highlight(self, painter: QPainter):
        progress, opacity, overshoot = preset_band_state(self.effect_mode, self._effect_phase, self._effect_index)
        if opacity <= 0:
            return
        fill, fill_path = self.effect_fill_path()
        if fill.height() <= 0:
            return

        accent = QColor(self._effect_accent)
        stripe_height = max(10.0, fill.height() * 0.22)
        center_y = fill.bottom() - progress * fill.height()
        stripe = QRectF(fill.left(), center_y - stripe_height / 2, fill.width(), stripe_height)
        gradient = QLinearGradient(stripe.topLeft(), stripe.bottomLeft())
        clear = QColor(accent)
        clear.setAlpha(0)
        color = QColor(accent).lighter(135)
        color.setAlphaF(min(1.0, opacity * 0.7))
        white = QColor("white")
        white.setAlphaF(min(1.0, opacity * (0.72 + overshoot * 2.0)))
        gradient.setColorAt(0.0, clear)
        gradient.setColorAt(0.3, color)
        gradient.setColorAt(0.5, white)
        gradient.setColorAt(0.7, color)
        gradient.setColorAt(1.0, clear)
        painter.save()
        painter.setClipPath(fill_path)
        painter.fillRect(stripe, gradient)
        if overshoot > 0:
            wash = QColor(accent)
            wash.setAlphaF(min(0.22, overshoot * opacity))
            painter.fillPath(fill_path, wash)
        painter.restore()

    def hideEvent(self, a0: QHideEvent | None):
        if a0 is None:
            return None
        settle(self)
        super().hideEvent(a0)


class EqualizerEffectOverlay(QFrame):
    """Input-transparent effect canvas spanning the full EQ section.

    Keeping the sweep/rings outside the slider row avoids QWidget paint-rect
    clipping while the actual sliders retain their original layout and hit
    targets. The effect uses layered alpha strokes instead of per-frame image
    blurs, keeping the animation cheap enough for normal popup use.
    """

    def __init__(self, bands: EqualizerBands, parent: QWidget, clip_radius: float) -> None:
        super().__init__(parent)
        self.bands = bands
        self.clip_radius = clip_radius
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

    def hideEvent(self, a0: QHideEvent | None):
        if a0 is None:
            return None
        settle(self)
        super().hideEvent(a0)

    def map_slider_point(self, slider: GainSlider, point: QPoint):
        """Map a slider-local point onto this sibling overlay safely."""
        return QPointF(self.mapFromGlobal(slider.mapToGlobal(point)))

    def points(self) -> list[QPointF]:
        points: list[QPointF] = []
        for slider in self.bands.sliders:
            point = self.map_slider_point(slider, QPoint(slider.width() // 2, 0))
            y = (
                point.y()
                + 8 * self.bands.scale
                + (1 - (slider.gain + 12) / 24) * (slider.height() - 16 * self.bands.scale)
            )
            points.append(QPointF(point.x(), y))
        return points

    def clip_to_surface(self, painter: QPainter) -> None:
        parent = self.parentWidget()
        if parent is not None and self.clip_radius > 0:
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(parent.rect().translated(-self.pos())), self.clip_radius, self.clip_radius)
            painter.setClipPath(clip)

    def paintEvent(self, a0: QPaintEvent | None):
        if a0 is None:
            return None
        effect = PRESET_EFFECTS.get(self.bands.effect_mode)
        if effect is None or effect.overlay is None or self.bands.phase >= 1600:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        effect.overlay(self, painter, self.bands.phase / 1600)


def _envelope(t: float, rise: float = 0.15, fall: float = 0.4) -> float:
    return max(0.0, min(1.0, t / rise, (1.0 - t) / fall))


def _lightning_band(slider: GainSlider, painter: QPainter, t: float) -> None:
    phase = t * 1600
    _, track, _, flash, fade = band_effect_state(phase, slider.effect_index)
    visibility = 1.0 - fade
    if visibility <= 0 or max(track, flash) <= 0:
        return

    scale = max(0.5, slider.width() / 32)
    accent = QColor(slider.effect_accent)

    fill, fill_path = slider.effect_fill_path()
    if fill.height() > 0 and flash > 0:
        overlay = QLinearGradient(fill.topLeft(), fill.bottomLeft())
        top = QColor(accent).lighter(130)
        top.setAlphaF(min(1.0, flash * visibility * 0.8))
        mid = QColor(accent)
        mid.setAlphaF(min(1.0, flash * visibility * 0.55))
        clear = QColor(accent)
        clear.setAlpha(0)
        overlay.setColorAt(0.0, top)
        overlay.setColorAt(0.5, mid)
        overlay.setColorAt(1.0, clear)
        painter.fillPath(fill_path, overlay)

    if fill.height() > 0 and 0.0 < track < 1.0:
        stripe_height = 70 * scale
        y = fill.top() + track * (fill.height() + stripe_height) - stripe_height
        stripe = QRectF(fill.left(), y, fill.width(), stripe_height)
        gradient = QLinearGradient(stripe.topLeft(), stripe.bottomLeft())
        clear = QColor(accent)
        clear.setAlpha(0)
        pulse = max(0.0, math.sin(track * math.pi)) * visibility
        bright = QColor("white")
        bright.setAlphaF(min(1.0, pulse))
        side = QColor(accent)
        side.setAlphaF(min(1.0, pulse * 0.9))
        gradient.setColorAt(0.0, clear)
        gradient.setColorAt(0.2, side)
        gradient.setColorAt(0.5, bright)
        gradient.setColorAt(0.8, side)
        gradient.setColorAt(1.0, clear)
        painter.save()
        painter.setClipPath(fill_path)
        painter.fillRect(stripe, gradient)
        painter.restore()


def _highlight_band(slider: GainSlider, painter: QPainter, t: float) -> None:
    slider.paint_preset_highlight(painter)


def _lightning_overlay(overlay: EqualizerEffectOverlay, painter: QPainter, t: float) -> None:
    phase = t * 1600
    progress, fade = lightning_state(phase)
    if progress <= 0 or fade >= 1 or len(overlay.bands.sliders) < 2:
        return
    points = overlay.points()
    visibility = 1.0 - fade
    accent = QColor(overlay.bands.accentColor)
    scale = overlay.bands.scale
    overlay.clip_to_surface(painter)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)

    # Soft ring bloom plus a crisp inner edge. Painting several cheap alpha
    # passes gives a much closer energy falloff to the QML MultiEffect source
    # without running a Gaussian blur over the popup every frame.
    for index, slider in enumerate(overlay.bands.sliders):
        point = overlay.map_slider_point(slider, QPoint(slider.width() // 2, 0))
        _, _, ring, _, _ = band_effect_state(phase, index)
        if ring <= 0:
            continue
        base = QRectF(
            0,
            0,
            (29 + ring * 34) * scale,
            slider.height() + (17 + ring * 51) * scale,
        )
        base.moveCenter(QPointF(point.x(), point.y() + slider.height() / 2))
        for extra, width, alpha in ((10, 10, 0.07), (5, 6, 0.13), (0, 2.1, 0.55)):
            rect = base.adjusted(-extra * scale, -extra * scale, extra * scale, extra * scale)
            color = QColor(accent).lighter(118 if extra == 0 else 105)
            color.setAlphaF(min(1.0, ring * visibility * alpha))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(color, width * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawRoundedRect(rect, rect.width() / 2, min(rect.width(), rect.height()) / 2)

    seconds = phase / 1000
    paths: list[QPainterPath] = []
    for layer in range(4):
        path = QPainterPath(points[0])
        for i in range(9):
            if i > progress:
                break
            fraction = min(1.0, progress - i)
            steps = 6 if layer == 3 else 8
            for j in range(1, steps + 1):
                t = min(j / steps, fraction)
                point = points[i] + (points[i + 1] - points[i]) * t
                envelope = math.sin(t * math.pi)
                noise_x = 1 if layer == 3 else (4 - layer) * 4
                noise_y = 1 if layer == 3 else (4 - layer) * 5
                sep_x = math.sin(seconds * 3 + i + j + layer) * 9 * scale * envelope if layer < 2 else 0
                sep_y = math.cos(seconds * 2.5 + i - j - layer) * 13.5 * scale * envelope if layer < 2 else 0
                point += QPointF(
                    sep_x
                    + math.sin(seconds * (10 + layer) + i + j)
                    * math.cos(seconds * 8 - i + j)
                    * noise_x
                    * envelope
                    * visibility,
                    sep_y
                    + math.cos(seconds * (9 - layer) + i - j)
                    * math.sin(seconds * 7 + i - j)
                    * noise_y
                    * envelope
                    * visibility,
                )
                path.lineTo(point)
                if t == fraction:
                    break
        paths.append(path)

    # Wide low-alpha bloom -> colored energy -> narrow white core.
    for path, width, alpha, color in (
        (paths[0], 30, 0.055, accent),
        (paths[0], 20, 0.09, accent),
        (paths[1], 11, 0.22, accent.lighter(118)),
        (paths[2], 5.2, 0.50, accent.lighter(145)),
        (paths[3], 2.1, 0.92, QColor("white")),
    ):
        color = QColor(color)
        color.setAlphaF(min(1.0, alpha * visibility))
        painter.setPen(
            QPen(color, width * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)


def _glow_band(slider: GainSlider, painter: QPainter, t: float) -> None:
    """Bloom proportional to how far this band travels."""
    distance = slider.travel_share
    strength = distance * _envelope(t, 0.12, 0.55)
    if strength <= 0:
        return
    fill, path = slider.effect_fill_path()
    accent = slider.effect_accent
    wash = QColor(accent).lighter(140)
    wash.setAlphaF(min(1.0, 0.7 * strength))
    if fill.height() > 0:
        painter.fillPath(path, wash)
    halo = QRadialGradient(QPointF(fill.center().x(), fill.top()), max(8.0, slider.width() * 0.55))
    bright = QColor(accent).lighter(160)
    bright.setAlphaF(min(1.0, 0.8 * strength))
    clear = QColor(bright)
    clear.setAlpha(0)
    halo.setColorAt(0, bright)
    halo.setColorAt(1, clear)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(halo)
    painter.drawRect(QRectF(slider.rect()))


def _scan_progress(t: float) -> float:
    return QEasingCurve(QEasingCurve.Type.InOutSine).valueForProgress(t)


def _scan_band(slider: GainSlider, painter: QPainter, t: float) -> None:
    """Flash as the scan bar crosses this band."""
    flash = max(0.0, 1 - abs(_scan_progress(t) * 1.2 - 0.1 - (slider.effect_index + 0.5) / 10) * 10 / 1.5)
    if flash <= 0:
        return
    fill, path = slider.effect_fill_path()
    color = slider.effect_accent.lighter(150)
    color.setAlphaF(min(1.0, 0.85 * flash))
    if fill.height() > 0:
        painter.fillPath(path, color)


def _scan_overlay(overlay: EqualizerEffectOverlay, painter: QPainter, t: float) -> None:
    """One light bar crossing the section."""
    width = overlay.width()
    x = (_scan_progress(t) * 1.2 - 0.1) * width
    if not -width * 0.1 <= x <= width * 1.1:
        return
    overlay.clip_to_surface(painter)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    accent = QColor(overlay.bands.accentColor)
    spread = 28 * overlay.bands.scale
    gradient = QLinearGradient(x - spread, 0, x + spread, 0)
    clear = QColor(accent)
    clear.setAlpha(0)
    core = QColor(accent).lighter(150)
    core.setAlphaF(0.5 * _envelope(t, 0.08, 0.2))
    gradient.setColorAt(0, clear)
    gradient.setColorAt(0.5, core)
    gradient.setColorAt(1, clear)
    painter.fillRect(QRectF(x - spread, 0, spread * 2, overlay.height()), gradient)


def _curve_overlay(overlay: EqualizerEffectOverlay, painter: QPainter, t: float) -> None:
    """A glowing spline through the handle centres; it follows them while they travel."""
    points = overlay.points()
    visibility = _envelope(t, 0.1, 0.45)
    if len(points) < 2 or visibility <= 0:
        return
    path = QPainterPath(points[0])
    for index in range(len(points) - 1):
        before = points[max(0, index - 1)]
        start, end = points[index], points[index + 1]
        after = points[min(len(points) - 1, index + 2)]
        path.cubicTo(start + (end - before) / 6, end - (after - start) / 6, end)
    overlay.clip_to_surface(painter)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    accent = QColor(overlay.bands.accentColor)
    scale = overlay.bands.scale
    for width, alpha, color in ((16, 0.06, accent), (8, 0.16, accent.lighter(120)), (2.4, 0.85, accent.lighter(160))):
        stroke = QColor(color)
        stroke.setAlphaF(min(1.0, alpha * visibility))
        painter.setPen(
            QPen(stroke, width * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        )
        painter.drawPath(path)


@dataclass(frozen=True)
class PresetEffect:
    """One preset transition: duration at speed 1 and paint hooks taking normalized time."""

    duration: int
    band: Callable[[GainSlider, QPainter, float], None] | None = None
    overlay: Callable[[EqualizerEffectOverlay, QPainter, float], None] | None = None


PRESET_EFFECTS: dict[str, PresetEffect] = {
    "lightning": PresetEffect(1600, _lightning_band, _lightning_overlay),
    "ripple": PresetEffect(700, _highlight_band),
    "center_pulse": PresetEffect(650, _highlight_band),
    "curve": PresetEffect(1200, overlay=_curve_overlay),
    "glow": PresetEffect(900, _glow_band),
    "scan": PresetEffect(1000, _scan_band, _scan_overlay),
}
PRESET_EFFECT_DURATIONS = {name: effect.duration for name, effect in PRESET_EFFECTS.items()}

_EASINGS = {
    "out_quart": QEasingCurve.Type.OutQuart,
    "out_cubic": QEasingCurve.Type.OutCubic,
    "out_back": QEasingCurve.Type.OutBack,
    "in_out_sine": QEasingCurve.Type.InOutSine,
}


class PresetTravel(QAbstractAnimation):
    """All ten handles on one animation; a new selection restarts from the presented gains."""

    def __init__(self, bands: EqualizerBands) -> None:
        super().__init__(bands)
        self.bands = bands
        self.configure(MediaV2EqualizerPresetMotionConfig(), 1.0)
        self.starts = [0.0] * len(bands.sliders)
        self.targets: list[float | None] = [None] * len(bands.sliders)
        self._total = 1

    def configure(self, motion: MediaV2EqualizerPresetMotionConfig, speed: float) -> None:
        self.style = motion.style
        self.travel = max(1.0, motion.duration_ms * speed)
        self.stagger = motion.stagger_ms * speed
        self.curve = QEasingCurve(_EASINGS[motion.easing])
        if self.style == "wave":
            self.curve = QEasingCurve(QEasingCurve.Type.OutBack)
            self.curve.setOvershoot(1.0)

    def duration(self) -> int:
        return self._total

    def delay(self, index: int) -> float:
        count = len(self.bands.sliders)
        outward = max(0, round(abs(index - (count - 1) / 2) - 0.5))
        order = {
            "cascade": index,
            "wave": index,
            "center_out": outward,
            "edges_in": max(0, round((count - 1) / 2 - 0.5)) - outward,
        }.get(self.style, 0)
        return order * self.stagger

    def ease(self, progress: float) -> float:
        if self.style == "spring":
            return 1 - math.exp(-6 * progress) * math.cos(10 * progress)
        return self.curve.valueForProgress(progress)

    def move(self, values: Sequence[float], held: Callable[[int], bool]) -> None:
        """Travel to new targets; identical targets leave running travel untouched."""
        bands = [index for index in range(len(values)) if not held(index)]
        if self.state() == QAbstractAnimation.State.Running and all(self.targets[i] == float(values[i]) for i in bands):
            return
        self.stop()
        sliders = self.bands.sliders
        self.targets = [float(values[i]) if i in bands else None for i in range(len(values))]
        self.starts = [slider.gain for slider in sliders]
        self.bands.travel_shares = [abs(self.starts[i] - float(values[i])) / 24 for i in range(len(values))]
        self._total = max(1, round(max((self.delay(i) for i in bands), default=0) + self.travel))
        self.start()

    def release(self, index: int) -> None:
        self.targets[index] = None

    def settle(self) -> None:
        self.stop()
        for slider, target in zip(self.bands.sliders, self.targets):
            if target is not None:
                slider.gain = target

    def updateCurrentTime(self, currentTime: int) -> None:
        for index, (slider, target) in enumerate(zip(self.bands.sliders, self.targets)):
            if target is None:
                continue
            progress = (currentTime - self.delay(index)) / self.travel
            start = self.starts[index]
            if progress <= 0:
                slider.gain = start
            elif progress >= 1:
                slider.gain = target
            else:
                slider.gain = start + (target - start) * self.ease(progress)


class EqualizerBands(QFrame):
    def __init__(self, scale: float, parent: QWidget | None) -> None:
        super().__init__(parent)
        identify(self, "media-equalizer", "equalizer")
        self.scale = scale
        self.sliders: list[GainSlider] = []
        self.intro: list[RevealEffect] = []
        self.phase = 1600.0
        self.effect_mode = "none"
        self.effect_overlay: EqualizerEffectOverlay | None = None
        self.random = random.Random()
        self._travel_shares = [0.0] * 10
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#cba6f7"))
        self.setPalette(palette)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setMinimumHeight(round(100 * scale))
        self.setMaximumHeight(round(155 * scale))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        for index, frequency in enumerate(("31", "63", "125", "250", "500", "1k", "2k", "4k", "8k", "16k")):
            band = identify(QFrame(self), "media-eq-column-" + frequency, "eq-column")
            column = QVBoxLayout(band)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(round(4 * scale))
            slider = identify(GainSlider(band), "media-eq-" + frequency, "eq-band", "band-" + frequency)
            slider.setAccessibleName(f"{frequency} Hz equalizer gain")
            slider.setFixedWidth(round(32 * scale))
            slider.set_effect(self.phase, index, self.accentColor, self.effect_mode)
            column.addWidget(slider, 1, Qt.AlignmentFlag.AlignHCenter)
            label = QLabel(frequency, band)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(label)
            layout.addWidget(band, 1)
            self.sliders.append(slider)
            self.intro.append(
                RevealEffect(
                    band, 430, 860, offset=(0, round((25 + 7 * index) * scale)), easing=QEasingCurve.Type.OutExpo
                )
            )
        self.travel = PresetTravel(self)

    def _get_accentColor(self):
        return self.palette().color(QPalette.ColorRole.WindowText)

    def _set_accentColor(self, value: QColor):
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor(value))
        self.setPalette(palette)
        for index, slider in enumerate(self.sliders):
            slider.set_effect(self.phase, index, self.accentColor, self.effect_mode)
        if self.effect_overlay is not None:
            self.effect_overlay.update()
        self.update()

    accentColor: QColor = pyqtProperty(QColor, _get_accentColor, _set_accentColor)

    def _get_lightningPhase(self):
        return self.phase

    def _set_lightningPhase(self, value: float):
        self.phase = value
        for index, slider in enumerate(self.sliders):
            slider.set_effect(value, index, self.accentColor, self.effect_mode)
        if self.effect_overlay is not None:
            self.effect_overlay.update()
        self.update()

    lightningPhase: float = pyqtProperty(float, _get_lightningPhase, _set_lightningPhase)

    def set_effect_mode(self, effect: str):
        self.effect_mode = effect
        for index, slider in enumerate(self.sliders):
            slider.set_effect(self.phase, index, self.accentColor, effect)
        if self.effect_overlay is not None:
            self.effect_overlay.update()

    @property
    def travel_shares(self) -> list[float]:
        return self._travel_shares

    @travel_shares.setter
    def travel_shares(self, shares: list[float]) -> None:
        self._travel_shares = shares
        for slider, share in zip(self.sliders, shares):
            slider.travel_share = share

    def trigger(self, effect: str = "lightning", speed: float = 1.0):
        animation = getattr(self, "_motion", {}).get("lightningPhase")
        if animation:
            animation.stop()
        if effect == "random":
            effect = self.random.choice(sorted(PRESET_EFFECTS))
        self.set_effect_mode(effect)
        self.lightningPhase = 0.0
        duration = PRESET_EFFECT_DURATIONS.get(effect, 0)
        if duration <= 0:
            self.lightningPhase = 1600.0
            return
        animate(self, "lightningPhase", 1600.0, max(1, round(duration * speed)), QEasingCurve.Type.Linear)

    def hideEvent(self, a0: QHideEvent | None):
        if a0 is None:
            return None
        settle(self)
        self.travel.settle()
        super().hideEvent(a0)

    def paintEvent(self, a0: QPaintEvent | None):
        # Slider chrome remains in this bounded row; sweep/ring energy is drawn
        # by EqualizerEffectOverlay across the full section so it cannot be
        # clipped by the 155px slider container.
        if a0 is None:
            return None
        super().paintEvent(a0)


class AdaptiveOverlay(QLabel):
    def event(self, e: QEvent | None) -> bool:
        if e is not None and e.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseMove,
            QEvent.Type.Wheel,
        ):
            e.accept()
            return True
        return super().event(e)


class EqualizerPanel(QFrame):
    caption_changed = pyqtSignal()
    header_changed = pyqtSignal()

    def __init__(
        self,
        options: MediaEqualizerConfig,
        scale: float,
        parent: QWidget | None = None,
        *,
        effect_parent: QWidget | None = None,
        effect_radius: float = 0,
    ) -> None:
        super().__init__(parent)
        identify(self, "media-equalizer-section", "equalizer-section")
        self.options = options
        self.preset = options.preset
        self._edited_drag: tuple[GainSlider, object] | None = None
        self._drag_has_edited = False
        self.apply_action_visible = False
        self.effect_mode = getattr(options, "preset_effect", "lightning")
        self.effect_speed = float(getattr(options, "effect_speed", 1.0))
        self.buttons: dict[str, MediaButton] = {}
        self._page_active = True
        self._status_detail = ""
        self._adaptive_mix = 0.0
        self._adaptive_target: bool | None = None
        self.apo = EqualizerApoController(options, self)

        def s(n: float) -> int:
            return round(n * scale)

        self.main_layout = layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(s(16))
        self.header = identify(QFrame(self), "media-equalizer-header", "equalizer-header")
        self.header_layout = header = QHBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 0)
        self.title = title = identify(
            QLabel("Equalizer", self.header), "media-equalizer-title", "equalizer-title", "title"
        )
        title.setFixedHeight(s(26))
        header.addWidget(title, 1)

        initial_status = "" if self.apo.enabled else "Visual only — Equalizer APO disabled"
        self.status = MediaText(
            "media-equalizer-status", self.header, elide=True, classes="equalizer-status label", scrollable=False
        )
        self.status.setText(initial_status)
        self.status.setVisible(bool(initial_status))
        header.addWidget(self.status, 1)

        self.current = identify(QLabel(self.preset, self), "media-equalizer-current", "equalizer-current", "label")
        header.addWidget(self.current)
        self.apply_button = MediaButton(self, "apply", "equalizer-apply")
        self.apply_button.setObjectName("media-equalizer-apply")
        self.apply_button.setFixedSize(s(92), s(28))
        self.apply_button.clicked.connect(self._apply_action)
        header.addWidget(self.apply_button)
        layout.addWidget(self.header)
        self.body = identify(QFrame(self), "media-equalizer-body", "equalizer-body")
        self.manual_opacity = QGraphicsOpacityEffect(self.body)
        self.body.setGraphicsEffect(self.manual_opacity)
        self.manual_opacity.setEnabled(False)
        self.adaptive_overlay = identify(
            AdaptiveOverlay("Adapting to your sound", self), "media-adaptive-overlay", "equalizer-adaptive-overlay"
        )
        self.adaptive_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.adaptive_overlay.setWordWrap(True)
        self.adaptive_overlay.setTextFormat(Qt.TextFormat.PlainText)
        self.adaptive_alpha = QGraphicsOpacityEffect(self.adaptive_overlay)
        self.adaptive_overlay.setGraphicsEffect(self.adaptive_alpha)
        self.adaptive_overlay.hide()

        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(s(9))
        layout.addWidget(self.body)
        self.bands = EqualizerBands(scale, self.body)
        self.bands.travel.configure(options.preset_motion, self.effect_speed)
        body_layout.addWidget(self.bands)
        self.effects = EqualizerEffectOverlay(self.bands, effect_parent or self, effect_radius)
        self.bands.effect_overlay = self.effects
        self.bands.set_effect_mode(self.effect_mode)

        presets = identify(QFrame(self.body), "media-presets", "presets")
        rows = QVBoxLayout(presets)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(s(7))
        names = list(PRESETS)
        for start in (0, 4):
            row = QHBoxLayout()
            row.setSpacing(s(8))
            for name in names[start : start + 4]:
                button = MediaButton(presets, "preset", name.lower())
                button.setObjectName("media-preset-" + name.lower())
                button.setText(name)
                button.setCheckable(True)
                button.setFixedHeight(s(28))
                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

                def select(checked: bool = False, name: str = name) -> None:
                    self.select_preset(name)

                button.clicked.connect(select)
                self.buttons[name] = button
                row.addWidget(button, 1)
            rows.addLayout(row)
        body_layout.addWidget(presets)

        self.apo.status_changed.connect(self._on_apo_status)
        self.apo.committed_changed.connect(self._present_gains)
        self.apo.draft_changed.connect(self._sync_apply)
        self.destroyed.connect(lambda *_: self.apo.shutdown())
        for index, slider in enumerate(self.bands.sliders):

            def change(value: int, slider: GainSlider = slider, index: int = index) -> None:
                self._custom(index, slider, slider.gain_from_slider(value))

            def interrupt(slider: GainSlider = slider) -> None:
                self._edited_drag = None
                self._drag_has_edited = False
                self._interrupt(slider)

            def release(slider: GainSlider = slider, index: int = index) -> None:
                self._release_custom(index, slider)

            slider.valueChanged.connect(change)
            slider.sliderPressed.connect(interrupt)
            slider.sliderReleased.connect(release)
            slider.pointer_released.connect(release)
        values = self.options.custom_bands if self.preset == "Custom" else PRESETS[self.preset]
        self.apo.start(values)
        self._sync_apply()
        self.intro = [
            RevealEffect(title, 370, 710, offset=(s(12), 0)),
            *self.bands.intro,
            RevealEffect(presets, 550, 810, offset=(0, s(18)), back=True),
        ]
        self.sync_effect_overlay()

    def _get_adaptive_mix(self) -> float:
        return self._adaptive_mix

    def _set_adaptive_mix(self, value: float) -> None:
        self._adaptive_mix = max(0.0, min(1.0, value))
        self.manual_opacity.setOpacity(1 - 0.7 * self._adaptive_mix)
        self.manual_opacity.setEnabled(self._adaptive_mix > 0)
        self.adaptive_alpha.setOpacity(self._adaptive_mix)
        self._place_adaptive_overlay()

    adaptiveMix: float = pyqtProperty(float, _get_adaptive_mix, _set_adaptive_mix)

    def _place_adaptive_overlay(self) -> None:
        parent = self.adaptive_overlay.parentWidget()
        if parent is not None:
            self.adaptive_overlay.setGeometry(parent.rect())
        self.adaptive_overlay.setVisible(self._page_active and self.isVisible() and self._adaptive_mix > 0.01)
        self.adaptive_overlay.raise_()

    def sync_effect_overlay(self):
        parent = self.effects.parentWidget()
        if parent is None:
            return
        origin = parent.mapFromGlobal(self.body.mapToGlobal(QPoint()))
        room = round(52 * self.bands.scale)
        bounds = QRect(origin, self.body.size()).adjusted(-room, -room, room, room)
        self.effects.setGeometry(bounds.intersected(parent.rect()))
        self.effects.setVisible(self._page_active and self.isVisible())
        if self._page_active:
            self.effects.raise_()
        self._place_adaptive_overlay()

    def set_page_active(self, active: bool, *, preserve_motion: bool = False) -> None:
        self._page_active = active
        if not active:
            settle(self.bands)
            for effect in self.intro:
                if not preserve_motion and (effect.widget is self.body or self.body.isAncestorOf(effect.widget)):
                    effect.finish()
            self.discard_draft()
        self.sync_effect_overlay()

    def _duration(self, milliseconds: float):
        # effect_speed is a duration multiplier: <1 faster, >1 slower.
        return max(1, round(milliseconds * self.effect_speed))

    def select_preset(self, name: str, motion: bool = True):
        values = self.options.custom_bands if name == "Custom" else PRESETS[name]
        self._edited_drag = None
        self.preset = name
        accepted = self.apo.apply_preset(values)
        if not accepted or tuple(values) != self.apo.editing_gains:
            self._present_gains(self.apo.editing_gains, motion=accepted)
            return
        self._show_gains(tuple(values), motion)
        self._sync_selection()
        if motion and self._page_active and self.isVisible() and self.effect_mode != "none":
            self.bands.trigger(self.effect_mode, self.effect_speed)

    def _show_gains(self, values: tuple[float, ...], motion: bool) -> None:
        visible = self._page_active and self.isVisible()
        sliders, travel = self.bands.sliders, self.bands.travel

        def held(index: int) -> bool:
            return visible and sliders[index].isSliderDown()

        if motion and visible:
            travel.move(values, held)
            return
        for index, (slider, gain) in enumerate(zip(sliders, values)):
            if not held(index):
                travel.release(index)
                slider.gain = float(gain)

    def _present_gains(self, values: tuple[float, ...], *, motion: bool = True):
        """Hydrate shared intent without submitting a write or starting a preset effect."""
        self._edited_drag = None
        self.preset = next((name for name, gains in PRESETS.items() if tuple(gains) == values), "Custom")
        self._show_gains(values, motion and self.preset != "Custom")
        if not self._hold_drag_header():
            self._sync_selection()

    def _interrupt(self, slider: GainSlider):
        self.bands.travel.release(self.bands.sliders.index(slider))

    def _custom(self, index: int, slider: GainSlider, value: float, *, expected_draft: object | None = None):
        if slider.programmatic or not self._page_active:
            return
        self._interrupt(slider)
        slider.gain_value = float(value)
        # A tween only changes presentation. Untouched bands come from the
        # controller's complete preset or the most recent complete draft.
        curve = list(self.apo.editing_gains)
        curve[index] = value
        accepted, draft = self.apo.edit_custom(curve, expected_draft=expected_draft)
        if not accepted or draft is not None and self.apo.draft_identity is not draft:
            slider.cancel_interaction()
            self._present_gains(self.apo.editing_gains, motion=False)
        elif draft is not None:
            if slider.isSliderDown():
                self._edited_drag = (slider, draft)
                self._drag_has_edited = True
            self.preset = "Custom"
            self._sync_selection()

    def _release_custom(self, index: int, slider: GainSlider):
        edited, self._edited_drag = self._edited_drag, None
        self._drag_has_edited = False
        if not self._page_active:
            return
        if edited is not None and edited[0] is slider:
            self._custom(index, slider, float(round(slider.gain_from_slider())), expected_draft=edited[1])
        slider.gain = self.apo.editing_gains[index]
        self._sync_selection()
        self._sync_apply()

    def discard_draft(self):
        self._edited_drag = None
        self._drag_has_edited = False
        self.apo.discard_custom()

    def _apply_action(self):
        self._edited_drag = None
        action = self.apply_button.text()
        if action == "Reconnect":
            self.apo.reconnect_writer()
        elif action == "Review":
            self.apo.review_custom()
        else:
            self.apo.apply_custom()
        self._sync_apply()

    def _hold_drag_header(self) -> bool:
        return self._drag_has_edited and any(slider.isSliderDown() for slider in self.bands.sliders)

    def _sync_apply(self):
        previous_text = self.apply_button.text()
        previous_visible = self.apply_action_visible
        adaptive = self.apo.audio_state.adaptive
        restoring = self.apo.restoring
        restore_required = self.apo.restore_required
        writer_available = self.apo.writer_available
        review = self.apo.draft_needs_review
        editable = self.apo.draft_available
        available = editable and not adaptive and not restoring and not restore_required and not review
        if adaptive != self._adaptive_target:
            self._adaptive_target = adaptive
            if self.isVisible():
                animate(self, "adaptiveMix", 1.0 if adaptive else 0.0, 250, QEasingCurve.Type.OutCubic)
            else:
                self.adaptiveMix = 1.0 if adaptive else 0.0
        for slider in self.bands.sliders:
            if not available and (slider.pointer_held or slider.isSliderDown()):
                slider.cancel_interaction()
            slider.setEnabled(available)
        for button in self.buttons.values():
            button.setEnabled(available)
        if not writer_available:
            text, enabled = "Reconnect", True
        elif review:
            text, enabled = "Review", True
        elif restore_required:
            text, enabled = "Restore", True
        elif restoring:
            if not editable:
                text, enabled = "Editing elsewhere", False
            else:
                text, enabled = ("Retry", True) if self.apo.write_failed else ("Loading…", False)
        elif adaptive:
            text, enabled = ("Saving…" if self.apo.pending else "Saved"), False
        elif not available:
            text, enabled = "Editing elsewhere", False
        elif self.apo.has_draft:
            text, enabled = "Apply", available
        elif self.apo.write_failed:
            text, enabled = "Retry", available
        elif self.apo.pending:
            text, enabled = "Saving…", False
        else:
            text, enabled = ("Saved" if self.apo.enabled else "Visual only"), False
        status = self._status_detail.partition("\n")[0]
        show_status = status not in {"", "Saved", "Visual only", "Applying…", "Saving…", "Loading…"}
        if text in {"Apply", "Saved", "Visual only", "Saving…"} and any(
            slider.pointer_held or slider.isSliderDown() for slider in self.bands.sliders
        ):
            if previous_visible and previous_text == "Apply":
                text = "Apply"
            elif text == "Apply":
                text, enabled = ("Saved" if self.apo.enabled else "Visual only"), False
        visible = show_status or text in {"Apply", "Retry", "Reconnect", "Review", "Restore"}
        if not visible and previous_text == "Apply" and self.status.property("compact_header"):
            text = previous_text
        self.apply_action_visible = visible
        self.apply_button.setText(text)
        self.apply_button.setEnabled(enabled)
        self.apply_button.setAccessibleName("Apply equalizer changes" if text == "Apply" else text)
        self.apply_button.setAccessibleDescription(self._status_detail)
        if previous_text != text or previous_visible != visible:
            self.header_changed.emit()

    def _on_apo_status(self, status: str, detail: str):
        self._status_detail = "\n".join(filter(None, (status, detail)))
        self.status.setText(status)
        self.status.setAccessibleDescription(detail)
        self.status.setVisible(bool(status) and not self.status.property("compact_header"))
        self.setAccessibleDescription("\n".join((status, detail)))
        self.current.setAccessibleDescription(detail)
        self.header.setAccessibleDescription(detail)
        self._sync_apply()
        self.header_changed.emit()

    def _sync_selection(self):
        caption_changed = self.current.text() != self.preset
        if caption_changed:
            self.current.setText(self.preset)
        for name, button in self.buttons.items():
            button.setChecked(name == self.preset)
        if caption_changed:
            self.caption_changed.emit()

    def resizeEvent(self, a0: QResizeEvent | None):
        if a0 is None:
            return None
        super().resizeEvent(a0)
        if hasattr(self, "effects"):
            self.sync_effect_overlay()

    def showEvent(self, a0: QShowEvent | None):
        if a0 is None:
            return None
        super().showEvent(a0)
        self.sync_effect_overlay()

    def hideEvent(self, a0: QHideEvent | None):
        if a0 is None:
            return None
        settle(self)
        self.effects.hide()
        self.discard_draft()
        super().hideEvent(a0)
