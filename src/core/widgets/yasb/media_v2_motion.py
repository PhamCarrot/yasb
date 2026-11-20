"""Presentation-only motion primitives; no media service or polling timers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import PyQt6.QtCore as QtCore
from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPauseAnimation,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSequentialAnimationGroup,
    QSize,
    Qt,
)
from PyQt6.QtGui import (
    QColor,
    QFontMetrics,
    QHideEvent,
    QImage,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPalette,
    QResizeEvent,
    QShowEvent,
    QTextLayout,
    QTextLine,
    QTextOption,
)
from PyQt6.QtWidgets import QGraphicsEffect, QLabel, QSizePolicy, QStyle, QStyleOption, QWidget

pyqtProperty: Callable[..., Any] = getattr(QtCore, "pyqtProperty")


def animate(
    owner: QObject,
    name: str,
    target: Any,
    duration: int = 250,
    easing: QEasingCurve | QEasingCurve.Type = QEasingCurve.Type.OutCubic,
) -> QPropertyAnimation:
    """Retarget an owned animation from its current presentation value."""
    motions = cast(dict[str, QPropertyAnimation], getattr(owner, "_motion", {}))
    setattr(owner, "_motion", motions)
    animation = motions.get(name)
    if animation is None:
        animation = QPropertyAnimation(owner, name.encode(), owner)
        motions[name] = animation
    animation.stop()
    animation.setDuration(duration)
    animation.setEasingCurve(easing)
    animation.setStartValue(owner.property(name))
    animation.setEndValue(target)
    animation.start()
    return animation


def settle(owner: QObject) -> None:
    motions = cast(dict[str, QPropertyAnimation], getattr(owner, "_motion", {}))
    for name, animation in motions.items():
        animation.stop()
        if animation.endValue() is not None:
            owner.setProperty(name, animation.endValue())


class RevealEffect(QGraphicsEffect):
    """Paint-only staggered intro: leaves layout and hit targets intact.

    Disabled when idle so Qt does not retain an offscreen render pass. The
    output bounds intentionally include motion overflow so OutBack/translated
    content does not get chopped at each child QWidget boundary.
    """

    def __init__(
        self,
        widget: QWidget,
        delay: int = 0,
        duration: int = 760,
        offset: tuple[float, float] = (0, 0),
        scale: float = 1.0,
        back: bool = False,
        easing: QEasingCurve.Type | None = None,
        opacity: bool = True,
    ) -> None:
        super().__init__(widget)
        self._progress = 1.0
        self._offset = QPointF(*offset)
        self._scale = scale
        self.widget = widget
        self._opacity = opacity
        self._delay, self._duration = delay, duration
        self._exiting = False
        widget.setGraphicsEffect(self)
        self.sequence = QSequentialAnimationGroup(self)
        self.pause = cast(QPauseAnimation, self.sequence.addPause(delay))
        motion = self.motion = QPropertyAnimation(self, b"progress", self.sequence)
        motion.setStartValue(0.0)
        motion.setEndValue(1.0)
        motion.setDuration(duration)
        curve = QEasingCurve(easing or (QEasingCurve.Type.OutBack if back else QEasingCurve.Type.OutQuart))
        if back:
            curve.setOvershoot(0.8)
        self._curve = curve
        motion.setEasingCurve(curve)
        self.sequence.addAnimation(motion)
        self.sequence.finished.connect(self._completed)
        self.setEnabled(False)
        widget.installEventFilter(self)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a1 is not None and a1.type() == QEvent.Type.Hide and self.isEnabled():
            self.finish()
        return super().eventFilter(a0, a1)

    def _get_progress(self):
        return self._progress

    def _set_progress(self, value: float):
        self._progress = value
        self.update()

    progress: float = pyqtProperty(float, _get_progress, _set_progress)

    def _run(self, start: float, end: float, delay: int, duration: int, curve: QEasingCurve) -> None:
        self.sequence.stop()
        self.pause.setDuration(delay)
        self.motion.setStartValue(start)
        self.motion.setEndValue(end)
        self.motion.setDuration(max(1, duration))
        self.motion.setEasingCurve(curve)
        self.progress = start
        self.setEnabled(True)
        self.sequence.start()

    def replay(self) -> None:
        self._exiting = False
        self._run(0.0, 1.0, self._delay, self._duration, self._curve)

    def resume(self) -> None:
        self._exiting = False
        self._run(self.progress, 1.0, 0, round(self._duration * abs(1 - self.progress)), self._curve)

    def conceal(self, delay: int, duration: int, easing: QEasingCurve.Type) -> None:
        self._exiting = True
        self._run(self.progress, 0.0, delay, duration, QEasingCurve(easing))

    def _completed(self) -> None:
        if self._exiting:
            self.progress = 0.0
        else:
            self.finish()

    def finish(self):
        self.sequence.stop()
        self.progress = 1.0
        self.setEnabled(False)

    def boundingRectFor(self, sourceRect: QRectF):
        pad = max(16.0, abs(self._offset.x()) + 12.0, abs(self._offset.y()) + 12.0)
        return sourceRect.adjusted(-pad, -pad, pad, pad)

    def draw(self, painter: QPainter | None):
        if painter is None:
            return
        pixmap, offset = self.sourcePixmap(Qt.CoordinateSystem.LogicalCoordinates)
        if offset is None:
            return
        bounds = QRectF(self.widget.rect())
        painter.save()
        if self._opacity:
            painter.setOpacity(max(0.0, min(1.0, self._progress)))
        center = bounds.center()
        painter.translate(center + self._offset * (1 - self._progress))
        factor = self._scale + (1 - self._scale) * self._progress
        painter.scale(factor, factor)
        painter.translate(-center)
        painter.drawPixmap(offset, pixmap)
        painter.restore()


class MediaText(QLabel):
    """Plain-text, fractional-pixel marquee and track crossfade in a text-only layer."""

    def __init__(
        self,
        name: str,
        parent: QWidget | None = None,
        *,
        elide: bool = False,
        classes: str | None = None,
        scrollable: bool | None = None,
        scroll_speed: float = 40.0,
        scroll_delay: int = 3000,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(name)
        self.setProperty("class", classes or name)
        self.elide = elide
        self._scrollable = name in ("media-title", "media-artist") if scrollable is None else bool(scrollable)
        self._scroll_speed = float(scroll_speed)
        self._scroll_delay = int(scroll_delay)
        self._offset = 0.0
        self._mix = 1.0
        self._previous = ""
        self._previous_offset = 0.0
        self._empty = False
        self._distance = 0.0
        self._ink_layer = QImage()
        self._fade_gradient: QLinearGradient | None = None
        self._marquee_layout: QTextLayout | None = None
        self._measurement: tuple[str, QFontMetrics, int] | None = None
        self._scroll = QSequentialAnimationGroup(self)
        self._pause: QPauseAnimation = cast(QPauseAnimation, self._scroll.addPause(self._scroll_delay))
        assert self._pause is not None
        self._travel = QPropertyAnimation(self, b"scrollOffset", self._scroll)
        self._travel.setEasingCurve(QEasingCurve.Type.Linear)
        self._scroll.addAnimation(self._travel)
        self._scroll.setLoopCount(-1)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def _get_scrollOffset(self):
        return self._offset

    def _set_scrollOffset(self, value: float):
        self._offset = value
        self.update()

    scrollOffset: float = pyqtProperty(float, _get_scrollOffset, _set_scrollOffset)

    def _get_textMix(self):
        return self._mix

    def _set_textMix(self, value: float):
        self._mix = value
        self.update()

    textMix: float = pyqtProperty(float, _get_textMix, _set_textMix)

    def setText(self, a0: str | None):
        if a0 == self.text():
            return
        self._previous = self.text()
        self._previous_offset = self._offset
        super().setText(a0)
        self.reset_scroll()
        if self._scrollable and self.isVisible():
            self.textMix = 0.0
            animate(self, "textMix", 1.0, 300)
        else:
            self.textMix = 1.0

    def reset_scroll(self, empty: bool | None = None):
        if empty is not None:
            self._empty = empty
        self._scroll.stop()
        self.scrollOffset = 0.0
        metrics = self.fontMetrics()
        width = self._text_width(self.text(), metrics)
        self._distance = width + metrics.height() * 2.5
        if not self._scrollable or not self.isVisible() or width <= self.contentsRect().width():
            return
        self._pause.setDuration(self._scroll_delay)
        self._travel.setStartValue(0.0)
        self._travel.setEndValue(self._distance)
        self._travel.setDuration(max(1, round(self._distance / self._scroll_speed * 1000)))
        self._scroll.start()

    def showEvent(self, a0: QShowEvent | None):
        if a0 is None:
            return None
        super().showEvent(a0)
        self.reset_scroll()

    def hideEvent(self, a0: QHideEvent | None):
        if a0 is None:
            return None
        self._scroll.stop()
        self.scrollOffset = 0.0
        settle(self)
        self._marquee_layout = None
        self._ink_layer = QImage()
        super().hideEvent(a0)

    def resizeEvent(self, a0: QResizeEvent | None):
        if a0 is None:
            return None
        super().resizeEvent(a0)
        self.reset_scroll()

    def changeEvent(self, a0: QEvent | None):
        if a0 is None:
            return None
        super().changeEvent(a0)
        if hasattr(self, "_scroll") and a0.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._marquee_layout = None
            self._ink_layer = QImage()
            self._measurement = None
            self.reset_scroll()

    def display_text(self, width: float | None = None):
        """Return the current paint-time text without replacing the full value."""
        text = self.text()
        if not self._scrollable and self.elide:
            available = self.contentsRect().width() if width is None else width
            return self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(0, round(available)))
        return text

    def _text_width(self, text: str, metrics: QFontMetrics) -> int:
        measured = self._measurement
        if measured is None or text != measured[0] or metrics != measured[1]:
            measured = text, metrics, metrics.horizontalAdvance(text)
            self._measurement = measured
        return measured[2]

    def _marquee_line(self, painter: QPainter, text: str) -> QTextLine | None:
        # Keep Qt's rectangle layout for formatting-sensitive text.
        font = painter.font()
        direction = painter.layoutDirection()
        if (
            len(text) > 512
            or not text.isascii()
            or not text.isprintable()
            or text != text.strip()
            or direction == Qt.LayoutDirection.RightToLeft
            or font.underline()
            or font.strikeOut()
            or font.overline()
        ):
            return None
        layout = self._marquee_layout
        if (
            layout is None
            or layout.text() != text
            or layout.font() != font
            or layout.textOption().textDirection() != direction
        ):
            layout = QTextLayout(text, font, self._ink_layer)
            layout.setCacheEnabled(True)
            options = QTextOption(Qt.AlignmentFlag.AlignLeft)
            options.setTextDirection(direction)
            layout.setTextOption(options)
            layout.beginLayout()
            line = layout.createLine()
            # Match the rectangle painter's unwrapped single-line layout.
            line.setLineWidth(0x01000000)
            line.setPosition(QPointF())
            layout.endLayout()
            self._marquee_layout = layout
        return layout.lineAt(0)

    def _draw_text(
        self,
        painter: QPainter,
        text: str,
        metrics: QFontMetrics,
        width: int,
        offset: float,
        opacity: float,
        shift: float,
        bounds: QRectF,
    ):
        if not text or opacity <= 0:
            return
        painter.save()
        painter.setOpacity(opacity)
        painter.translate(-offset, shift)
        text_rect = QRectF(0, 0, max(width + 2, bounds.width()), bounds.height())
        if not self._scrollable and self.elide:
            text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, round(bounds.width()))
            text_rect = QRectF(bounds)
        alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter if self._scrollable else self.alignment()
        scrolling = self._scrollable and width > bounds.width()
        if scrolling and self._mix >= 1:
            line = self._marquee_line(painter, text)
            if line is not None:
                line_height = line.ascent() + line.descent()
                if line_height <= bounds.height() and line.naturalTextWidth() <= text_rect.width():
                    y = (bounds.height() - line_height) / 2
                    repeat = width + metrics.height() * 2.5
                    line.draw(painter, QPointF(0, y))
                    line.draw(painter, QPointF(repeat, y))
                    painter.restore()
                    return
        painter.drawText(text_rect, alignment, text)
        if scrolling:
            text_rect.translate(width + metrics.height() * 2.5, 0)
            painter.drawText(text_rect, alignment, text)
        painter.restore()

    def paintEvent(self, a0: QPaintEvent | None):
        if a0 is None:
            return None
        painter = QPainter(self)
        option = QStyleOption()
        option.initFrom(self)
        cast(QStyle, self.style()).drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option, painter, self)
        bounds = self.contentsRect()
        if bounds.isEmpty():
            return
        metrics = self.fontMetrics()
        text = self.text()
        width = self._text_width(text, metrics)
        overflow = width > bounds.width()
        # Static labels need neither an intermediate image nor an alpha-mask pass.
        if self._mix >= 1 and (not self._scrollable or not overflow):
            painter.setFont(self.font())
            group = QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled
            painter.setPen(self.palette().color(group, QPalette.ColorRole.WindowText))
            painter.setClipRect(bounds)
            painter.translate(bounds.topLeft())
            self._draw_text(painter, text, metrics, width, 0, 1, 0, QRectF(0, 0, bounds.width(), bounds.height()))
            return
        # Only overflowing/fading text needs a small composited layer.
        dpr = self.devicePixelRatioF()
        size = QSize(round(bounds.width() * dpr), round(bounds.height() * dpr))
        if self._ink_layer.size() != size or self._ink_layer.devicePixelRatio() != dpr:
            self._marquee_layout = None
            self._ink_layer = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
            self._ink_layer.setDevicePixelRatio(dpr)
        layer = self._ink_layer
        layer.fill(Qt.GlobalColor.transparent)
        ink = QPainter(layer)
        ink.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        ink.setFont(self.font())
        group = QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled
        ink.setPen(self.palette().color(group, QPalette.ColorRole.WindowText))
        local = QRectF(0, 0, bounds.width(), bounds.height())
        old_width = metrics.horizontalAdvance(self._previous) if self._mix < 1 else 0
        self._draw_text(
            ink, self._previous, metrics, old_width, self._previous_offset, 1 - self._mix, -4 * self._mix, local
        )
        self._draw_text(ink, text, metrics, width, self._offset, self._mix, 4 * (1 - self._mix), local)
        old_overflow = old_width > bounds.width()
        if self._scrollable and (overflow or old_overflow):
            if self._fade_gradient is None or self._fade_gradient.finalStop().x() != bounds.width():
                edge = min(12.0, bounds.width() / 4)
                gradient = QLinearGradient(0, 0, bounds.width(), 0)
                gradient.setColorAt(0, QColor(0, 0, 0, 0))
                gradient.setColorAt(edge / bounds.width(), QColor(0, 0, 0, 255))
                gradient.setColorAt(1 - edge / bounds.width(), QColor(0, 0, 0, 255))
                gradient.setColorAt(1, QColor(0, 0, 0, 0))
                self._fade_gradient = gradient
            ink.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            ink.fillRect(local, self._fade_gradient)
        ink.end()
        painter.drawImage(bounds.topLeft(), layer)
