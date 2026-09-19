"""Presentation-only Qt components used by Media Widget V2."""

import math
import time

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QGuiApplication, QKeyEvent, QMouseEvent, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyleOption,
)

from core.utils.tooltip import set_tooltip
from core.utils.utilities import refresh_widget_style
from core.widgets.services.media.model import MAX_TIMELINE_DURATION
from core.widgets.yasb.media_v2_motion import MediaText, animate, settle

__all__ = [
    "AlbumArt",
    "InfoButton",
    "MediaButton",
    "MediaComboBox",
    "MediaText",
    "SeekSlider",
    "TransportControls",
    "format_time",
    "identify",
    "media_title",
    "track_identity",
]


def identify(widget, name, *classes):
    """Assign a stable compatibility ID plus optional reusable semantic classes."""
    widget.setObjectName(name)
    if classes:
        widget.setProperty("class", " ".join(dict.fromkeys(value for value in classes if value)))
    return widget


def format_time(seconds):
    if seconds is None or not math.isfinite(seconds) or seconds > MAX_TIMELINE_DURATION:
        return "--:--"
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    return f"{minutes:02d}:{seconds:02d}"


def track_identity(active):
    if active is None:
        return None
    meta = active.metadata
    return (active.session_id, meta.title.strip(), meta.track_number or None)


def media_title(active):
    if active is None:
        return "Nothing playing"
    if active.title:
        return active.title
    if active.is_playing:
        return "Media playing"
    return "Unknown title" if active.metadata_ready else "Loading media…"


class MediaButton(QPushButton):
    """YASB-style semantic button; Qt owns normal interaction pseudo-states."""

    def __init__(self, parent=None, *classes):
        super().__init__(parent)
        self.setFlat(True)
        self.setAutoDefault(False)
        self.setDefault(False)
        # Keep keyboard tab navigation without giving every mouse click a
        # persistent native/focus box. Programmatic popup focus still works.
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.set_base_classes(*classes)

    def set_base_classes(self, *classes):
        value = " ".join(dict.fromkeys(("btn", *(item for item in classes if item))))
        if self.property("class") != value:
            self.setProperty("class", value)
            refresh_widget_style(self)


