"""Virtualized lyric text and captured input; no media or network ownership."""

from __future__ import annotations

import math
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, NamedTuple, cast

import PyQt6.QtCore as QtCore
from PyQt6.QtCore import (
    QAbstractListModel,
    QEasingCurve,
    QEvent,
    QModelIndex,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFocusEvent,
    QFont,
    QHideEvent,
    QImage,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QResizeEvent,
    QTextCharFormat,
    QTextLayout,
    QTextOption,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QListView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from core.validation.widgets.yasb.media_v2 import MediaLyricsConfig
from core.widgets.services.media.lyrics_model import LyricsDocument
from core.widgets.yasb.media_v2_components import identify
from core.widgets.yasb.media_v2_motion import FrameClock, animate

BEFORE, CURRENT, AFTER = 0, 1, 2
# pyqtProperty exists at runtime but is missing from the PyQt6 type stubs
pyqtProperty: Callable[..., Any] = getattr(QtCore, "pyqtProperty")
# One glow mask never exceeds this many pixels, which bounds its cost on the GUI thread.
GLOW_PIXELS = 120_000


@dataclass(frozen=True)
class LineLook:
    """One resolved before, current or after style; None defers to the fade."""

    variant: int
    underline: bool
    strikethrough: bool
    opacity: float | None
    scale: float | None

    @property
    def draw_key(self) -> tuple[int, bool, bool]:
        return self.variant, self.underline, self.strikethrough


class RowLook(NamedTuple):
    scale: float
    opacity: float
    tint: float
    side: float
    source: int
    target: int
    mix: float


def resolve_looks(
    options: MediaLyricsConfig,
) -> tuple[tuple[LineLook, LineLook, LineLook], tuple[tuple[bool | None, bool], ...]]:
    """Resolve the three state blocks once; variant 0 is always the unstyled font."""
    variants: list[tuple[bool | None, bool]] = [(None, False)]
    looks: list[LineLook] = []
    style = options.style
    for block in (style.before, style.current, style.after):
        key = (block.bold, block.italic)
        if key not in variants:
            variants.append(key)
        looks.append(
            LineLook(
                variants.index(key),
                block.underline,
                block.strikethrough,
                block.opacity,
                block.scale,
            )
        )
    return (looks[0], looks[1], looks[2]), tuple(variants)


def mix_color(first: QColor, second: QColor, amount: float) -> QColor:
    if amount <= 0:
        return QColor(first)
    if amount >= 1:
        return QColor(second)
    return QColor(
        round(first.red() + (second.red() - first.red()) * amount),
        round(first.green() + (second.green() - first.green()) * amount),
        round(first.blue() + (second.blue() - first.blue()) * amount),
        round(first.alpha() + (second.alpha() - first.alpha()) * amount),
    )


def mix_optional(first: QColor | None, second: QColor | None, amount: float) -> QColor | None:
    """Blend two optional fills, treating a missing fill as transparent."""
    if first is None and second is None:
        return None
    if first is None:
        assert second is not None
        first = QColor(second.red(), second.green(), second.blue(), 0)
    if second is None:
        second = QColor(first.red(), first.green(), first.blue(), 0)
    return mix_color(first, second, amount)


def ink_rect(layout: QTextLayout) -> QRectF:
    rect = QRectF()
    for index in range(layout.lineCount()):
        line = layout.lineAt(index).naturalTextRect()
        if line.width() > 0:
            rect = line if rect.isNull() else rect.united(line)
    return rect


def render_glow(layout: QTextLayout, color: QColor, radius: float, dpr: float) -> tuple[QImage, QRectF]:
    """Blur the layout's glyph coverage once; reduced density keeps large radii cheap."""
    from PIL import Image, ImageFilter

    ink = ink_rect(layout)
    if ink.isEmpty() or radius <= 0:
        return QImage(), QRectF()
    spread = radius * 1.5
    area = (ink.width() + 2 * spread) * (ink.height() + 2 * spread)
    density = min(dpr / max(2.0, min(4.0, radius * dpr / 4)), math.sqrt(GLOW_PIXELS / area))
    width = max(1, math.ceil((ink.width() + 2 * spread) * density))
    height = max(1, math.ceil((ink.height() + 2 * spread) * density))
    mask = QImage(width, height, QImage.Format.Format_Alpha8)
    mask.fill(0)
    painter = QPainter(mask)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.scale(density, density)
    painter.translate(spread - ink.x(), spread - ink.y())
    painter.setPen(QColor(0, 0, 0, 255))
    layout.draw(painter, QPointF())
    painter.end()
    bits = mask.constBits()
    if bits is None:
        return QImage(), QRectF()
    coverage = Image.frombytes(  # pyright: ignore[reportUnknownMemberType] - Pillow stubs omit buffer arguments
        "L", (width, height), bits.asstring(mask.sizeInBytes()), "raw", "L", mask.bytesPerLine()
    ).filter(ImageFilter.GaussianBlur(radius * density / 2))
    data = coverage.tobytes()  # pyright: ignore[reportUnknownMemberType] - Pillow variadic encoder stub
    blurred = QImage(data, width, height, width, QImage.Format.Format_Alpha8)
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(color.red(), color.green(), color.blue()))
    painter = QPainter(image)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, blurred)
    painter.end()
    return image, ink.adjusted(-spread, -spread, spread, spread)


class LyricsPlayhead:
    """Presentation-only position between timeline samples; it never polls the player.

    Small sample differences are absorbed gradually so a sweep never steps backwards.
    A larger difference, a new identity, a pause or a rate change snaps.
    """

    ABSORB_MS = 150.0

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.identity: tuple[str, int] | None = None
        self.playing = False
        self.rate: float = 1.0
        self._anchor: float | None = None
        self._anchor_time = 0.0
        self._offset = 0.0
        self._span = 1.0
        self._last: float | None = None

    def sample(self, position_ms: int | None, identity: tuple[str, int] | None, playing: bool, rate: float) -> None:
        now = self.clock()
        rate = max(0.0, float(rate))
        predicted = self.position(now)
        snap = (
            position_ms is None
            or predicted is None
            or identity != self.identity
            or not playing
            or not self.playing
            or rate != self.rate
            or abs(position_ms - predicted) > self.ABSORB_MS
        )
        self.identity, self.playing, self.rate = identity, playing, rate
        if position_ms is None:
            self._anchor, self._last = None, None
            return
        self._anchor, self._anchor_time = float(position_ms), now
        if snap or predicted is None:
            self._offset, self._last = 0.0, None
        else:
            self._offset = predicted - position_ms
            self._span = max(0.5, 2 * abs(self._offset) / (1000 * max(rate, 0.05)))

    def position(self, now: float | None = None) -> float | None:
        if self._anchor is None:
            return None
        now = self.clock() if now is None else now
        elapsed = max(0.0, now - self._anchor_time)
        value = self._anchor + (elapsed * 1000 * self.rate if self.playing else 0.0)
        if self._offset:
            value += self._offset * max(0.0, 1 - elapsed / self._span)
        if self.playing and self._last is not None and value < self._last:
            value = self._last
        self._last = value
        return value


