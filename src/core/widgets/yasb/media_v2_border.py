"""MediaPopup's charging, rotating border, repainting only the narrow border region."""

import time

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, pyqtProperty
from PyQt6.QtGui import QBrush, QColor, QConicalGradient, QPainter, QPainterPath, QPen, QRegion
from PyQt6.QtWidgets import QFrame


def lower_left_clockwise_path(rect: QRectF, radius: float) -> QPainterPath:
    """Rounded-rect path with a deterministic lower-left clockwise start."""
    radius = max(0.0, min(float(radius), rect.width() / 2, rect.height() / 2))
    left, top, right, bottom = rect.left(), rect.top(), rect.right(), rect.bottom()
    path = QPainterPath(QPointF(left, bottom - radius))
    path.lineTo(left, top + radius)
    path.quadTo(left, top, left + radius, top)
    path.lineTo(right - radius, top)
    path.quadTo(right, top, right, top + radius)
    path.lineTo(right, bottom - radius)
    path.quadTo(right, bottom, right - radius, bottom)
    path.lineTo(left + radius, bottom)
    path.quadTo(left, bottom, left, bottom - radius)
    path.closeSubpath()
    return path


class MediaBorder(QFrame):
    def __init__(self, radius, scale=1.0, parent=None, options=None):
        super().__init__(parent)
        self.radius = radius
        self.scale = scale
        self.framerate = int(getattr(options, "framerate", 60))
        # The content slightly underlaps the inner half of the animated stroke.
        # Keeping these radii concentric removes the transparent crescent that
        # otherwise appears at rounded corners.
        self.content_inset = max(1, round(2 * self.scale))
        self.content_radius = max(0.0, float(self.radius - self.content_inset))
        self.charge_duration = max(0.001, float(getattr(options, "charge_duration", 1.2)))
        self.rotation_duration = max(0.001, float(getattr(options, "rotation_duration", 5.0)))
        self._animated = True
        self._started = 0.0
        self._colors = [QColor("#cba6f7"), QColor("#89b4fa"), QColor("#f38ba8")]
        self._from_colors = self._colors[:]
        self._palette_started = 0.0
        self._artwork_colors = True
        self._timer = QTimer(self)
        self._timer.setInterval(max(8, round(1000 / max(1, self.framerate))))
        self._timer.timeout.connect(self._tick)

    @pyqtProperty(bool)
    def artworkColors(self):
        return self._artwork_colors

    @artworkColors.setter
    def artworkColors(self, value):
        self._artwork_colors = value

    def _blended_colors(self):
        amount = QEasingCurve(QEasingCurve.Type.InOutQuad).valueForProgress(
            min(1.0, max(0.0, (time.monotonic() - self._palette_started) / 0.8))
        )
        return [
            QColor.fromRgbF(*(a * (1 - amount) + b * amount for a, b in zip(old.getRgbF(), new.getRgbF())))
            for old, new in zip(self._from_colors, self._colors)
        ]

    def set_palette(self, colors):
        if not self._artwork_colors or len(colors) < 3:
            return
        self._from_colors = self._blended_colors()
        self._colors = [QColor(color) for color in colors[:3]]
        self._palette_started = time.monotonic()
        self._tick()

    @pyqtProperty(bool)
    def animated(self):
        return self._animated

    @animated.setter
    def animated(self, value):
        self._animated = value
        if value and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    @pyqtProperty(QColor)
    def firstColor(self):
        return self._colors[0]

    @firstColor.setter
    def firstColor(self, value):
        self._colors[0] = QColor(value)

    @pyqtProperty(QColor)
    def secondColor(self):
        return self._colors[1]

    @secondColor.setter
    def secondColor(self, value):
        self._colors[1] = QColor(value)

    @pyqtProperty(QColor)
    def thirdColor(self):
        return self._colors[2]

    @thirdColor.setter
    def thirdColor(self, value):
        self._colors[2] = QColor(value)

    def _tick(self):
        inset = max(4, round(5 * self.scale))
        self.update(QRegion(self.rect()) - QRegion(self.rect().adjusted(inset, inset, -inset, -inset)))

    def showEvent(self, event):
        super().showEvent(event)
        self._started = time.monotonic()
        if self._animated:
            self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        if not self._animated:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        elapsed = max(0.0, time.monotonic() - self._started)
        rotation = (elapsed % self.rotation_duration) / self.rotation_duration * 360.0
        gradient = QConicalGradient(QRectF(self.rect()).center(), -rotation)
        colors = self._blended_colors()
        for stop, color in zip((0.0, 0.33, 0.66, 1.0), colors + colors[:1]):
            gradient.setColorAt(stop, color)
        width = 3 * self.scale
        rect = QRectF(self.rect()).adjusted(width / 2, width / 2, -width / 2, -width / 2)
        path = lower_left_clockwise_path(rect, self.radius)
        pen = QPen(QBrush(gradient), width)
        charge = QEasingCurve(QEasingCurve.Type.OutCubic).valueForProgress(min(1.0, elapsed / self.charge_duration))
        if charge < 1:
            perimeter = path.length() / width
            pen.setDashPattern([perimeter, perimeter])
            pen.setDashOffset(perimeter * (1 - charge))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
