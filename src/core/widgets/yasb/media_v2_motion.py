"""Presentation-only motion primitives; no media service or polling timers."""

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSequentialAnimationGroup,
    Qt,
    pyqtProperty,
)
from PyQt6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPalette
from PyQt6.QtWidgets import QGraphicsEffect, QLabel, QSizePolicy, QStyle, QStyleOption


def animate(owner, name, target, duration=250, easing=QEasingCurve.Type.OutCubic):
    """Retarget an owned animation from its current presentation value."""
    if not hasattr(owner, "_motion"):
        owner._motion = {}
    animation = owner._motion.get(name)
    if animation is None:
        animation = QPropertyAnimation(owner, name.encode(), owner)
        owner._motion[name] = animation
    animation.stop()
    animation.setDuration(duration)
    animation.setEasingCurve(easing)
    animation.setStartValue(owner.property(name))
    animation.setEndValue(target)
    animation.start()
    return animation


def settle(owner):
    for name, animation in getattr(owner, "_motion", {}).items():
        animation.stop()
        if animation.endValue() is not None:
            owner.setProperty(name, animation.endValue())


class RevealEffect(QGraphicsEffect):
    """Paint-only staggered intro: leaves layout and hit targets intact.

    Disabled when idle so Qt does not retain an offscreen render pass. The
    output bounds intentionally include motion overflow so OutBack/translated
    content does not get chopped at each child QWidget boundary.
    """

    def __init__(self, widget, delay=0, duration=760, offset=(0, 0), scale=1.0, back=False):
        super().__init__(widget)
        self._progress = 1.0
        self._offset = QPointF(*offset)
        self._scale = scale
        self.widget = widget
        widget.setGraphicsEffect(self)
        self.sequence = QSequentialAnimationGroup(self)
        self.sequence.addPause(delay)
        motion = QPropertyAnimation(self, b"progress", self.sequence)
        motion.setStartValue(0.0)
        motion.setEndValue(1.0)
        motion.setDuration(duration)
        curve = QEasingCurve(QEasingCurve.Type.OutBack if back else QEasingCurve.Type.OutQuart)
        if back:
            curve.setOvershoot(0.8)
        motion.setEasingCurve(curve)
        self.sequence.addAnimation(motion)
        self.sequence.finished.connect(self.finish)
        self.setEnabled(False)

    @pyqtProperty(float)
    def progress(self):
        return self._progress

    @progress.setter
    def progress(self, value):
        self._progress = value
        self.update()

    def replay(self):
        self.sequence.stop()
        self.progress = 0.0
        self.setEnabled(True)
        self.sequence.start()

    def finish(self):
        self.sequence.stop()
        self.progress = 1.0
        self.setEnabled(False)

    def boundingRectFor(self, rect):
        pad = max(16.0, abs(self._offset.x()) + 12.0, abs(self._offset.y()) + 12.0)
        return rect.adjusted(-pad, -pad, pad, pad)

    def draw(self, painter):
        pixmap, offset = self.sourcePixmap(Qt.CoordinateSystem.LogicalCoordinates)
        bounds = QRectF(self.widget.rect())
        painter.save()
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
        name,
        parent=None,
        *,
        elide=False,
        classes=None,
        scrollable=None,
        scroll_speed=40.0,
        scroll_delay=3000,
    ):
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
        self._scroll = QSequentialAnimationGroup(self)
        self._pause = self._scroll.addPause(self._scroll_delay)
        self._travel = QPropertyAnimation(self, b"scrollOffset", self._scroll)
        self._travel.setEasingCurve(QEasingCurve.Type.Linear)
        self._scroll.addAnimation(self._travel)
        self._scroll.setLoopCount(-1)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    @pyqtProperty(float)
    def scrollOffset(self):
        return self._offset

    @scrollOffset.setter
    def scrollOffset(self, value):
        self._offset = value
        self.update()

    @pyqtProperty(float)
    def textMix(self):
        return self._mix

    @textMix.setter
    def textMix(self, value):
        self._mix = value
        self.update()

    def setText(self, text):
        if text == self.text():
            return
        self._previous = self.text()
        self._previous_offset = self._offset
        super().setText(text)
        self.reset_scroll()
        if self._scrollable and self.isVisible():
            self.textMix = 0.0
            animate(self, "textMix", 1.0, 300)
        else:
            self.textMix = 1.0

    def reset_scroll(self, empty=None):
        if empty is not None:
            self._empty = empty
        self._scroll.stop()
        self.scrollOffset = 0.0
        width = self.fontMetrics().horizontalAdvance(self.text())
        self._distance = width + self.fontMetrics().height() * 2.5
        if not self._scrollable or not self.isVisible() or width <= self.contentsRect().width():
            return
        self._pause.setDuration(self._scroll_delay)
        self._travel.setStartValue(0.0)
        self._travel.setEndValue(self._distance)
        self._travel.setDuration(max(1, round(self._distance / self._scroll_speed * 1000)))
        self._scroll.start()

    def showEvent(self, event):
        super().showEvent(event)
        self.reset_scroll()

    def hideEvent(self, event):
        self._scroll.stop()
        self.scrollOffset = 0.0
        settle(self)
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reset_scroll()

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, "_scroll") and event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self.reset_scroll()

    def display_text(self, width=None):
        """Return the current paint-time text without replacing the full value."""
        text = self.text()
        if not self._scrollable and self.elide:
            available = self.contentsRect().width() if width is None else width
            return self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(0, round(available)))
        return text

    def _draw_text(self, painter, text, offset, opacity, shift, bounds):
        if not text or opacity <= 0:
            return
        painter.save()
        painter.setOpacity(opacity)
        painter.translate(-offset, shift)
        width = self.fontMetrics().horizontalAdvance(text)
        if not self._scrollable and self.elide and text == self.text():
            text = self.display_text(bounds.width())
        elif not self._scrollable and self.elide:
            text = self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, round(bounds.width()))
        text_rect = QRectF(0, 0, max(width + 2, bounds.width()), bounds.height())
        alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter if self._scrollable else self.alignment()
        painter.drawText(text_rect, alignment, text)
        if self._scrollable and width > bounds.width():
            text_rect.translate(width + self.fontMetrics().height() * 2.5, 0)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()

    def paintEvent(self, event):
        painter = QPainter(self)
        option = QStyleOption()
        option.initFrom(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option, painter, self)
        bounds = self.contentsRect()
        if bounds.isEmpty():
            return
        # Static labels need neither an intermediate image nor an alpha-mask pass.
        if self._mix >= 1 and (
            not self._scrollable or self.fontMetrics().horizontalAdvance(self.text()) <= bounds.width()
        ):
            painter.setFont(self.font())
            group = QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled
            painter.setPen(self.palette().color(group, QPalette.ColorRole.WindowText))
            painter.setClipRect(bounds)
            painter.translate(bounds.topLeft())
            self._draw_text(painter, self.text(), 0, 1, 0, QRectF(0, 0, bounds.width(), bounds.height()))
            return
        # Only overflowing/fading text needs a small composited layer.
        dpr = self.devicePixelRatioF()
        layer = QImage(
            round(bounds.width() * dpr), round(bounds.height() * dpr), QImage.Format.Format_ARGB32_Premultiplied
        )
        layer.setDevicePixelRatio(dpr)
        layer.fill(Qt.GlobalColor.transparent)
        ink = QPainter(layer)
        ink.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        ink.setFont(self.font())
        group = QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled
        ink.setPen(self.palette().color(group, QPalette.ColorRole.WindowText))
        local = QRectF(0, 0, bounds.width(), bounds.height())
        self._draw_text(ink, self._previous, self._previous_offset, 1 - self._mix, -4 * self._mix, local)
        self._draw_text(ink, self.text(), self._offset, self._mix, 4 * (1 - self._mix), local)
        overflow = self.fontMetrics().horizontalAdvance(self.text()) > bounds.width()
        old_overflow = self._mix < 1 and self.fontMetrics().horizontalAdvance(self._previous) > bounds.width()
        if self._scrollable and (overflow or old_overflow):
            edge = min(12.0, bounds.width() / 4)
            gradient = QLinearGradient(0, 0, bounds.width(), 0)
            gradient.setColorAt(0, QColor(0, 0, 0, 0))
            gradient.setColorAt(edge / bounds.width(), QColor(0, 0, 0, 255))
            gradient.setColorAt(1 - edge / bounds.width(), QColor(0, 0, 0, 255))
            gradient.setColorAt(1, QColor(0, 0, 0, 0))
            ink.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            ink.fillRect(local, gradient)
        ink.end()
        painter.drawImage(bounds.topLeft(), layer)
