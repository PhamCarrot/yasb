"""MediaPopup's 25-second disc and 60 radial bars, using the existing shared FFT."""

import math
import time

from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QRadialGradient

from core.widgets.services.audio_visualizer.spectrum import FFT_SIZE, SpectrumAnalyzer
from core.widgets.yasb.media_v2_components import AlbumArt


def rhythm_targets(bass, kick, strength=1.0, size=224.0):
    """Return smoothed-motion targets for the disc's scale, bounce and tilt."""
    strength = max(0.0, float(strength))
    bass = max(0.0, min(1.0, float(bass)))
    kick = max(0.0, min(1.0, float(kick)))
    scale = 1.0 + strength * (bass * 0.025 + kick * 0.045)
    bounce = -strength * kick * max(0.0, float(size)) * 0.012
    tilt = 0.0
    if bass > 0.12 or kick > 0.08:
        tilt = strength * ((bass - 0.28) * 0.75 + kick * 0.42)
        tilt = max(-1.2, min(1.2, tilt))
    return scale, bounce, tilt


def reactive_levels(source, count=60):
    if not source:
        return [0.0] * count, 0.0, 0.0
    sample = lambda i: source[i] if i < len(source) else 0.0
    sub = sample(0) * 0.50 + sample(1) * 0.35 + sample(2) * 0.15
    punch = sample(1) * 0.30 + sample(2) * 0.45 + sample(3) * 0.25
    raw = max(sub, punch)
    kick = min(1.0, ((raw - 0.10) / 0.90) ** 1.8 * 1.4) if raw > 0.10 else 0.0
    bass = max(0.0, min(1.0, sub * 0.6 + punch * 0.4))
    levels = []
    for i in range(count):
        pos = (i / max(1, count - 1)) ** 1.15 * (len(source) - 1)
        low = int(pos)
        val = source[low] + (source[min(low + 1, len(source) - 1)] - source[low]) * (pos - low)
        levels.append(max(0.0, min(1.0, val)) ** 1.08)
    return levels, bass, kick


class _CaptureLease:
    def __init__(self, fps):
        self.service = None
        self.fps = fps
        self.channels = frozenset({"average"})
        self.attached = False

    def attach(self):
        if self.attached:
            return
        if self.service is None:
            from core.widgets.services.audio_visualizer.loopback import AudioVisualizerCaptureService

            self.service = AudioVisualizerCaptureService.instance()
        self.service.attach(self.fps, self.channels)
        self.attached = True

    def detach(self):
        if self.attached:
            self.service.detach(self.fps, self.channels, True)
            self.attached = False