def right_to_left(text: str) -> bool:
    return any(unicodedata.bidirectional(character) in ("R", "AL") for character in text)


def text_segments(layout: QTextLayout, start: int, end: int) -> tuple[QRectF, ...]:
    """Map a UTF-16 range to one rectangle per wrapped line, in layout coordinates."""
    segments: list[QRectF] = []
    for index in range(layout.lineCount()):
        line = layout.lineAt(index)
        low, high = max(start, line.textStart()), min(end, line.textStart() + line.textLength())
        if low < high:
            left, right = line.cursorToX(low)[0], line.cursorToX(high)[0]
            segments.append(QRectF(min(left, right), line.y(), abs(right - left), line.height()))
    return tuple(segments)


class LyricsRows(QAbstractListModel):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.texts: tuple[str, ...] = ()

    def replace(self, document: LyricsDocument | None) -> None:
        self.beginResetModel()
        self.texts = (
            tuple(line.text for line in document.lines)
            if document and document.lines
            else tuple(document.plain.splitlines())
            if document
            else ()
        )
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() or not self.texts else len(self.texts) + 2

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        row = index.row() - 1
        if (
            index.isValid()
            and 0 <= row < len(self.texts)
            and role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.AccessibleTextRole)
        ):
            return self.texts[row]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if 1 <= index.row() <= len(self.texts):
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return Qt.ItemFlag.NoItemFlags


