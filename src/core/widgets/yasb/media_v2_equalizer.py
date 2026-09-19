"""Visual equalizer controls with optional Equalizer APO controller delegation."""

import math

from PyQt6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, Qt, pyqtProperty
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPalette, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
)

from core.utils.tooltip import set_tooltip
from core.widgets.services.media.equalizer_apo import EqualizerApoController
from core.widgets.yasb.media_v2_components import MediaButton, identify
from core.widgets.yasb.media_v2_motion import RevealEffect, animate, settle

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


def lightning_state(milliseconds):
    progress = 10 * QEasingCurve(QEasingCurve.Type.OutSine).valueForProgress(min(1.0, milliseconds / 650))
    fade = QEasingCurve(QEasingCurve.Type.OutQuad).valueForProgress(max(0.0, min(1.0, (milliseconds - 800) / 800)))
    return progress, fade


def band_effect_state(milliseconds, index):
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


class GainSlider(QSlider):
    """One-dB user slider with a high-resolution presentation range for animation."""

    SCALE = 100

    def __init__(self, parent):
        super().__init__(Qt.Orientation.Vertical, parent)
        self._gain = 0.0
        self.programmatic = False
        self._effect_phase = 1600.0
        self._effect_index = 0
        self._effect_accent = QColor("#cba6f7")
        self.setRange(-12 * self.SCALE, 12 * self.SCALE)
        self.setSingleStep(self.SCALE)
        self.setPageStep(self.SCALE)
        self.sliderReleased.connect(self.snap_to_step)

    @pyqtProperty(float)
    def gain(self):
        return self._gain

    @gain.setter
    def gain(self, value):
        self._gain = max(-12.0, min(12.0, float(value)))
        self.programmatic = True
        super().setValue(round(self._gain * self.SCALE))
        self.programmatic = False

    def gain_from_slider(self, value=None):
        raw = super().value() if value is None else value
        return raw / self.SCALE

    def snap_to_step(self):
        if self.programmatic:
            return
        snapped = float(round(self.gain_from_slider()))
        self._gain = snapped
        self.programmatic = True
        super().setValue(round(snapped * self.SCALE))
        self.programmatic = False

    def set_effect(self, phase, index, accent):
        self._effect_phase = phase
        self._effect_index = index
        self._effect_accent = QColor(accent)
        self.update()

    def effect_fill_path(self):
        """Return the same rounded, style-derived fill path used by internal effects."""
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self
        )
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self
        )
        fill = QRectF(groove)
        fill.setTop(max(fill.top(), QPointF(handle.center()).y()))
        path = QPainterPath()
        radius = max(0.0, min(fill.width(), fill.height()) / 2)
        path.addRoundedRect(fill, radius, radius)
        return fill, path

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._effect_phase >= 1600:
            return

        _, track, _, flash, fade = band_effect_state(self._effect_phase, self._effect_index)
        visibility = 1.0 - fade
        if visibility <= 0 or max(track, flash) <= 0:
            return

        scale = max(0.5, self.width() / 32)
        accent = QColor(self._effect_accent)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        fill, fill_path = self.effect_fill_path()
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

    def hideEvent(self, event):
        settle(self)
        super().hideEvent(event)


