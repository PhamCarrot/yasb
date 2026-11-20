"""MediaPopup's charging, rotating border, repainting only the narrow border region."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import PyQt6.QtCore as QtCore
from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QHideEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QRegion,
    QShowEvent,
)
from PyQt6.QtWidgets import QFrame, QWidget

from core.validation.widgets.yasb.media_v2 import MediaBorderConfig

pyqtProperty: Callable[..., Any] = getattr(QtCore, "pyqtProperty")


def lower_left_clockwise_path(rect: QRectF, radius: float) -> QPainterPath:
    """Rounded-rect path with a deterministic lower-left clockwise start."""
    radius = max(0.0, min(float(radius), rect.width() / 2, rect.height() / 2))
    left, top, right, bottom = rect.left(), rect.top(), rect.right(), rect.bottom()
    diameter = 2 * radius
    path = QPainterPath(QPointF(left, bottom - radius))
    path.lineTo(left, top + radius)
    path.arcTo(QRectF(left, top, diameter, diameter), 180, -90)
    path.lineTo(right - radius, top)
    path.arcTo(QRectF(right - diameter, top, diameter, diameter), 90, -90)
    path.lineTo(right, bottom - radius)
    path.arcTo(QRectF(right - diameter, bottom - diameter, diameter, diameter), 0, -90)
    path.lineTo(left + radius, bottom)
    path.arcTo(QRectF(left, bottom - diameter, diameter, diameter), 270, -90)
    path.closeSubpath()
    return path


class MediaBorder(QFrame):
    def __init__(
        self, radius: float, scale: float = 1.0, parent: QWidget | None = None, options: MediaBorderConfig | None = None
    ) -> None:
        super().__init__(parent)
        self.radius = radius
        self.scale = scale
        self.framerate = int(getattr(options, "framerate", 60))
        # The content slightly underlaps the inner half of the animated stroke.
        # Keeping these radii concentric removes the transparent crescent that
        # otherwise appears at rounded corners.
        self.content_inset = max(1, round(3 * self.scale))
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
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(max(8, 1000 // max(1, self.framerate)))
        self._timer.timeout.connect(self._tick)

    def _get_artworkColors(self):
        return self._artwork_colors

    def _set_artworkColors(self, value: bool):
        self._artwork_colors = value

    artworkColors: bool = pyqtProperty(bool, _get_artworkColors, _set_artworkColors)

    def _blended_colors(self):
        amount = QEasingCurve(QEasingCurve.Type.InOutQuad).valueForProgress(
            min(1.0, max(0.0, (time.monotonic() - self._palette_started) / 0.8))
        )
        return [
            QColor.fromRgbF(
                *(
                    float(a or 0.0) * (1 - amount) + float(b or 0.0) * amount
                    for a, b in zip(old.getRgbF(), new.getRgbF())
                )
            )
            for old, new in zip(self._from_colors, self._colors)
        ]

    def set_palette(self, colors: list[str]):
        if not self._artwork_colors or len(colors) < 3:
            return
        self._from_colors = self._blended_colors()
        self._colors = [QColor(color) for color in colors[:3]]
        self._palette_started = time.monotonic()
        self._tick()

    def _get_animated(self):
        return self._animated

    def _set_animated(self, value: bool):
        self._animated = value
        if value and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    animated: bool = pyqtProperty(bool, _get_animated, _set_animated)

    def _get_firstColor(self):
        return self._colors[0]

    def _set_firstColor(self, value: QColor):
        self._colors[0] = QColor(value)

    firstColor: QColor = pyqtProperty(QColor, _get_firstColor, _set_firstColor)

    def _get_secondColor(self):
        return self._colors[1]

    def _set_secondColor(self, value: QColor):
        self._colors[1] = QColor(value)

    secondColor: QColor = pyqtProperty(QColor, _get_secondColor, _set_secondColor)

    def _get_thirdColor(self):
        return self._colors[2]

    def _set_thirdColor(self, value: QColor):
        self._colors[2] = QColor(value)

    thirdColor: QColor = pyqtProperty(QColor, _get_thirdColor, _set_thirdColor)

    def _tick(self):
        inset = max(4, round(5 * self.scale))
        self.update(QRegion(self.rect()) - QRegion(self.rect().adjusted(inset, inset, -inset, -inset)))

    def showEvent(self, a0: QShowEvent | None):
        if a0 is None:
            return None
        super().showEvent(a0)
        self._started = time.monotonic()
        if self._animated:
            self._timer.start()

    def hideEvent(self, a0: QHideEvent | None):
        if a0 is None:
            return None
        self._timer.stop()
        super().hideEvent(a0)

    def paintEvent(self, a0: QPaintEvent | None):
        if a0 is None:
            return None
        if not self._animated:
            super().paintEvent(a0)
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
        path = lower_left_clockwise_path(rect, self.radius - width / 2)
        pen = QPen(QBrush(gradient), width)
        charge = QEasingCurve(QEasingCurve.Type.OutCubic).valueForProgress(min(1.0, elapsed / self.charge_duration))
        if charge < 1:
            perimeter = path.length() / width
            pen.setDashPattern([perimeter, perimeter])
            pen.setDashOffset(perimeter * (1 - charge))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
