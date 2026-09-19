"""Bounded, worker-processed artwork backgrounds; no blur work in paintEvent."""

import asyncio
import logging
import math
import os
import time
from collections import Counter, OrderedDict

from PyQt6.QtCore import QEasingCurve, QRectF, Qt, QTimer, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QImageReader, QLinearGradient, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import QFrame, QStyle, QStyleOption

from core.utils.qobject import is_valid_qobject
from core.widgets.yasb.media_v2_motion import animate, settle

logger = logging.getLogger("MediaV2")


def prepare_background(image, filename, radius):
    # QImage and Pillow are worker-safe. Never create a QPixmap here.
    from PIL import Image, ImageFilter

    if filename:
        reader = QImageReader(os.path.expandvars(os.path.expanduser(filename)))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isEmpty() or size.width() * size.height() > 100_000_000:
            raise ValueError("Background image is missing, unsupported or too large")
        reader.setScaledSize(size.scaled(640, 640, Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
    if image.isNull():
        return QImage()
    image = image.scaled(
        640, 640, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    ).convertToFormat(QImage.Format.Format_RGBA8888)
    bits = image.constBits()
    bits.setsize(image.sizeInBytes())
    source = Image.frombytes("RGBA", (image.width(), image.height()), bytes(bits), "raw", "RGBA", image.bytesPerLine())
    if radius:
        source = source.filter(ImageFilter.GaussianBlur(radius))
    data = source.tobytes()
    return QImage(data, source.width, source.height, source.width * 4, QImage.Format.Format_RGBA8888).copy()


def artwork_palette(image):
    if image.isNull():
        return ["#cba6f7", "#89b4fa", "#f38ba8"]
    sample = image.scaled(32, 32, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    colors = Counter()
    for y in range(sample.height()):
        for x in range(sample.width()):
            color = sample.pixelColor(x, y)
            if color.alpha() > 128:
                colors[(color.red() // 16, color.green() // 16, color.blue() // 16)] += 1
    result = [QColor(*(min(255, v * 16 + 8) for v in rgb)).name() for rgb, _ in colors.most_common(3)]
    if not result:
        return ["#cba6f7", "#89b4fa", "#f38ba8"]
    return (result * 3)[:3]


def prepare_assets(image, filename, radius):
    background = prepare_background(image, filename, radius)
    return background, artwork_palette(image if not image.isNull() else background)


class MediaSurface(QFrame):
    palette_changed = pyqtSignal(object)

    def __init__(self, options, radius, parent=None):
        super().__init__(parent)
        self.options = options
        self.radius = radius
        self._mix = 1.0
        self._image_opacity = 0.9
        self._overlay_top = QColor(30, 30, 46, 140)
        self._overlay_middle = QColor(30, 30, 46, 184)
        self._overlay_bottom = QColor(30, 30, 46, 230)
        self._pixmap = QPixmap()
        self._previous = QPixmap()
        self._source = QImage()
        self._key = None
        self._loaded_key = None
        self._task = None
        self._cache = OrderedDict()
        self._palette_cache = {}
        self._ambient = bool(getattr(options, "ambient_motion", True))
        self._has_media = False
        self._playing = False
        self._ambient_opacity = 0.0
        self._orbit_start = time.monotonic()
        self._orbit_timer = QTimer(self)
        # These very faint, 90-second orbits move less than a pixel per frame.
        self._orbit_timer.setInterval(83)
        self._orbit_timer.timeout.connect(self.update)

    @pyqtProperty(bool)
    def ambientMotion(self):
        return self._ambient

    @ambientMotion.setter
    def ambientMotion(self, value):
        self._ambient = bool(value)
        self._sync_orbit()
        self._sync_ambient_opacity()

    @pyqtProperty(float)
    def ambientOpacity(self):
        return self._ambient_opacity

    @ambientOpacity.setter
    def ambientOpacity(self, value):
        self._ambient_opacity = max(0.0, min(0.08, float(value)))
        self.update()

    def _ambient_target(self):
        if self.options.mode == "color" or not self._ambient or not self._has_media:
            return 0.0
        if self._playing:
            return 0.025
        return max(0.0, min(0.08, float(getattr(self.options, "ambient_paused_opacity", 0.01))))

    def _sync_ambient_opacity(self, *, animate_change=True):
        target = self._ambient_target()
        if animate_change and self.isVisible():
            animate(self, "ambientOpacity", target, 800, QEasingCurve.Type.InOutQuad)
        else:
            self.ambientOpacity = target

    def set_media_state(self, has_media, playing):
        has_media = bool(has_media)
        playing = bool(playing)
        if has_media != self._has_media or playing != self._playing:
            self._has_media = has_media
            self._playing = playing
            self._sync_orbit()
            self._sync_ambient_opacity()

    def set_playing(self, playing):
        # Backward-compatible helper for callers that only know playback state.
        self.set_media_state(bool(playing), playing)

    def _sync_orbit(self):
        if self.options.mode != "color" and self._ambient and self._has_media and self.isVisible():
            if not self._orbit_timer.isActive():
                self._orbit_start = time.monotonic()
                self._orbit_timer.start()
        else:
            self._orbit_timer.stop()

    @pyqtProperty(float)
    def backgroundMix(self):
        return self._mix

    @backgroundMix.setter
    def backgroundMix(self, value):
        self._mix = value
        if value >= 1:
            self._previous = QPixmap()
        self.update()

    @pyqtProperty(float)
    def imageOpacity(self):
        return self._image_opacity

    @imageOpacity.setter
    def imageOpacity(self, value):
        self._image_opacity = max(0.0, min(1.0, value))
        self.update()

    @pyqtProperty(QColor)
    def overlayTop(self):
        return self._overlay_top

    @overlayTop.setter
    def overlayTop(self, value):
        self._overlay_top = QColor(value)
        self.update()

    @pyqtProperty(QColor)
    def overlayMiddle(self):
        return self._overlay_middle

    @overlayMiddle.setter
    def overlayMiddle(self, value):
        self._overlay_middle = QColor(value)
        self.update()

    @pyqtProperty(QColor)
    def overlayBottom(self):
        return self._overlay_bottom

    @overlayBottom.setter
    def overlayBottom(self, value):
        self._overlay_bottom = QColor(value)
        self.update()

    def set_artwork(self, pixmap, *, clear_previous=False):
        if self.options.mode == "color":
            return
        clear_previous = clear_previous and self.options.mode == "album_art"
        key = (self.options.image if self.options.mode == "image" else pixmap.cacheKey(), self.options.blur_radius)
        if key == self._key:
            if clear_previous:
                self._previous = QPixmap()
                self.update()
            return
        self._key = key
        self._source = pixmap.toImage() if self.options.mode == "album_art" else QImage()
        if clear_previous:
            animation = getattr(self, "_motion", {}).get("backgroundMix")
            if animation is not None:
                animation.stop()
            self._previous = QPixmap()
            self._pixmap = QPixmap()
            self.backgroundMix = 1.0
            if pixmap.isNull() and self.options.mode == "album_art":
                self._loaded_key = key
                self.palette_changed.emit(["#cba6f7", "#89b4fa", "#f38ba8"])
                return
        if self.isVisible():
            self._request()

    def _request(self):
        if self.options.mode == "color" or self._key == self._loaded_key or self._key is None:
            return
        if self._task and not self._task.done():
            return
        if self._key in self._cache:
            self._install(self._key, self._cache[self._key])
            return
        task = asyncio.get_running_loop().create_task(self._load_latest())
        self._task = task
        cancel = lambda: task.cancel()
        self.destroyed.connect(cancel)
        task.add_done_callback(lambda _: self._release(cancel))

    def _release(self, cancel):
        if is_valid_qobject(self):
            self.destroyed.disconnect(cancel)

    async def _load_latest(self):
        while is_valid_qobject(self) and self.isVisible() and self._key != self._loaded_key:
            key = self._key
            if key in self._cache:
                self._install(key, self._cache[key])
            else:
                await self._load(key, self._source)

    async def _load(self, key, image):
        try:
            filename = self.options.image if self.options.mode == "image" else ""
            image, palette = await asyncio.to_thread(prepare_assets, image, filename, self.options.blur_radius)
            if is_valid_qobject(self) and key == self._key and self.isVisible():
                self._install(key, QPixmap.fromImage(image), palette)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Unable to load media background; using QSS fallback", exc_info=True)
            if is_valid_qobject(self) and key == self._key:
                self._install(key, QPixmap())

    def _install(self, key, pixmap, palette=None):
        self._loaded_key = key
        self._cache[key] = pixmap
        if palette is not None:
            self._palette_cache[key] = palette
        self.palette_changed.emit(self._palette_cache.get(key, ["#cba6f7", "#89b4fa", "#f38ba8"]))
        self._cache.move_to_end(key)
        while len(self._cache) > 4:
            old_key, _ = self._cache.popitem(last=False)
            self._palette_cache.pop(old_key, None)
        self._previous = self._pixmap
        self._pixmap = pixmap
        self.backgroundMix = 0.0
        animate(self, "backgroundMix", 1.0, 800, QEasingCurve.Type.InOutQuad)

    def showEvent(self, event):
        super().showEvent(event)
        self._request()
        self._sync_orbit()
        self._sync_ambient_opacity(animate_change=False)

    def hideEvent(self, event):
        self._orbit_timer.stop()
        if self._task:
            self._task.cancel()
            self._task = None
        settle(self)
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        option = QStyleOption()
        option.initFrom(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option, painter, self)
        if self.options.mode == "color":
            color = getattr(self.options, "color", None)
            if color:
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                path = QPainterPath()
                path.addRoundedRect(QRectF(self.rect()), self.radius, self.radius)
                painter.fillPath(path, QColor(color))
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        bounds = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(bounds, self.radius, self.radius)
        painter.setClipPath(path)
        for pixmap, opacity in ((self._previous, 1 - self._mix), (self._pixmap, self._mix)):
            if pixmap.isNull():
                continue
            scale = max(bounds.width() / pixmap.width(), bounds.height() / pixmap.height())
            crop = QRectF(0, 0, bounds.width() / scale, bounds.height() / scale)
            crop.moveCenter(QRectF(pixmap.rect()).center())
            painter.setOpacity(opacity * self._image_opacity)
            painter.drawPixmap(bounds, pixmap, crop)
        if not self._pixmap.isNull() or not self._previous.isNull():
            painter.setOpacity(1.0)
            overlay = QLinearGradient(0, 0, 0, self.height())
            overlay.setColorAt(0, self._overlay_top)
            overlay.setColorAt(0.5, self._overlay_middle)
            overlay.setColorAt(1, self._overlay_bottom)
            painter.fillPath(path, overlay)
        if self._ambient_opacity > 0:
            phase = (time.monotonic() - self._orbit_start) * math.tau / 90
            painter.setOpacity(self._ambient_opacity)
            painter.setPen(Qt.PenStyle.NoPen)
            scale = self.width() / 619
            for ratio, dx, dy, color in (
                (0.8, math.cos(phase * 2) * 150, math.sin(phase * 2) * 100, "#cba6f7"),
                (0.9, math.sin(phase * 1.5) * -150, math.cos(phase * 1.5) * -100, "#89b4fa"),
            ):
                diameter = self.width() * ratio
                painter.setBrush(QColor(color))
                painter.drawEllipse(
                    QRectF(
                        (self.width() - diameter) / 2 + dx * scale,
                        (self.height() - diameter) / 2 + dy * scale,
                        diameter,
                        diameter,
                    )
                )