class EqualizerEffectOverlay(QFrame):
    """Input-transparent effect canvas spanning the full EQ section.

    Keeping the sweep/rings outside the slider row avoids QWidget paint-rect
    clipping while the actual sliders retain their original layout and hit
    targets. The effect uses layered alpha strokes instead of per-frame image
    blurs, keeping the animation cheap enough for normal popup use.
    """

    def __init__(self, bands, parent):
        super().__init__(parent)
        self.bands = bands
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

    def hideEvent(self, event):
        settle(self)
        super().hideEvent(event)

    def _map_slider_point(self, slider, point):
        """Map a slider-local point onto this sibling overlay safely."""
        return QPointF(self.mapFromGlobal(slider.mapToGlobal(point)))

    def _points(self):
        points = []
        for slider in self.bands.sliders:
            point = self._map_slider_point(slider, QPoint(slider.width() // 2, 0))
            y = (
                point.y()
                + 8 * self.bands.scale
                + (1 - (slider.gain + 12) / 24) * (slider.height() - 16 * self.bands.scale)
            )
            points.append(QPointF(point.x(), y))
        return points

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        progress, fade = lightning_state(self.bands._phase)
        if progress <= 0 or fade >= 1 or len(self.bands.sliders) < 2:
            return
        points = self._points()
        visibility = 1.0 - fade
        accent = QColor(self.bands.accentColor)
        scale = self.bands.scale
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)

        # Soft ring bloom plus a crisp inner edge. Painting several cheap alpha
        # passes gives a much closer energy falloff to the QML MultiEffect source
        # without running a Gaussian blur over the popup every frame.
        for index, slider in enumerate(self.bands.sliders):
            point = self._map_slider_point(slider, QPoint(slider.width() // 2, 0))
            _, _, ring, _, _ = band_effect_state(self.bands._phase, index)
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

        seconds = self.bands._phase / 1000
        paths = []
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


class EqualizerBands(QFrame):
    def __init__(self, scale, parent):
        super().__init__(parent)
        identify(self, "media-equalizer", "equalizer")
        self.scale = scale
        self.sliders = []
        self._phase = 1600.0
        self.effect_overlay = None
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#cba6f7"))
        self.setPalette(palette)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setFixedHeight(round(155 * scale))
        for index, frequency in enumerate(("31", "63", "125", "250", "500", "1k", "2k", "4k", "8k", "16k")):
            column = QVBoxLayout()
            column.setSpacing(round(4 * scale))
            slider = identify(GainSlider(self), "media-eq-" + frequency, "eq-band", "band-" + frequency)
            slider.setAccessibleName(f"{frequency} Hz equalizer gain")
            slider.setFixedWidth(round(32 * scale))
            slider.set_effect(self._phase, index, self.accentColor)
            column.addWidget(slider, 1, Qt.AlignmentFlag.AlignHCenter)
            label = QLabel(frequency, self)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(label)
            layout.addLayout(column, 1)
            self.sliders.append(slider)

    @pyqtProperty(QColor)
    def accentColor(self):
        return self.palette().color(QPalette.ColorRole.WindowText)

    @accentColor.setter
    def accentColor(self, value):
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor(value))
        self.setPalette(palette)
        for index, slider in enumerate(self.sliders):
            slider.set_effect(self._phase, index, self.accentColor)
        if self.effect_overlay is not None:
            self.effect_overlay.update()
        self.update()

    @pyqtProperty(float)
    def lightningPhase(self):
        return self._phase

    @lightningPhase.setter
    def lightningPhase(self, value):
        self._phase = value
        for index, slider in enumerate(self.sliders):
            slider.set_effect(value, index, self.accentColor)
        if self.effect_overlay is not None:
            self.effect_overlay.update()
        self.update()

    def trigger(self, speed=1.0):
        animation = getattr(self, "_motion", {}).get("lightningPhase")
        if animation:
            animation.stop()
        self.lightningPhase = 0.0
        animate(self, "lightningPhase", 1600.0, max(1, round(1600 * speed)), QEasingCurve.Type.Linear)

    def hideEvent(self, event):
        settle(self)
        super().hideEvent(event)

    def paintEvent(self, event):
        # Slider chrome remains in this bounded row; sweep/ring energy is drawn
        # by EqualizerEffectOverlay across the full section so it cannot be
        # clipped by the 155px slider container.
        super().paintEvent(event)


class EqualizerPanel(QFrame):
    def __init__(self, options, scale, parent=None, *, effect_parent=None):
        super().__init__(parent)
        identify(self, "media-equalizer-section", "equalizer-section")
        self.options = options
        self.preset = options.preset
        self.effect_mode = getattr(options, "preset_effect", "lightning")
        self.effect_speed = float(getattr(options, "effect_speed", 1.0))
        self.buttons = {}
        self.apo = EqualizerApoController(options, self)
        s = lambda n: round(n * scale)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(s(12))
        header = QHBoxLayout()
        title = identify(QLabel("Equalizer", self), "media-equalizer-title", "equalizer-title", "title")
        title.setFixedHeight(s(26))
        header.addWidget(title, 1)

        initial_status = "" if self.apo.enabled else "Visual only — Equalizer APO disabled"
        self.status = identify(QLabel(initial_status, self), "media-equalizer-status", "equalizer-status", "label")
        self.status.setVisible(bool(initial_status))
        header.addWidget(self.status)

        self.current = identify(QLabel(self.preset, self), "media-equalizer-current", "equalizer-current", "label")
        header.addWidget(self.current)
        layout.addLayout(header)

        self.bands = EqualizerBands(scale, self)
        layout.addWidget(self.bands)
        self._effect_parent = effect_parent or self
        self.effects = EqualizerEffectOverlay(self.bands, self._effect_parent)
        self.bands.effect_overlay = self.effects

        presets = identify(QFrame(self), "media-presets", "presets")
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
                set_tooltip(button, f"Apply {name} equalizer preset")
                button.clicked.connect(lambda checked=False, name=name: self.select_preset(name))
                self.buttons[name] = button
                row.addWidget(button, 1)
            rows.addLayout(row)
        layout.addWidget(presets)

        self.apo.status_changed.connect(self._on_apo_status)
        self.destroyed.connect(lambda *_: self.apo.shutdown())
        for slider in self.bands.sliders:
            slider.valueChanged.connect(
                lambda value, slider=slider: self._custom(slider, slider.gain_from_slider(value))
            )
            slider.sliderPressed.connect(lambda slider=slider: self._interrupt(slider))
            slider.sliderReleased.connect(self._release_custom)
        self.select_preset(self.preset, motion=False)
        self.intro = [
            RevealEffect(title, 370, 710, offset=(s(12), 0)),
            RevealEffect(self.bands, 430, 860, offset=(0, s(12))),
            RevealEffect(presets, 550, 810, offset=(0, s(12)), back=True),
        ]
        self.sync_effect_overlay()

    def sync_effect_overlay(self):
        parent = self.effects.parentWidget()
        if parent is None:
            return
        self.effects.setGeometry(parent.rect() if parent is not self else self.rect())
        self.effects.show()
        self.effects.raise_()

    def _duration(self, milliseconds):
        # effect_speed is a duration multiplier: <1 faster, >1 slower.
        return max(1, round(milliseconds * self.effect_speed))

    def select_preset(self, name, motion=True):
        values = self.options.custom_bands if name == "Custom" else PRESETS[name]
        self.preset = name
        self.apo.apply_preset(values)
        for slider, gain in zip(self.bands.sliders, values):
            if motion and self.isVisible():
                animate(slider, "gain", float(gain), self._duration(350), QEasingCurve.Type.OutQuart)
            else:
                settle(slider)
                slider.gain = float(gain)
            set_tooltip(slider, f"Gain: {float(gain):+g} dB")
        self._sync_selection()
        if motion and self.isVisible():
            if self.effect_mode == "lightning":
                self.bands.trigger(self.effect_speed)

    def _interrupt(self, slider):
        animation = getattr(slider, "_motion", {}).get("gain")
        if animation:
            animation.stop()

    def _custom(self, slider, value):
        if slider.programmatic:
            return
        self._interrupt(slider)
        slider._gain = float(value)
        set_tooltip(slider, f"Gain: {round(value):+d} dB")
        if self.preset != "Custom":
            self.preset = "Custom"
            self._sync_selection()
        self.apo.update_custom(self._current_gains())

    def _release_custom(self):
        if self.preset == "Custom":
            self.apo.update_custom(self._current_gains(), final=True)

    def _current_gains(self):
        return tuple(slider.gain_from_slider() for slider in self.bands.sliders)

    def _on_apo_status(self, status, detail):
        self.status.setText(status)
        if detail:
            set_tooltip(self.status, detail)
        self.status.setAccessibleDescription(detail)
        self.status.setVisible(bool(status))

    def _sync_selection(self):
        self.current.setText(self.preset)
        for name, button in self.buttons.items():
            button.setChecked(name == self.preset)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "effects"):
            self.sync_effect_overlay()

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_effect_overlay()

    def hideEvent(self, event):
        self.effects.hide()
        super().hideEvent(event)