class MediaComboBox(QComboBox):
    """Hidden selector model backed by a reliably anchored player menu."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._mode = "automatic"
        self._anchor = None
        self._menu_active = False
        self._sync_class()
        self.view().setProperty("class", "menu media-player-menu")
        self.view().setFrameShape(QFrame.Shape.NoFrame)
        self.popup_menu = QMenu(self)
        self.popup_menu.setObjectName("media-player-menu")
        self.popup_menu.setProperty("class", "menu media-player-menu")
        self.popup_menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.popup_menu.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.popup_menu.aboutToShow.connect(self._menu_shown)
        self.popup_menu.aboutToHide.connect(self._menu_hidden)

    @property
    def menu_active(self):
        return self._menu_active

    def set_mode(self, mode):
        mode = "pinned" if mode == "pinned" else "automatic"
        if mode != self._mode:
            self._mode = mode
            self._sync_class()

    def _sync_class(self):
        value = f"combobox media-player-selector {self._mode}"
        if self.property("class") != value:
            self.setProperty("class", value)
            refresh_widget_style(self)

    def showPopup(self):
        if not self.count():
            return
        self._rebuild_menu()
        refresh_widget_style(self.popup_menu)
        self._menu_active = True
        self.popup_menu.popup(self._popup_position())
        if self.popup_menu.isVisible():
            QTimer.singleShot(0, self._apply_rounded_corners)
        else:
            self._menu_active = False

    def hidePopup(self):
        self.popup_menu.close()

    def open_at(self, anchor):
        """Open the menu at a visible sibling while retaining combo selection state."""
        self._anchor = anchor
        self.showPopup()

    def sync_popup(self):
        """Keep an already-open menu consistent with a changed session model."""
        if self.popup_menu.isVisible():
            self._rebuild_menu()

    def _rebuild_menu(self):
        self.popup_menu.clear()
        current = self.currentIndex()
        for index in range(self.count()):
            action = self.popup_menu.addAction(self.itemText(index))
            action.setCheckable(True)
            action.setChecked(index == current)
            action.setEnabled(bool(self.model().flags(self.model().index(index, 0)) & Qt.ItemFlag.ItemIsEnabled))
            action.triggered.connect(lambda checked=False, item=index: self._activate(item))

    def _activate(self, index):
        if not 0 <= index < self.count():
            return
        self.setCurrentIndex(index)
        self.activated.emit(index)

    def _menu_shown(self):
        self._menu_active = True

    def _menu_hidden(self):
        self._menu_active = False

    def _popup_position(self):
        self.popup_menu.ensurePolished()
        size = self.popup_menu.sizeHint()
        anchor = self._anchor
        if anchor is not None and anchor.isVisible():
            origin = anchor.mapToGlobal(QPoint(0, anchor.height()))
            screen = anchor.screen()
            available = screen.availableGeometry() if screen is not None else None
            x = origin.x()
            y = origin.y()
            if available is not None:
                x = max(available.left(), min(x, available.right() - size.width() + 1))
                if y + size.height() > available.bottom() + 1:
                    y = anchor.mapToGlobal(QPoint(0, 0)).y() - size.height()
                y = max(available.top(), y)
            return QPoint(x, y)
        return self.mapToGlobal(QPoint(0, self.height()))

    def _apply_rounded_corners(self):
        if not self.popup_menu.isVisible():
            return
        try:
            import sys

            if QGuiApplication.platformName() != "offscreen" and sys.getwindowsversion().build >= 22000:
                from core.utils.win32.backdrop import set_window_corner_preference
                from core.utils.win32.constants import DWMWCP_ROUND

                set_window_corner_preference(int(self.popup_menu.winId()), DWMWCP_ROUND, "None")
        except Exception:
            pass


class InfoButton(MediaButton):
    """Accessible click target around the bar artwork/title/time column."""

    def __init__(self, parent=None):
        super().__init__(parent, "media-info")
        self.setObjectName("media-info")
        self._highlight = 0.0
        self._highlight_enabled = False
        self._activation_mode = "keyboard"
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("Open media player")
        set_tooltip(self, "Open media player")
        self.pressed.connect(lambda: animate(self, "highlight", 0.12, 180))
        self.released.connect(lambda: animate(self, "highlight", 0.06 if self.underMouse() else 0.0, 250))

    def take_activation_mode(self):
        mode = self._activation_mode
        self._activation_mode = "keyboard"
        return mode

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._activation_mode = "mouse"
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._activation_mode = "keyboard"
        super().keyPressEvent(event)

    @pyqtProperty(bool)
    def highlightEnabled(self):
        return self._highlight_enabled

    @highlightEnabled.setter
    def highlightEnabled(self, value):
        self._highlight_enabled = value
        self.update()

    @pyqtProperty(float)
    def highlight(self):
        return self._highlight

    @highlight.setter
    def highlight(self, value):
        self._highlight = value
        if self._highlight_enabled:
            self.update()

    def enterEvent(self, event):
        animate(self, "highlight", 0.06, 250, QEasingCurve.Type.OutExpo)
        super().enterEvent(event)

    def leaveEvent(self, event):
        animate(self, "highlight", 0.0, 250, QEasingCurve.Type.OutExpo)
        super().leaveEvent(event)

    def hideEvent(self, event):
        settle(self)
        self.highlight = 0.0
        super().hideEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._highlight_enabled:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self.palette().color(QPalette.ColorRole.WindowText)
        color.setAlphaF(self._highlight)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(self.rect()), 8, 8)


class AlbumArt(QFrame):
    """Rounded/circular artwork with cached-pixmap replacement and playback motion."""

    def __init__(self, parent=None, *, vinyl=False, radius=10):
        super().__init__(parent)
        identify(self, "media-art", "media-art", "artwork")
        self.vinyl = vinyl
        self.radius = radius
        self.shape = "rounded"
        self._angle = 0.0
        self._rhythm_scale = 1.0
        self._pixmap = QPixmap()
        self._old_pixmap = QPixmap()
        self._playing = False
        self._mix = 1.0
        self._disc_scale = 0.9
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#cba6f7"))
        palette.setColor(QPalette.ColorRole.Window, QColor("#45475a"))
        self.setPalette(palette)
        # AlbumArt paints its own shape. Prevent QSS background brushes from
        # filling the rectangular QWidget behind circular/rounded artwork;
        # the palette color still supplies the painted fallback disc.
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAccessibleName("Album artwork")

    @pyqtProperty(QColor)
    def fallbackColor(self):
        return self.palette().color(QPalette.ColorRole.Window)

    @fallbackColor.setter
    def fallbackColor(self, value):
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(value))
        self.setPalette(palette)
        self.update()

    @pyqtProperty(QColor)
    def accentColor(self):
        return self.palette().color(QPalette.ColorRole.WindowText)

    @accentColor.setter
    def accentColor(self, color):
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor(color))
        self.setPalette(palette)
        self.update()

    @pyqtProperty(float)
    def artMix(self):
        return self._mix

    @artMix.setter
    def artMix(self, value):
        self._mix = value
        if value >= 1:
            self._old_pixmap = QPixmap()
        self.update()

    @pyqtProperty(float)
    def discScale(self):
        return self._disc_scale

    @discScale.setter
    def discScale(self, value):
        self._disc_scale = value
        self.update()

    def set_artwork(self, pixmap, playing=False, *, clear_previous=False):
        if clear_previous:
            animation = getattr(self, "_motion", {}).get("artMix")
            if animation is not None:
                animation.stop()
            self._old_pixmap = QPixmap()
            self._pixmap = pixmap
            self.artMix = 1.0
        if self._pixmap.cacheKey() == pixmap.cacheKey() and self._playing == playing:
            return
        if self._pixmap.cacheKey() != pixmap.cacheKey():
            if self._mix >= 0.5:
                self._old_pixmap = self._pixmap
            self._pixmap = pixmap
            if self.isVisible():
                self.artMix = 0.0
                animate(self, "artMix", 1.0, 650 if self.vinyl else 600, QEasingCurve.Type.InOutQuad)
            else:
                settle(self)
                self.artMix = 1.0
        if self._playing != playing:
            self._playing = playing
            target = 1.0 if playing else 0.9
            if self.isVisible():
                animate(self, "discScale", target, 600)
            else:
                self.discScale = target
        self.update()

    def hideEvent(self, event):
        settle(self)
        super().hideEvent(event)

    def _draw_cover(self, painter, bounds, path, pixmap, opacity):
        painter.save()
        painter.setOpacity(opacity)
        painter.fillPath(path, self.fallbackColor)
        if not pixmap.isNull():
            width, height = pixmap.width(), pixmap.height()
            side = min(width, height)
            painter.save()
            if self.vinyl:
                painter.translate(bounds.center())
                painter.rotate(self._angle)
                painter.translate(-bounds.center())
            painter.drawPixmap(bounds, pixmap, QRectF((width - side) / 2, (height - side) / 2, side, side))
            painter.restore()
            overlay = QColor("#313244")
            overlay.setAlphaF(0.08 if self.vinyl else 0.15)
            painter.fillPath(path, overlay)
        else:
            painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
            font = painter.font()
            font.setPixelSize(max(12, round(bounds.width() * (0.26 if self.vinyl else 0.5))))
            painter.setFont(font)
            painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, "♫")
        painter.restore()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        content = QRectF(self.contentsRect())
        bounds = content.adjusted(0.5, 0.5, -0.5, -0.5)
        if self.vinyl:
            size = min(bounds.width(), bounds.height()) * 0.86 * self._disc_scale * self._rhythm_scale
            offset_y = float(getattr(self, "_rhythm_offset_y", 0.0))
            bounds = QRectF(0, 0, size, size)
            bounds.moveCenter(content.center() + QPointF(0, offset_y))
            tilt = float(getattr(self, "_rhythm_tilt", 0.0))
            if tilt:
                painter.translate(bounds.center())
                painter.rotate(tilt)
                painter.translate(-bounds.center())
        path = QPainterPath()
        if self.vinyl or self.shape == "circle":
            path.addEllipse(bounds)
        else:
            radius = 0 if self.shape == "square" else self.radius
            path.addRoundedRect(bounds, radius, radius)
        painter.save()
        painter.setClipPath(path)
        if self._mix < 1:
            self._draw_cover(painter, bounds, path, self._old_pixmap, 1.0)
        self._draw_cover(painter, bounds, path, self._pixmap, self._mix)
        painter.restore()
        if not self.vinyl:
            return
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(self.accentColor if self._playing else QColor("#585b70"), 1))
        painter.drawPath(path)
        for index, ratio in enumerate((0.92, 0.84, 0.76, 0.68, 0.60, 0.52, 0.44)):
            ring = QRectF(0, 0, bounds.width() * ratio, bounds.height() * ratio)
            ring.moveCenter(bounds.center())
            painter.setPen(QPen(QColor(255, 255, 255, 10) if index % 2 == 0 else QColor(0, 0, 0, 16), 1))
            painter.drawEllipse(ring)
        spindle = float(not self._old_pixmap.isNull()) * (1 - self._mix) + float(not self._pixmap.isNull()) * self._mix
        painter.setOpacity(spindle)
        for ratio, color in ((0.28, "#11111b"), (0.28 * 0.68, "#585b70"), (0.28 * 0.68 * 0.38, "#0d0e15")):
            circle = QRectF(0, 0, bounds.width() * ratio, bounds.height() * ratio)
            circle.moveCenter(bounds.center())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawEllipse(circle)


class TransportButton(MediaButton):
    """Native keyboard/mouse semantics, animated vector icons and click feedback."""

    def __init__(self, action, size, icon_size, parent=None):
        super().__init__(parent, "transport", action)
        self.action = action
        self.icon_size = icon_size
        self._visual_scale = 1.0
        self._availability = 1.0
        self._morph = 0.0
        self._flash = 0.0
        self.setObjectName("media-" + action)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(action.title())
        set_tooltip(self, action.title())
        self.pressed.connect(self._pressed)
        self.released.connect(self._released)
        self.clicked.connect(self._clicked)

    def set_shape(self, shape, radius=10):
        self._shape = shape
        self._shape_radius = radius
        self._sync_shape()

    def _shape_path(self):
        path = QPainterPath()
        rect = QRectF(self.rect())
        shape = getattr(self, "_shape", "rounded")
        radius = getattr(self, "_shape_radius", 10)
        if shape == "circle":
            path.addEllipse(rect)
        else:
            path.addRoundedRect(rect, 0 if shape == "square" else radius, 0 if shape == "square" else radius)
        return path

    def _sync_shape(self):
        shape = getattr(self, "_shape", "rounded")
        radius = (
            min(self.width(), self.height()) / 2
            if shape == "circle"
            else (0 if shape == "square" else getattr(self, "_shape_radius", 10))
        )
        metrics = (self.width(), self.height(), shape, radius)
        if metrics == getattr(self, "_shape_metrics", None):
            return
        self._shape_metrics = metrics
        # QSS owns the box model; the painter path handles hit testing and icons.
        self.clearMask()
        self.setProperty("shape", shape)
        self.set_base_classes("transport", self.action, shape)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_shape()

    def hitButton(self, point):
        return self._shape_path().contains(QPointF(point))

    @pyqtProperty(float)
    def visualScale(self):
        return self._visual_scale

    @visualScale.setter
    def visualScale(self, value):
        self._visual_scale = value
        self.update()

    @pyqtProperty(float)
    def availability(self):
        return self._availability

    @availability.setter
    def availability(self, value):
        self._availability = value
        self.update()

    @pyqtProperty(float)
    def morph(self):
        return self._morph

    @morph.setter
    def morph(self, value):
        self._morph = value
        self.update()

    @pyqtProperty(float)
    def flash(self):
        return self._flash

    @flash.setter
    def flash(self, value):
        self._flash = value
        self.update()

    def _pressed(self):
        animate(self, "visualScale", 1.08, 250, QEasingCurve.Type.OutQuint)

    def _released(self):
        animate(self, "visualScale", 1.04 if self.underMouse() else 1.0, 420, QEasingCurve.Type.OutQuint)

    def _clicked(self):
        self.flash = 0.4
        animate(self, "flash", 0.0, 400, QEasingCurve.Type.OutExpo)
        self.visualScale = 1.1
        self._released()

    def enterEvent(self, event):
        if self.isEnabled():
            animate(self, "visualScale", 1.04, 250, QEasingCurve.Type.OutQuint)
        super().enterEvent(event)

    def leaveEvent(self, event):
        animate(self, "visualScale", 1.0, 250, QEasingCurve.Type.OutQuint)
        super().leaveEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange and hasattr(self, "_availability"):
            target = 1.0 if self.isEnabled() else 0.5
            self.setCursor(Qt.CursorShape.PointingHandCursor if self.isEnabled() else Qt.CursorShape.ArrowCursor)
            if self.isVisible():
                animate(self, "availability", target, 180)
            else:
                self.availability = target
            if not self.isEnabled():
                self.setDown(False)
                self._released()

    def hideEvent(self, event):
        settle(self)
        self.visualScale = 1.0
        self.flash = 0.0
        super().hideEvent(event)

    def set_playing(self, playing):
        action = "pause" if playing else "play"
        if action == self.action:
            return
        self.action = action
        self.set_base_classes("transport", action, getattr(self, "_shape", "rounded"))
        self.setAccessibleName(action.title())
        set_tooltip(self, action.title())
        if self.isVisible():
            animate(self, "morph", float(playing), 180)
        else:
            self.morph = float(playing)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._flash:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, round(self._flash * 255)))
            painter.drawPath(self._shape_path())
        painter.setBrush(self.palette().color(QPalette.ColorRole.ButtonText))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(self.icon_size / 24 * self._visual_scale, self.icon_size / 24 * self._visual_scale)
        painter.setOpacity(self._availability)
        if self.action in ("pause", "play"):
            painter.setOpacity(self._availability * (1 - self._morph))
            play = QPainterPath()
            play.moveTo(-6.5, -10.0)
            play.lineTo(10.0, 0.0)
            play.lineTo(-6.5, 10.0)
            play.closeSubpath()
            painter.drawPath(play)
            painter.setOpacity(self._availability * self._morph)
            painter.drawRoundedRect(QRectF(-7.2, -9.2, 5.2, 18.4), 1.1, 1.1)
            painter.drawRoundedRect(QRectF(2.0, -9.2, 5.2, 18.4), 1.1, 1.1)
        else:
            if self.action == "previous":
                painter.scale(-1, 1)
            skip = QPainterPath()
            skip.moveTo(-9.2, -8.5)
            skip.lineTo(3.4, 0.0)
            skip.lineTo(-9.2, 8.5)
            skip.closeSubpath()
            painter.drawPath(skip)
            painter.drawRoundedRect(QRectF(5.0, -8.5, 3.0, 17.0), 0.8, 0.8)


class TransportControls(QFrame):
    def __init__(self, scale, parent=None, *, popup=False, compact=False, control_size=None):
        super().__init__(parent)
        identify(self, "media-controls", "media-controls")
        self._scale = float(scale)
        self._popup = popup
        self._control_size = float(control_size if control_size is not None else (43 if popup else 30))
        s = lambda value: round(value * self._scale)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(s(18 if popup else (3 if compact else 4)))
        self.previous = TransportButton("previous", 1, 1, self)
        self.play = TransportButton("play", 1, 1, self)
        self.next = TransportButton("next", 1, 1, self)
        for button in (self.previous, self.play, self.next):
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
            button.setEnabled(False)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_metrics(scale=self._scale, compact=compact)

    def set_metrics(self, *, scale=None, compact=False):
        """Apply one coherent metric set to geometry, icons, hit targets and spacing."""
        scale = self._scale if scale is None else float(scale)
        compact = max(0.0, min(1.0, float(compact)))
        reference = 43 if self._popup else 30
        factor = self._control_size / reference
        side = 32 * factor if self._popup else (30 - 2 * compact) * factor
        play = 43 * factor if self._popup else side
        spacing = 18 if self._popup else 4 - compact
        play_icon = round((32 if self._popup else 18) * factor * scale)
        side_icon = round((21 if self._popup else 16) * factor * scale)
        icons = (side_icon, play_icon, side_icon)
        sizes = (
            round(side * scale),
            round(play * scale),
            round(side * scale),
        )
        for button, size, icon in zip((self.previous, self.play, self.next), sizes, icons):
            button.setFixedSize(size, size)
            button.icon_size = icon
            button.update()
        self.layout().setSpacing(round(spacing * scale))

    def set_state(self, active):
        caps = active.capabilities if active else None
        self.previous.setEnabled(bool(caps and caps.can_previous))
        self.play.setEnabled(bool(caps and caps.can_play_pause))
        self.next.setEnabled(bool(caps and caps.can_next))
        self.play.set_playing(bool(active and active.is_playing))


class SeekSlider(QSlider):
    interaction_started = pyqtSignal()
    preview_changed = pyqtSignal(float)
    seek_requested = pyqtSignal(float)

    def __init__(self, scale, parent=None, *, smoothing_ms=250, show_handle=True):
        super().__init__(Qt.Orientation.Horizontal, parent)
        identify(self, "media-progress", "media-progress")
        self._scale = float(scale)
        self._smoothing_ms = int(smoothing_ms)
        self._show_handle = bool(show_handle)
        self.setRange(0, 10000)
        self.setSingleStep(100)
        self.setPageStep(1000)
        self.setFixedHeight(round(15 * scale))
        self.handle_size = max(10, round(13 * scale))
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName("Playback position")
        # QSlider's platform style can paint a rectangular primitive behind
        # rounded groove sub-controls. Keep QSlider for input/accessibility,
        # but render the visual track using ordinary semantic child frames.
        self._track = identify(QFrame(self), "media-progress-track", "media-progress-track")
        self._fill = identify(QFrame(self), "media-progress-fill", "media-progress-fill")
        self._handle = identify(QFrame(self), "media-progress-handle", "media-progress-handle")
        for visual in (self._track, self._fill, self._handle):
            visual.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            visual.hide()
        self._dragging = False
        self._target = None
        self._pending = None
        self._deadline = 0.0
        self._last_progress = 0.0
        self._visual_progress = 0.0
        self._seek_timeout = QTimer(self)
        self._seek_timeout.setSingleShot(True)
        self._seek_timeout.setInterval(1000)
        self._seek_timeout.timeout.connect(self._expire_pending)
        self.setTracking(False)
        self.valueChanged.connect(self.update)
        self.rangeChanged.connect(lambda *_: self.update())

    def _visual_rects(self, progress=None):
        handle = self.handle_size
        track_h = max(4, round(6 * self._scale))
        usable = max(1, self.width() - handle)
        left = handle / 2
        top = max(0.0, (self.height() - track_h) / 2)
        if progress is None:
            progress = self.sliderPosition() / self.maximum() if self._dragging else self._visual_progress
        progress = max(0.0, min(1.0, progress))
        fill_w = usable * progress
        center_x = left + fill_w
        return (
            QRectF(left, top, usable, track_h),
            QRectF(left, top, max(0.0, fill_w), track_h),
            QRectF(center_x - handle / 2, (self.height() - handle) / 2, handle, handle),
        )

    @staticmethod
    def _paint_styled_frame(painter, frame, target):
        if target.width() <= 0 or target.height() <= 0:
            return
        size = QSize(max(1, math.ceil(target.width())), max(1, math.ceil(target.height())))
        frame.resize(size)
        frame.ensurePolished()
        option = QStyleOption()
        option.initFrom(frame)
        option.rect = QRect(0, 0, size.width(), size.height())
        painter.save()
        painter.translate(target.topLeft())
        painter.setClipRect(QRectF(0, 0, target.width(), target.height()))
        frame.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option, painter, frame)
        painter.restore()

    def _sync_visuals(self, *_):
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_visuals()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track, fill, handle = self._visual_rects()
        self._paint_styled_frame(painter, self._track, track)
        self._paint_styled_frame(painter, self._fill, fill)
        if self._show_handle:
            self._paint_styled_frame(painter, self._handle, handle)

    @property
    def interacting(self):
        return self._dragging

    @pyqtProperty(float)
    def visualProgress(self):
        return self._visual_progress

    @visualProgress.setter
    def visualProgress(self, value):
        value = max(0.0, min(1.0, float(value)))
        self._visual_progress = value
        self.setValue(round(value * self.maximum()))
        self.update()

    def set_progress(self, progress, reset=False, velocity=0.0):
        target = min(1.0, max(0.0, progress or 0.0))
        self._last_progress = target
        if self._dragging:
            return
        if self._pending is not None:
            if time.monotonic() < self._deadline and abs(target - self._pending) > 0.015:
                return
            self._pending = None
            self._seek_timeout.stop()
        self._target = target
        if self.isVisible() and not reset and self._smoothing_ms > 0:
            # smoothing_ms is a prediction horizon, not a delay. Advancing the
            # target by the authoritative playback rate prevents permanent
            # catch-up lag when backend samples arrive more frequently than the
            # animation duration.
            projected = target + float(velocity) * self._smoothing_ms / 1000
            animate(self, "visualProgress", max(0.0, min(1.0, projected)), self._smoothing_ms, QEasingCurve.Type.Linear)
        else:
            settle(self)
            self.visualProgress = target

    def cancel_interaction(self):
        # Preserve the user's value: settling a stopped position animation would
        # otherwise overwrite the release position with its old backend target.
        for animation in getattr(self, "_motion", {}).values():
            animation.stop()
        self._seek_timeout.stop()
        self._dragging = False
        self._pending = None
        self._target = None
        self.setSliderDown(False)
        self.update()

    def _begin(self):
        self.cancel_interaction()
        self.interaction_started.emit()

    def _commit(self, value):
        self._pending = value
        self._deadline = time.monotonic() + 1.0
        self._seek_timeout.start()
        self.seek_requested.emit(value)

    def reject_seek(self):
        self._seek_timeout.stop()
        self._pending = None
        self._target = None
        self.set_progress(self._last_progress)

    def _expire_pending(self):
        self.reject_seek()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled() and hasattr(self, "_seek_timeout"):
            self.cancel_interaction()
        if event.type() == QEvent.Type.EnabledChange and hasattr(self, "_track"):
            for visual in (self._track, self._fill, self._handle):
                visual.setEnabled(self.isEnabled())
            self.update()

    def _point(self, event):
        value = (event.position().x() - self.handle_size / 2) / max(1, self.width() - self.handle_size)
        self.setSliderPosition(round(max(0.0, min(1.0, value)) * self.maximum()))
        self._visual_progress = self.sliderPosition() / self.maximum()
        self.update()
        self.preview_changed.emit(self.sliderPosition() / self.maximum())

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.isEnabled():
            event.ignore()
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self._begin()
        self._dragging = True
        self.setSliderDown(True)
        self._point(event)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._point(event)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._point(event)
            value = self.sliderPosition() / self.maximum()
            self.setValue(self.sliderPosition())
            self.cancel_interaction()
            self._commit(value)
            event.accept()
        else:
            event.ignore()

    def keyPressEvent(self, event):
        keys = (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
            Qt.Key.Key_Home,
            Qt.Key.Key_End,
            Qt.Key.Key_PageUp,
            Qt.Key.Key_PageDown,
        )
        if event.key() not in keys or not self.isEnabled():
            super().keyPressEvent(event)
            return
        self._begin()
        super().keyPressEvent(event)
        self._visual_progress = self.value() / self.maximum()
        self.update()
        self.preview_changed.emit(self.value() / self.maximum())
        self._commit(self.value() / self.maximum())

    def wheelEvent(self, event):
        if not self.isEnabled():
            event.ignore()
            return
        self._begin()
        super().wheelEvent(event)
        self._visual_progress = self.value() / self.maximum()
        self.update()
        self.preview_changed.emit(self.value() / self.maximum())
        self._commit(self.value() / self.maximum())

    def hideEvent(self, event):
        self.cancel_interaction()
        for animation in getattr(self, "_motion", {}).values():
            animation.stop()
        self.visualProgress = self._last_progress
        super().hideEvent(event)

    def sizeHint(self):
        return QSize(200, self.handle_size)