class DiscArt(AlbumArt):
    PAUSE_DECAY_SECONDS = 1.5
    MAX_BAR_HEIGHT_LOGICAL = 10.0
    MAX_BOUNCE_LOGICAL = 2.0
    EDGE_INSET_LOGICAL = 0.75

    def __init__(self, options, parent=None):
        super().__init__(parent, vinyl=True)
        self.options = options
        self._levels = [0.0] * 60
        self._bass = self._kick = 0.0
        self._rhythm_offset_y = 0.0
        self._rhythm_tilt = 0.0
        self._last_tick = 0.0
        self._decay_started = 0.0
        self._decay_snapshot = None
        self._sample_rate = None
        self._analyzer = SpectrumAnalyzer(
            bands=24,
            fft_size=FFT_SIZE,
            f_min=50.0,
            f_max=12000.0,
            sensitivity=1.0,
            smoothness=0.55,
            auto_gain=True,
        )
        self._lease = _CaptureLease(options.framerate)
        lease = self._lease
        self.destroyed.connect(lambda *_: lease.detach())
        self._clock = QTimer(self)
        self._clock.setInterval(round(1000 / options.framerate))
        self._clock.timeout.connect(self._tick)

    def set_artwork(self, pixmap, playing=False, *, clear_previous=False):
        was_playing = self._playing
        super().set_artwork(pixmap, playing, clear_previous=clear_previous)
        self._sync_clock(was_playing=was_playing)

    def _reset_reactive_state(self):
        self._decay_snapshot = None
        self._analyzer.reset()
        self._levels = [0.0] * 60
        self._bass = self._kick = 0.0
        self._rhythm_scale = 1.0
        self._rhythm_offset_y = 0.0
        self._rhythm_tilt = 0.0

    def _begin_decay(self):
        self._decay_started = time.monotonic()
        self._last_tick = self._decay_started
        self._decay_snapshot = (
            tuple(self._levels),
            self._bass,
            self._kick,
            self._rhythm_scale,
            self._rhythm_offset_y,
            self._rhythm_tilt,
        )
        if not self._clock.isActive():
            self._clock.start()

    def _sync_clock(self, *, was_playing=False):
        active = self.isVisible() and self._playing
        capture_effect = self.options.visualizer or self.options.rhythm or self.options.glow
        if active and capture_effect:
            self._lease.attach()
        else:
            self._lease.detach()
        if active and (self.options.spin or capture_effect):
            self._decay_snapshot = None
            if not self._clock.isActive():
                self._last_tick = time.monotonic()
                self._clock.start()
        elif self.isVisible() and was_playing and capture_effect:
            self._begin_decay()
        elif self.isVisible() and self._decay_snapshot is not None:
            if not self._clock.isActive():
                self._clock.start()
        else:
            self._clock.stop()
            self._reset_reactive_state()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_clock()

    def hideEvent(self, event):
        self._clock.stop()
        self._lease.detach()
        self._reset_reactive_state()
        super().hideEvent(event)

    def _logical_scale(self):
        return max(0.01, min(self.contentsRect().width(), self.contentsRect().height()) / 224.0)

    def _effect_limits(self):
        content = self.contentsRect()
        available = max(0.0, (min(content.width(), content.height()) - 1) / 2)
        logical_scale = self._logical_scale()
        bar_height = self.MAX_BAR_HEIGHT_LOGICAL * logical_scale
        bounce = self.MAX_BOUNCE_LOGICAL * logical_scale
        base_radius = available * 0.86 * max(1.0, self._disc_scale)
        pen_width = max(2.0 * logical_scale, 2 * math.pi * base_radius * 1.05 / 60 * 0.65)
        bounce = min(
            bounce,
            max(0.0, available - self.EDGE_INSET_LOGICAL * logical_scale - base_radius - bar_height - pen_width / 2),
        )
        safe_radius = max(
            0.0,
            available - self.EDGE_INSET_LOGICAL * logical_scale - bar_height - pen_width / 2 - bounce,
        )
        max_rhythm_scale = max(1.0, safe_radius / base_radius) if base_radius else 1.0
        return available, bar_height, bounce, pen_width, max_rhythm_scale

    def _tick_decay(self, now):
        if self._decay_snapshot is None:
            self._clock.stop()
            return
        progress = min(1.0, max(0.0, (now - self._decay_started) / self.PAUSE_DECAY_SECONDS))
        remaining = (1.0 - progress) ** 2
        levels, bass, kick, scale, offset, tilt = self._decay_snapshot
        self._levels = [level * remaining for level in levels]
        self._bass = bass * remaining
        self._kick = kick * remaining
        self._rhythm_scale = 1.0 + (scale - 1.0) * remaining
        self._rhythm_offset_y = offset * remaining
        self._rhythm_tilt = tilt * remaining
        if progress >= 1.0:
            self._clock.stop()
            self._reset_reactive_state()
        self.update()

    def _tick(self):
        now = time.monotonic()
        if not self._playing:
            self._last_tick = now
            self._tick_decay(now)
            return
        dt = min(0.25, max(0.0, now - self._last_tick))
        self._last_tick = now
        if self.options.spin:
            self._angle = (self._angle + dt * 360 / 25) % 360
        if self._lease.attached:
            service = self._lease.service
            if self._sample_rate != service.sample_rate:
                self._sample_rate = service.sample_rate
                self._analyzer.set_sample_rate(self._sample_rate)
            if service.is_active:
                bands = self._analyzer.map_bands(service.magnitudes("average"), dt)
            else:
                bands, _ = self._analyzer.decay(dt)
            self._levels, self._bass, self._kick = reactive_levels(bands)
        strength = max(0.0, float(getattr(self.options, "rhythm_strength", 1.0))) if self.options.rhythm else 0.0
        scale_target, bounce_target, tilt_target = rhythm_targets(
            self._bass,
            self._kick,
            strength,
            min(self.contentsRect().width(), self.contentsRect().height()),
        )
        _, _, max_bounce, _, max_rhythm_scale = self._effect_limits()
        scale_target = min(scale_target, max_rhythm_scale)
        bounce_target = max(-max_bounce, min(max_bounce, bounce_target))
        self._rhythm_scale += (scale_target - self._rhythm_scale) * (1 - math.exp(-dt * 18))
        self._rhythm_offset_y += (bounce_target - self._rhythm_offset_y) * (1 - math.exp(-dt * 22))
        self._rhythm_tilt += (tilt_target - self._rhythm_tilt) * (1 - math.exp(-dt * 14))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        content = self.contentsRect()
        center = QPointF(content.center()) + QPointF(0, self._rhythm_offset_y)
        painter.translate(center)
        painter.rotate(self._rhythm_tilt)
        painter.translate(-center)
        available, max_bar_height, _, max_pen_width, _ = self._effect_limits()
        radius = available * 0.86 * self._disc_scale * self._rhythm_scale
        margin = available * 0.14
        glow_strength = max(0.0, float(getattr(self.options, "glow_strength", 1.0)))
        if self.options.glow and self._playing and glow_strength > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            # Layered radial blooms approximate the QML blur stack without a
            # per-frame Gaussian blur or temporary full-popup image.
            for outer_scale, base_alpha, kick_alpha in (
                (1.42, 0.055, 0.050),
                (1.22, 0.090, 0.085),
                (1.08, 0.140, 0.120),
            ):
                outer = min(
                    radius + margin * outer_scale,
                    available - self.EDGE_INSET_LOGICAL * self._logical_scale() - abs(self._rhythm_offset_y),
                )
                glow = QRadialGradient(center, outer)
                color = QColor(self.accentColor)
                color.setAlphaF(min(1.0, glow_strength * (base_alpha + self._kick * kick_alpha)))
                edge = max(0.0, min(0.98, (radius - 5) / outer))
                clear = QColor(color)
                clear.setAlpha(0)
                glow.setColorAt(0.0, clear)
                glow.setColorAt(max(0.0, edge - 0.08), clear)
                glow.setColorAt(edge, color)
                glow.setColorAt(min(1.0, edge + 0.09), QColor(color.red(), color.green(), color.blue(), 0))
                glow.setColorAt(1.0, Qt.GlobalColor.transparent)
                painter.setBrush(glow)
                painter.drawEllipse(center, outer, outer)
        if self.options.visualizer:
            painter.save()
            painter.translate(center)
            width = min(max_pen_width, max(2.0 * self._logical_scale(), 2 * math.pi * radius / 60 * 0.65))
            for i, level in enumerate(self._levels):
                color = QColor(self.accentColor).lighter(round(100 + ((i / 60) * 0.4 + level * 0.6) * 45))
                color.setAlphaF(0.4 + level * 0.6)
                painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                height = min(max_bar_height, max(2.0 * self._logical_scale(), level * margin * 1.4))
                painter.drawLine(QPointF(0, -radius), QPointF(0, -radius - height))
                painter.rotate(6)
            painter.restore()
        painter.end()
        super().paintEvent(event)