class LyricsDelegate(QStyledItemDelegate):
    def __init__(self, view: LyricsView) -> None:
        super().__init__(view)
        self.view = view
        self.layouts: OrderedDict[tuple[int, int], QTextLayout] = OrderedDict()
        self.heights: dict[int, int] = {}
        self.glows: OrderedDict[tuple[object, ...], tuple[QImage, QRectF]] = OrderedDict()
        self.sweeps: OrderedDict[tuple[int, int], tuple[tuple[int, int | None, tuple[QRectF, ...], bool], ...]] = (
            OrderedDict()
        )
        self._scratch = QImage()
        self._mask = QImage()
        self._mask_key: tuple[object, ...] | None = None

    def reset(self) -> None:
        self.layouts.clear()
        self.heights.clear()
        self.glows.clear()
        self.sweeps.clear()
        self._mask_key = None

    def base_font(self) -> QFont:
        font = self.view.font()
        parent = self.view.parentWidget()
        if parent is not None and font.pixelSize() == parent.font().pixelSize():
            # Older themes give the whole section a single small UI font.
            # Keep its face and honor a distinct row size when one is supplied.
            font.setPixelSize(max(font.pixelSize(), round(18 * self.view.scale)))
        return font

    def font_for(self, variant: int) -> QFont:
        font = self.base_font()
        bold, italic = self.view.variants[variant]
        if bold is not None:
            font.setWeight(QFont.Weight(max(font.weight(), 700) if bold else min(font.weight(), 400)))
        if italic:
            font.setItalic(True)
        return font

    def _line_width(self) -> float:
        _, max_scale, pad = self.view.row_geometry()
        width = self.view.canvas.width() - round(2 * self.view.options.margins.horizontal * self.view.scale)
        return max(1, (width - 2 * pad) / max_scale)

    def layout_for(self, row: int, variant: int = 0) -> QTextLayout:
        key = (row, variant)
        cached = self.layouts.get(key)
        if cached is not None:
            self.layouts.move_to_end(key)
            return cached
        layout = QTextLayout(self.view.rows.texts[row], self.font_for(variant))
        layout.setCacheEnabled(True)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        option.setAlignment(self.view.text_alignment)
        layout.setTextOption(option)
        layout.beginLayout()
        height = 0.0
        width = self._line_width()
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            line.setPosition(QPointF(0, height))
            height += line.height()
        layout.endLayout()
        while len(self.layouts) >= 64:
            self.layouts.popitem(last=False)
        self.layouts[key] = layout
        return layout

    def row_height(self, row: int) -> int:
        """Size a row for its tallest configured variant, so a state change never moves it."""
        height = self.heights.get(row)
        if height is None:
            variants, max_scale, pad = self.view.row_geometry()
            text = 0.0
            for variant in variants:
                layout = self.layout_for(row, variant)
                text = max(text, sum(layout.lineAt(index).height() for index in range(layout.lineCount())))
            height = max(
                round(self.view.options.line_height * self.view.scale), round(text * max_scale + 2 * pad)
            ) + round(self.view.options.line_spacing * self.view.scale)
            self.heights[row] = height
        return height

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        row = index.row() - 1
        if row < 0 or row >= len(self.view.rows.texts):
            ratio = self.view.options.center_position if row < 0 else 1.0 - self.view.options.center_position
            return QSize(1, max(0, round(self.view.canvas.height() * ratio - 15 * self.view.scale)))
        return QSize(max(1, self.view.canvas.width()), self.row_height(row))

    def placement(self, rect: QRect, layout: QTextLayout) -> tuple[QPointF, QPointF]:
        """Return the scale origin of one row and the layout origin relative to it."""
        view = self.view
        bounds = layout.boundingRect()
        height = bounds.height()
        top = rect.y() + max(0, (rect.height() - round(view.options.line_spacing * view.scale) - height) / 2)
        margin = round(view.options.margins.horizontal * view.scale) + view.row_geometry()[2]
        text_width = bounds.width()
        if view.options.alignment == "center":
            left = rect.x() + (rect.width() - text_width) / 2
            origin_x, draw_x = text_width / 2, -text_width / 2
        elif view.options.alignment == "right":
            left = rect.right() - margin - text_width
            origin_x, draw_x = text_width, -text_width
        else:
            left = rect.x() + margin
            origin_x, draw_x = 0, 0
        return QPointF(left + origin_x, top + height / 2), QPointF(draw_x, -height / 2)

    def state_colors(self) -> tuple[QColor, QColor, QColor]:
        view = self.view
        return (
            view.side_color(BEFORE) or view.inactive_color,
            view.side_color(CURRENT) or view.active_color,
            view.side_color(AFTER) or view.inactive_color,
        )

    def _line_color(self, row: int, tint: float | None) -> QColor:
        document, position = self.view.document, self.view.position_ms
        if document is None or not document.lines or position is None:
            return self.view.inactive_color
        before, accent, after = self.state_colors()
        line = document.lines[row]
        active = row == self.view.current_line and (line.end_ms is None or position < line.end_ms)
        if row == self.view.current_line and not active:
            return before
        level = float(active) if tint is None else tint
        return mix_color(mix_color(before, after, self.view.line_side(row)), accent, level)

    def formats(self, row: int, tint: float | None = None, look: int = -1) -> list[QTextLayout.FormatRange]:
        document = self.view.document
        if document is None:
            return []
        normal = self.view.inactive_color
        text = self.view.rows.texts[row]
        decoration = self.view.looks[look] if look >= 0 else None

        def span(start: int, length: int, color: QColor) -> QTextLayout.FormatRange:
            result = QTextLayout.FormatRange()
            result.start, result.length = start, length
            style = QTextCharFormat()
            style.setForeground(color)
            if decoration is not None:
                style.setFontUnderline(decoration.underline)
                style.setFontStrikeOut(decoration.strikethrough)
            result.format = style
            return result

        length = len(text.encode("utf-16-le")) // 2
        if not document.lines or self.view.position_ms is None:
            return [span(0, length, normal)]
        line = document.lines[row]
        position = self.view.position_ms
        before, accent, after = self.state_colors()
        if line.words and row != self.view.current_line:
            return [span(0, length, mix_color(before, after, self.view.line_side(row)))]
        if line.words:
            future = QColor(after)
            future.setAlphaF(after.alphaF() * self.view.options.unsung_opacity)
            ranges: list[QTextLayout.FormatRange] = []
            offset = 0
            starts = sorted({word.start_ms for word in line.words})
            following = dict(zip(starts, starts[1:]))
            for word in line.words:
                count = len(word.text.encode("utf-16-le")) // 2
                if not count:
                    continue
                # Timing order may differ from text order; each interval stands
                # alone. Missing ends use only a presentation boundary.
                end = word.end_ms
                if end is None:
                    end = following.get(word.start_ms, line.end_ms)
                active = position >= word.start_ms and (
                    position < end if end is not None else row == self.view.current_line
                )
                ranges.append(
                    span(offset, count, accent if active else before if position >= word.start_ms else future)
                )
                offset += count
            return ranges
        return [span(0, length, self._line_color(row, tint))]

    def sweep_parts(self, row: int, variant: int) -> tuple[tuple[int, int | None, tuple[QRectF, ...], bool], ...]:
        """Timed parts of one row: start, presentation end, wrapped rectangles and direction."""
        key = (row, variant)
        cached = self.sweeps.get(key)
        if cached is not None:
            return cached
        document = self.view.document
        assert document is not None
        layout, line = self.layout_for(row, variant), document.lines[row]
        parts: list[tuple[int, int | None, tuple[QRectF, ...], bool]] = []
        if line.words:
            starts = sorted({word.start_ms for word in line.words})
            following = dict(zip(starts, starts[1:]))
            offset = 0
            for word in line.words:
                count = len(word.text.encode("utf-16-le")) // 2
                if not count:
                    continue
                end = word.end_ms if word.end_ms is not None else following.get(word.start_ms, line.end_ms)
                parts.append(
                    (word.start_ms, end, text_segments(layout, offset, offset + count), right_to_left(word.text))
                )
                offset += count
        else:
            # A presentation-only sweep; it is never stored as word timing.
            limit = line.start_ms + self.view.options.line_sweep_max_ms
            following_start = document.lines[row + 1].start_ms if row + 1 < len(document.lines) else None
            end = line.end_ms if line.end_ms is not None else following_start
            length = len(line.text.encode("utf-16-le")) // 2
            parts.append(
                (
                    line.start_ms,
                    limit if end is None else min(end, limit),
                    text_segments(layout, 0, length),
                    right_to_left(line.text),
                )
            )
        while len(self.sweeps) >= 4:
            self.sweeps.popitem(last=False)
        self.sweeps[key] = tuple(parts)
        return self.sweeps[key]

    def sweep_region(self, layout: QTextLayout) -> QRectF:
        glow = self.view.options.glow
        extent = glow.radius * self.view.scale * 1.5 if glow.enabled and glow.target == "sung" else 2.0
        return ink_rect(layout).adjusted(-extent, -extent, extent, extent)

    def sung_mask(self, segments: list[tuple[QRectF, float]], region: QRectF, density: float) -> QImage:
        """Coverage of the sung part, reused across frames; soft edge of sweep_softness em."""
        key = (tuple((rect.x(), rect.y(), rect.width(), fraction) for rect, fraction in segments), region, density)
        if key == self._mask_key:
            return self._mask
        size = QSize(max(1, math.ceil(region.width() * density)), max(1, math.ceil(region.height() * density)))
        if self._mask.size() != size:
            self._mask = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
        self._mask.fill(0)
        painter = QPainter(self._mask)
        painter.scale(size.width() / region.width(), size.height() / region.height())
        painter.translate(-region.topLeft())
        soft = self.view.options.sweep_softness * self.base_font().pixelSize()
        top, bottom = region.top(), region.bottom()
        for rect, fraction in segments:
            if fraction <= 0 or rect.width() <= 0:
                continue
            band = QRectF(rect.left(), top, rect.width(), bottom - top)
            edge = rect.left() + rect.width() * fraction
            if fraction >= 1 or soft <= 0:
                painter.fillRect(
                    band.adjusted(0, 0, (edge - rect.right()) if fraction < 1 else 0, 0), Qt.GlobalColor.black
                )
                continue
            painter.save()
            painter.setClipRect(band)
            painter.fillRect(
                QRectF(rect.left(), top, max(0.0, edge - soft / 2 - rect.left()), bottom - top), Qt.GlobalColor.black
            )
            gradient = QLinearGradient(edge - soft / 2, 0, edge + soft / 2, 0)
            gradient.setColorAt(0, QColor(0, 0, 0, 255))
            gradient.setColorAt(1, QColor(0, 0, 0, 0))
            painter.fillRect(QRectF(edge - soft / 2, top, soft, bottom - top), gradient)
            painter.restore()
        painter.end()
        self._mask_key = key
        return self._mask

    def draw_masked(
        self, painter: QPainter, origin: QPointF, region: QRectF, mask: QImage, draw: Callable[[QPainter], None]
    ) -> None:
        """Draw through the sung mask using one reused scratch image."""
        if self._scratch.size() != mask.size():
            self._scratch = QImage(mask.size(), QImage.Format.Format_ARGB32_Premultiplied)
        self._scratch.fill(0)
        layer = QPainter(self._scratch)
        layer.setRenderHint(QPainter.RenderHint.Antialiasing)
        layer.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        layer.scale(mask.width() / region.width(), mask.height() / region.height())
        layer.translate(-region.topLeft())
        draw(layer)
        layer.resetTransform()
        layer.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        layer.drawImage(0, 0, mask)
        layer.end()
        painter.drawImage(QRectF(origin + region.topLeft(), region.size()), self._scratch, QRectF(self._scratch.rect()))

    def glow_for(self, row: int, variant: int, layout: QTextLayout, color: QColor) -> tuple[QImage, QRectF]:
        view = self.view
        dpr = view.canvas.devicePixelRatioF()
        key = (row, variant, color.rgba(), dpr, layout.lineAt(0).width() if layout.lineCount() else 0.0)
        cached = self.glows.get(key)
        if cached is not None:
            self.glows.move_to_end(key)
            return cached
        result = render_glow(layout, color, view.options.glow.radius * view.scale, dpr)
        while len(self.glows) >= 3:
            self.glows.popitem(last=False)
        self.glows[key] = result
        return result

    def _draw(self, painter: QPainter, rect: QRect, row: int, look: RowLook, state: int, weight: float) -> None:
        view = self.view
        style = view.looks[state] if state >= 0 else None
        layout = self.layout_for(row, style.variant if style is not None else 0)
        center, origin = self.placement(rect, layout)
        painter.save()
        painter.setOpacity(painter.opacity() * look.opacity * weight)
        painter.translate(center)
        painter.scale(look.scale, look.scale)
        background = view.background_color(look) if style is not None else None
        if background is not None and background.alpha() > 0:
            ink = ink_rect(layout)
            if not ink.isEmpty():
                pad = view.row_geometry()[2]
                radius = view.options.style.background_radius * view.scale
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(background)
                painter.drawRoundedRect(ink.translated(origin).adjusted(-pad, -pad, pad, pad), radius, radius)
        document = view.document
        decorated = style is not None and (style.underline or style.strikethrough)
        segments = view.sweep_segments(row, style.variant) if style is not None and state == CURRENT else None
        if segments is not None:
            accent = self.state_colors()[CURRENT]
            unsung = QColor(accent)
            unsung.setAlphaF(accent.alphaF() * view.options.unsung_opacity)
            self._draw_solid(painter, layout, origin, row, state, unsung)
            region = self.sweep_region(layout)
            density = view.canvas.devicePixelRatioF() * max(1.0, look.scale)
            mask = self.sung_mask(segments, region, density)
            self.draw_masked(
                painter,
                origin,
                region,
                mask,
                lambda layer: self._draw_solid(layer, layout, QPointF(), row, state, accent),
            )
        elif document and document.lines and (document.lines[row].words or decorated):
            layout.draw(painter, origin, self.formats(row, look.tint, state))
        else:
            painter.setPen(self._line_color(row, look.tint))
            layout.draw(painter, origin)
        painter.restore()

    def _draw_solid(
        self, painter: QPainter, layout: QTextLayout, origin: QPointF, row: int, state: int, color: QColor
    ) -> None:
        style = self.view.looks[state]
        if style.underline or style.strikethrough:
            length = len(self.view.rows.texts[row].encode("utf-16-le")) // 2
            span = QTextLayout.FormatRange()
            span.start, span.length = 0, length
            format = QTextCharFormat()
            format.setForeground(color)
            format.setFontUnderline(style.underline)
            format.setFontStrikeOut(style.strikethrough)
            span.format = format
            layout.draw(painter, origin, [span])
        else:
            painter.setPen(color)
            layout.draw(painter, origin)

    def paint(self, painter: QPainter | None, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        row = index.row() - 1
        if painter is None or not 0 <= row < len(self.view.rows.texts):
            return
        look = self.view.row_look(row)
        if look.opacity <= 0:
            return
        painter.save()
        painter.setClipRect(option.rect)
        looks = self.view.looks
        if look.mix < 1 and look.source >= 0 and looks[look.source].draw_key != looks[look.target].draw_key:
            # A font variant or decoration cannot be interpolated; crossfade two draws.
            self._draw(painter, option.rect, row, look, look.source, 1 - look.mix)
            self._draw(painter, option.rect, row, look, look.target, look.mix)
        else:
            self._draw(painter, option.rect, row, look, look.target, 1.0)
        painter.restore()


def _side_property(store: str, state: int) -> Any:
    """A QSS-settable colour for one side; an invalid colour defers to the palette."""

    def get(view: LyricsView) -> QColor:
        return QColor(getattr(view, store)[state])

    def set_(view: LyricsView, value: QColor) -> None:
        getattr(view, store)[state] = QColor(value)
        view.restyle()

    return pyqtProperty(QColor, get, set_)


class LyricsView(QListView):
    seek_requested = pyqtSignal(float, object)

    def __init__(
        self,
        scale: float,
        parent: QWidget,
        options: MediaLyricsConfig | None = None,
        *,
        clock: FrameClock | None = None,
    ) -> None:
        super().__init__(parent)
        identify(self, "media-lyrics-view", "media-lyrics-view")
        self.scale = scale
        self.options = options or MediaLyricsConfig()
        self.looks, self.variants = resolve_looks(self.options)
        self._side_colors = [QColor(), QColor(), QColor()]
        self._side_backgrounds = [QColor(), QColor(), QColor()]
        self._glow_color = QColor()
        self._styled_geometry = self._resolve_geometry()
        self.document: LyricsDocument | None = None
        self.position_ms: int | None = None
        self.identity: tuple[str, int] | None = None
        self.current_line = -1
        self.browsing = False
        self.playhead = LyricsPlayhead()
        self._sweep_enabled = self.options.word_highlight == "sweep" or self.options.line_sweep
        self._sweep_frames = (clock or FrameClock(self)).subscription(self._sweep_tick, self.options.sweep_fps)
        self._paint_position: float | None = None
        self._accept_input = False
        self._gesture_start: QPoint | None = None
        self._pressed: tuple[QPoint, int, LyricsDocument, tuple[str, int]] | None = None
        self._press_scroll = 0
        self._dragging = False
        self._scroll_motion: QPropertyAnimation | None = None
        self._line_from: dict[int, tuple[float, float, float, float, int]] = {}
        self._line_far_from = (0.8, 0.5, 0.0, 1.0, AFTER)
        self._line_far_before = (0.8, 0.5, 0.0, 0.0, BEFORE)
        self._line_from_current = -1
        self._line_progress = 1.0
        self._current_active = False
        self._restore_scroll: int | None = None
        self._settle_layout = False
        canvas, scroll = self.viewport(), self.verticalScrollBar()
        assert canvas is not None and scroll is not None
        self.canvas = canvas
        self.scroll_bar = identify(scroll, "media-lyrics-scrollbar", "media-lyrics-scrollbar")
        canvas.setAutoFillBackground(False)
        self.rows = LyricsRows(self)
        self.setModel(self.rows)
        self.delegate = LyricsDelegate(self)
        self.setItemDelegate(self.delegate)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setBatchSize(128)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAccessibleName("Lyrics; Enter seeks, right click returns to the playing line")
        font = self.font()
        if self.options.font_family:
            font.setFamily(self.options.font_family)
        font.setPixelSize(max(1, round(self.options.font_size * scale)))
        font.setWeight(QFont.Weight(self.options.font_weight))
        self.setFont(font)
        self._return = QTimer(self)
        self._return.setSingleShot(True)
        self._return.setInterval(self.options.browse_return_ms)
        self._return.timeout.connect(self.follow)
        self._layout_follow = QTimer(self)
        self._layout_follow.setSingleShot(True)
        self._layout_follow.timeout.connect(self._follow_after_layout)
        self.scroll_bar.sliderPressed.connect(self.browse)
        self.scroll_bar.sliderMoved.connect(self.browse)
        self.scroll_bar.rangeChanged.connect(self._range_changed)
        if self._sweep_enabled:
            self.scroll_bar.valueChanged.connect(self._sync_sweep)
        self._line_motion = QVariantAnimation(self)
        self._line_motion.setDuration(self.options.animation_duration_ms)
        self._line_motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._line_motion.setStartValue(0.0)
        self._line_motion.setEndValue(1.0)
        self._line_motion.valueChanged.connect(self._set_line_progress)
        self._line_motion.finished.connect(self.finish_line_motion)

    @property
    def accept_input(self) -> bool:
        return self._accept_input

    @accept_input.setter
    def accept_input(self, value: bool) -> None:
        self._accept_input = value
        self._sync_sweep()

    def sweep_position(self) -> float | None:
        return self._paint_position if self._paint_position is not None else self.playhead.position()

    def sweep_segments(self, row: int, variant: int | None = None) -> list[tuple[QRectF, float]] | None:
        """Sung fraction of each wrapped rectangle of the current row, or None without a sweep."""
        document = self.document
        if not self._sweep_enabled or document is None or not document.lines or row != self.current_line:
            return None
        line = document.lines[row]
        if (self.options.word_highlight != "sweep") if line.words else not self.options.line_sweep:
            return None
        position = self.sweep_position()
        if position is None or line.end_ms is not None and position >= line.end_ms:
            return None
        segments: list[tuple[QRectF, float]] = []
        for start, end, rects, backwards in self.delegate.sweep_parts(
            row, self.looks[CURRENT].variant if variant is None else variant
        ):
            if position < start:
                progress = 0.0
            elif end is None or end <= start:
                progress = 1.0
            else:
                progress = min(1.0, (position - start) / (end - start))
            if backwards:
                # Mixed-direction runs fill as one unit at half progress.
                segments.extend((rect, float(progress >= 0.5)) for rect in rects)
                continue
            filled = progress * sum(rect.width() for rect in rects)
            for rect in rects:
                segments.append((rect, max(0.0, min(1.0, filled / rect.width())) if rect.width() > 0 else 0.0))
                filled -= rect.width()
        return segments

    def _sync_sweep(self, *_: object) -> None:
        document, current = self.document, self.current_line
        wanted = (
            self._sweep_enabled
            and self._accept_input
            and self.isVisible()
            and self.playhead.playing
            and document is not None
            and 0 <= current < len(document.lines)
            and self.visualRect(self.rows.index(current + 1)).intersects(self.canvas.rect())
        )
        if wanted:
            self._sweep_frames.start()
        else:
            self._sweep_frames.stop()

    def _sweep_tick(self) -> None:
        self._sync_sweep()
        if self._sweep_frames.isActive():
            self._update_row(self.current_line)

    @property
    def text_alignment(self) -> Qt.AlignmentFlag:
        return {
            "left": Qt.AlignmentFlag.AlignLeft,
            "center": Qt.AlignmentFlag.AlignHCenter,
            "right": Qt.AlignmentFlag.AlignRight,
        }[self.options.alignment]

    @property
    def active_color(self) -> QColor:
        return QColor(self.palette().color(QPalette.ColorRole.Highlight))

    @property
    def inactive_color(self) -> QColor:
        return QColor(self.palette().color(QPalette.ColorRole.Text))

    def row_geometry(self) -> tuple[tuple[int, ...], float, int]:
        """Font variants, largest scale and background padding that size timed rows."""
        if self.document is not None and self.document.lines:
            return self._styled_geometry
        return (0,), 1.0, 0

    @staticmethod
    def _line_state(row: int, current: int) -> int:
        if current < 0 or row > current:
            return AFTER
        return CURRENT if row == current else BEFORE

    def _line_target(self, row: int, current: int) -> tuple[float, float, float]:
        if current < 0:
            target = (0.8, 0.5, 0.0)
        else:
            distance = abs(row - current)
            if distance == 0:
                target = (1.0, 1.0, 1.0)
            elif distance == 1:
                target = (0.88, 0.6, 0.0)
            else:
                target = (0.8, max(0.2, 0.38 - 0.08 * (distance - 2)), 0.0)
        look = self.looks[self._line_state(row, current)]
        if look.scale is None and look.opacity is None:
            return target
        return (
            target[0] if look.scale is None else look.scale,
            target[1] if look.opacity is None else look.opacity,
            target[2],
        )

    @staticmethod
    def _blend(
        old: tuple[float, float, float], new: tuple[float, float, float], fraction: float
    ) -> tuple[float, float, float]:
        return (
            old[0] + (new[0] - old[0]) * fraction,
            old[1] + (new[1] - old[1]) * fraction,
            old[2] + (new[2] - old[2]) * fraction,
        )

    def _line_start(self, row: int) -> tuple[float, float, float, float, int]:
        start = self._line_from.get(row)
        if start is not None:
            return start
        return (
            self._line_far_before
            if 0 <= self._line_from_current and row < self._line_from_current
            else self._line_far_from
        )

    def line_appearance(self, row: int) -> tuple[float, float, float]:
        if self.document is None or not self.document.lines:
            return (1.0, 1.0, 0.0)
        if not self.browsing and self.current_line >= 0:
            distance = row - self.current_line
            if (self.options.lines_before >= 0 and distance < 0 and -distance > self.options.lines_before) or (
                self.options.lines_after >= 0 and distance > 0 and distance > self.options.lines_after
            ):
                return (0.8, 0.0, 0.0)
        target = self._line_target(row, self.current_line)
        flat = (
            self.options.inactive_opacity >= 0
            and row != self.current_line
            and self.looks[self._line_state(row, self.current_line)].opacity is None
        )
        if self._line_progress >= 1:
            if flat:
                return (target[0], self.options.inactive_opacity, target[2])
            return target
        start = self._line_start(row)
        blended = self._blend((start[0], start[1], start[2]), target, self._line_progress)
        if flat:
            return (blended[0], self.options.inactive_opacity, blended[2])
        return blended

    def _side_target(self, row: int, current: int) -> float:
        if current < 0 or row > current:
            return 1.0
        if row < current:
            return 0.0
        # The current line keeps the side it came from; its colour is the current colour.
        start = self._line_from.get(row)
        return start[3] if start is not None else 1.0

    def line_side(self, row: int) -> float:
        """0 for the before style, 1 for the after style, blended during a line transition."""
        side = self._side_target(row, self.current_line)
        if self._line_progress >= 1:
            return side
        start = self._line_start(row)[3]
        return start + (side - start) * self._line_progress

    def row_look(self, row: int) -> RowLook:
        scale, opacity, tint = self.line_appearance(row)
        if self.document is None or not self.document.lines:
            return RowLook(scale, opacity, tint, 1.0, -1, -1, 1.0)
        target = self._line_state(row, self.current_line)
        if self._line_progress >= 1:
            return RowLook(scale, opacity, tint, self._side_target(row, self.current_line), target, target, 1.0)
        return RowLook(scale, opacity, tint, self.line_side(row), self._line_start(row)[4], target, self._line_progress)

    beforeColor: QColor = _side_property("_side_colors", BEFORE)
    currentColor: QColor = _side_property("_side_colors", CURRENT)
    afterColor: QColor = _side_property("_side_colors", AFTER)
    beforeBackground: QColor = _side_property("_side_backgrounds", BEFORE)
    currentBackground: QColor = _side_property("_side_backgrounds", CURRENT)
    afterBackground: QColor = _side_property("_side_backgrounds", AFTER)

    def _get_glowColor(self) -> QColor:
        return QColor(self._glow_color)

    def _set_glowColor(self, value: QColor) -> None:
        self._glow_color = QColor(value)
        self.restyle()

    glowColor: QColor = pyqtProperty(QColor, _get_glowColor, _set_glowColor)

    def side_color(self, state: int) -> QColor | None:
        color = self._side_colors[state]
        return QColor(color) if color.isValid() else None

    def side_background(self, state: int) -> QColor | None:
        color = self._side_backgrounds[state]
        return QColor(color) if color.isValid() else None

    def _resolve_geometry(self) -> tuple[tuple[int, ...], float, int]:
        style_scales = [look.scale for look in self.looks if look.scale is not None]
        has_background = any(color.isValid() for color in self._side_backgrounds)
        return (
            tuple(sorted({look.variant for look in self.looks})),
            max([1.0, *style_scales]),
            round(self.options.style.background_padding * self.scale) if has_background else 0,
        )

    def restyle(self) -> None:
        """Apply colours set from the stylesheet; backgrounds can change the row padding."""
        geometry = self._resolve_geometry()
        self.delegate.glows.clear()
        if geometry != self._styled_geometry:
            self._styled_geometry = geometry
            self.delegate.reset()
            self.scheduleDelayedItemsLayout()
        self.canvas.update()

    def background_color(self, look: RowLook) -> QColor | None:
        before, current, after = (self.side_background(state) for state in (BEFORE, CURRENT, AFTER))
        return mix_optional(mix_optional(before, after, look.side), current, look.tint)

    def glow_extent(self) -> int:
        glow = self.options.glow
        if not glow.enabled:
            return 0
        return math.ceil(glow.radius * self.scale * 1.5 * self._styled_geometry[1]) + 1

    def _glow_active(self) -> bool:
        glow = self.options.glow
        return (
            glow.enabled
            and glow.radius > 0
            and glow.strength > 0
            and self.document is not None
            and bool(self.document.lines)
        )

    def _update_row(self, row: int) -> None:
        if 0 <= row < len(self.rows.texts):
            extent = self.glow_extent()
            rect = self.visualRect(self.rows.index(row + 1))
            self.canvas.update(rect.adjusted(-extent, -extent, extent, extent))

    def _paint_glow(self, painter: QPainter, area: QRect) -> None:
        rows = {self.current_line} if self.current_line >= 0 else set[int]()
        if self._line_progress < 1:
            rows.update(row for row, start in self._line_from.items() if start[2] > 0)
        extent = self.glow_extent()
        strength = self.options.glow.strength
        color = QColor(self._glow_color) if self._glow_color.isValid() else None
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for row in sorted(rows):
            if not 0 <= row < len(self.rows.texts):
                continue
            look = self.row_look(row)
            ink = color if color is not None else self.delegate.state_colors()[CURRENT]
            amount = strength * look.tint * look.opacity * ink.alphaF()
            rect = self.visualRect(self.rows.index(row + 1))
            if amount <= 0 or not rect.adjusted(-extent, -extent, extent, extent).intersects(area):
                continue
            variant = self.looks[look.target].variant
            layout = self.delegate.layout_for(row, variant)
            image, halo = self.delegate.glow_for(row, variant, layout, ink)
            if image.isNull():
                continue
            center, origin = self.delegate.placement(rect, layout)
            segments = self.sweep_segments(row, variant) if self.options.glow.target == "sung" else None
            painter.save()
            painter.translate(center)
            painter.scale(look.scale, look.scale)
            while amount > 0:
                painter.setOpacity(min(1.0, amount))
                if segments is None:
                    painter.drawImage(halo.translated(origin), image, QRectF(image.rect()))
                else:
                    region = self.delegate.sweep_region(layout)
                    mask = self.delegate.sung_mask(
                        segments, region, self.canvas.devicePixelRatioF() * max(1.0, look.scale)
                    )
                    self.delegate.draw_masked(
                        painter, origin, region, mask, lambda layer: layer.drawImage(halo, image, QRectF(image.rect()))
                    )
                amount -= 1.0
            painter.restore()

    def paintEvent(self, e: QPaintEvent | None) -> None:
        # One playhead reading per paint keeps the glow and text sweep aligned.
        self._paint_position = self.playhead.position() if self._sweep_enabled else None
        try:
            if e is not None and self._glow_active():
                # Halos paint beneath every row and outside the per-row clip.
                painter = QPainter(self.canvas)
                self._paint_glow(painter, e.rect())
                painter.end()
            super().paintEvent(e)
        finally:
            self._paint_position = None

    def _set_line_progress(self, value: object) -> None:
        if isinstance(value, int | float):
            self._line_progress = float(value)
            self.canvas.update()

    def finish_line_motion(self) -> None:
        self._line_motion.stop()
        self._line_from.clear()
        self._line_from_current = -1
        self._set_line_progress(1.0)

    def _snapshot(self, row: int) -> tuple[float, float, float, float, int]:
        scale, opacity, tint = self.line_appearance(row)
        look = self.row_look(row) if 0 <= row < len(self.rows.texts) else None
        if look is None:
            side = self._side_target(row, self.current_line)
            return (scale, opacity, tint, side, self._line_state(row, self.current_line))
        return (scale, opacity, tint, look.side, look.target)

    def _transition_line(self, current: int) -> None:
        if not self.accept_input or not self.isVisible():
            self.current_line = current
            self.finish_line_motion()
            return
        # Only the two line neighborhoods differ from the far-row appearance.
        rows = {
            row
            for index in (self.current_line, current)
            if index >= 0
            for row in range(max(0, index - 4), min(len(self.rows.texts), index + 5))
        }
        rows.update(
            row for row in self._line_from if self.visualRect(self.rows.index(row + 1)).intersects(self.canvas.rect())
        )
        starts = {row: self._snapshot(row) for row in rows}
        far = self._snapshot(len(self.rows.texts) + 4)
        far_before = self._snapshot(-5)
        previous = self.current_line
        if previous in starts:
            # The outgoing line fades from the current colour towards its new side only.
            scale, opacity, tint, _, state = starts[previous]
            starts[previous] = (scale, opacity, tint, self._side_target(previous, current), state)
        self._line_motion.stop()
        self.current_line = current
        self._line_from, self._line_far_from, self._line_far_before = starts, far, far_before
        self._line_from_current = previous
        self._set_line_progress(0.0)
        self._line_motion.start()

    def _range_changed(self, minimum: int, maximum: int) -> None:
        if self._restore_scroll is not None:
            self._apply_restore()
        if self.accept_input and not self.browsing:
            self._layout_follow.start(0)

    def _apply_restore(self) -> None:
        target = self._restore_scroll
        if target is None:
            return
        bar = self.scroll_bar
        bar.setValue(min(target, bar.maximum()))
        if bar.maximum() >= target:
            self._restore_scroll = None

    def _active_now(self) -> bool:
        document, position, current = self.document, self.position_ms, self.current_line
        if document is None or not document.lines or position is None or not 0 <= current < len(document.lines):
            return False
        end = document.lines[current].end_ms
        return end is None or position < end

    def set_document(self, document: LyricsDocument | None, *, replace: bool = False) -> None:
        if document is self.document:
            return
        if replace and document is not None and document.lines and self.document is not None and self.document.lines:
            self._replace_document(document)
            return
        self.cancel_interaction()
        self.finish_line_motion()
        self.document = document
        self.current_line = -1
        self.browsing = False
        self._restore_scroll = None
        self._settle_layout = False
        self._return.stop()
        self.delegate.reset()
        self.rows.replace(document)
        if self.accept_input and document is not None:
            self._layout_follow.start(0)

    def _replace_document(self, document: LyricsDocument) -> None:
        """Swap in a better document for the same track without a visible reset."""
        value = self.scroll_bar.value()
        self._pressed = None
        self.finish_line_motion()
        self.document = document
        position = self.position_ms
        self.current_line = document.line_at(position) if position is not None else -1
        self._current_active = self._active_now()
        self.delegate.reset()
        self.rows.replace(document)
        cast(Any, self).doItemsLayout()  # Public runtime QListView method absent from installed stubs.
        if self.browsing:
            self._restore_scroll = value
            self._apply_restore()
        else:
            self._settle_layout = True
            self.follow(instant=True)

    def set_position(
        self,
        position_ms: int | None,
        identity: tuple[str, int] | None,
        *,
        playing: bool = False,
        rate: float = 1.0,
    ) -> None:
        if identity != self.identity:
            self.cancel_interaction()
        self.identity, self.position_ms = identity, position_ms
        self.playhead.sample(position_ms, identity, playing, rate)
        current = self.document.line_at(position_ms) if self.document and position_ms is not None else -1
        if current != self.current_line:
            self._settle_layout = False
            if not self.browsing and self.follow(current):
                self.current_line = current
                self.finish_line_motion()
            else:
                self._transition_line(current)
            self._current_active = self._active_now()
            self._sync_sweep()
            return
        self._sync_sweep()
        # Within a line only the current row can change: word colours, or the
        # line colour once playback passes the line's end.
        document = self.document
        if document is None or not document.lines or current < 0:
            return
        active = self._active_now()
        if document.lines[current].words or active != self._current_active:
            self._current_active = active
            self._update_row(current)

    def _follow_after_layout(self) -> None:
        if not self.browsing:
            self.follow(instant=self._settle_layout)

    def browse(self) -> None:
        self.browsing = True
        self._restore_scroll = None
        self._settle_layout = False
        self._return.start()
        if self._scroll_motion is not None:
            self._scroll_motion.stop()

    def follow(self, line: int | None = None, *, instant: bool = False) -> bool:
        if self._gesture_start is not None or self.scroll_bar.isSliderDown():
            self._return.start()
            return False
        self.browsing = False
        self._restore_scroll = None
        self._return.stop()
        if self.document is None or not self.document.lines:
            return False
        index = self.rows.index(max(0, self.current_line if line is None else line) + 1)
        rect = self.visualRect(index)
        target = (
            self.scroll_bar.value() + rect.center().y() - round(self.canvas.height() * self.options.center_position)
        )
        bar = self.scroll_bar
        target = max(bar.minimum(), min(bar.maximum(), target))
        motion = self._scroll_motion
        if target == bar.value() or instant:
            if motion is not None:
                motion.stop()
            self._scroll_motion = None
            bar.setValue(target)
            return False
        if motion is not None and motion.state() == QPropertyAnimation.State.Running and motion.endValue() == target:
            return True
        self._scroll_motion = animate(
            bar,
            "value",
            target,
            self.options.animation_duration_ms,
            QEasingCurve.Type.OutCubic,
        )
        return self._scroll_motion.state() == QPropertyAnimation.State.Running

    def cancel_interaction(self) -> None:
        self._pressed = None
        self._gesture_start = None
        self._dragging = False
        self._return.stop()
        self._layout_follow.stop()
        if self._scroll_motion is not None:
            self._scroll_motion.stop()

    def focusOutEvent(self, e: QFocusEvent | None) -> None:
        self.cancel_interaction()
        if self.accept_input and self.isVisible():
            if self.browsing:
                self._return.start()
            else:
                self.follow()
        super().focusOutEvent(e)

    def hideEvent(self, a0: QHideEvent | None) -> None:
        self.finish_line_motion()
        self.cancel_interaction()
        self._sweep_frames.stop()
        super().hideEvent(a0)

    def resizeEvent(self, e: QResizeEvent | None) -> None:
        self.delegate.reset()
        super().resizeEvent(e)
        if self.accept_input:
            self._layout_follow.start(0)

    def changeEvent(self, a0: QEvent | None) -> None:
        if a0 is not None and a0.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            if hasattr(self, "delegate"):
                self.delegate.reset()
        super().changeEvent(a0)
        if hasattr(self, "_layout_follow") and self.accept_input:
            self._layout_follow.start(0)

    def wheelEvent(self, e: QWheelEvent | None) -> None:
        if e is None or not self.accept_input:
            return
        self.browse()
        delta = e.pixelDelta().y() or round(e.angleDelta().y() / 120 * 54 * self.scale)
        bar = self.scroll_bar
        self._scroll_motion = animate(
            bar,
            "value",
            max(bar.minimum(), min(bar.maximum(), bar.value() - delta)),
            self.options.animation_duration_ms,
        )
        e.accept()

    def _capture(self, point: QPoint, row: int) -> None:
        self._gesture_start = point
        self._press_scroll = self.scroll_bar.value()
        self._dragging = False
        if self.accept_input and self.identity is not None and self.document and 0 <= row < len(self.document.lines):
            self._pressed = (point, row, self.document, self.identity)

    def mousePressEvent(self, e: QMouseEvent | None) -> None:
        if e is None or not self.accept_input:
            return
        if e.button() == Qt.MouseButton.RightButton:
            self.cancel_interaction()
            self.follow()
            e.accept()
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self._capture(e.position().toPoint(), self.indexAt(e.position().toPoint()).row() - 1)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent | None) -> None:
        if e is not None and self._gesture_start is not None:
            delta = e.position().toPoint() - self._gesture_start
            if self._dragging or delta.manhattanLength() > round(self.options.drag_threshold * self.scale):
                self._dragging = True
                self.browse()
                self.scroll_bar.setValue(self._press_scroll - delta.y())
                e.accept()
                return
        super().mouseMoveEvent(e)

    def _release(self) -> None:
        captured, self._pressed = self._pressed, None
        self._gesture_start = None
        if (
            captured is not None
            and not self._dragging
            and self.accept_input
            and self.isVisible()
            and self.isEnabled()
            and captured[2] is self.document
            and captured[3] == self.identity
        ):
            self.seek_requested.emit(captured[2].lines[captured[1]].start_ms / 1000, captured[3])
        if self._dragging:
            self._return.start()
        self._dragging = False

    def mouseReleaseEvent(self, e: QMouseEvent | None) -> None:
        if e is not None and e.button() == Qt.MouseButton.LeftButton:
            if self._gesture_start is not None and (
                e.position().toPoint() - self._gesture_start
            ).manhattanLength() > round(self.options.drag_threshold * self.scale):
                self._dragging = True
            self._release()
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e: QKeyEvent | None) -> None:
        if e is None or not self.accept_input:
            return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not e.isAutoRepeat():
                self._capture(QPoint(), self.currentIndex().row() - 1)
            e.accept()
            return
        if e.key() in (
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
            Qt.Key.Key_PageUp,
            Qt.Key.Key_PageDown,
            Qt.Key.Key_Home,
            Qt.Key.Key_End,
        ):
            self.browse()
        super().keyPressEvent(e)

    def keyReleaseEvent(self, a0: QKeyEvent | None) -> None:
        e = a0
        if e is not None and e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not e.isAutoRepeat():
                self._release()
            e.accept()
            return
        super().keyReleaseEvent(e)
