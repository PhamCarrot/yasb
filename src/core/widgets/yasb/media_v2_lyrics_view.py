"""Virtualized lyric text and captured input; no media or network ownership."""

from __future__ import annotations

from collections import OrderedDict

from PyQt6.QtCore import (
    QAbstractListModel,
    QEasingCurve,
    QEvent,
    QModelIndex,
    QPoint,
    QPointF,
    QPropertyAnimation,
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
    QKeyEvent,
    QMouseEvent,
    QPainter,
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
from core.widgets.yasb.media_v2_motion import animate


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
        self.layouts: OrderedDict[int, QTextLayout] = OrderedDict()
        self.heights: dict[int, int] = {}

    def reset(self) -> None:
        self.layouts.clear()
        self.heights.clear()

    def layout_for(self, row: int) -> QTextLayout:
        cached = self.layouts.get(row)
        if cached is not None:
            self.layouts.move_to_end(row)
            return cached
        font = self.view.font()
        parent = self.view.parentWidget()
        if parent is not None and font.pixelSize() == parent.font().pixelSize():
            # Older themes give the whole section a single small UI font.
            # Keep its face and honor a distinct row size when one is supplied.
            font.setPixelSize(max(font.pixelSize(), round(18 * self.view.scale)))
        layout = QTextLayout(self.view.rows.texts[row], font)
        layout.setCacheEnabled(True)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        option.setAlignment(self.view.text_alignment)
        layout.setTextOption(option)
        layout.beginLayout()
        height = 0.0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(
                max(1, self.view.canvas.width() - round(2 * self.view.options.margins.horizontal * self.view.scale))
            )
            line.setPosition(QPointF(0, height))
            height += line.height()
        layout.endLayout()
        self.heights[row] = max(round(self.view.options.line_height * self.view.scale), round(height)) + round(
            self.view.options.line_spacing * self.view.scale
        )
        while len(self.layouts) >= 64:
            self.layouts.popitem(last=False)
        self.layouts[row] = layout
        return layout

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        row = index.row() - 1
        if row < 0 or row >= len(self.view.rows.texts):
            ratio = self.view.options.center_position if row < 0 else 1.0 - self.view.options.center_position
            return QSize(1, max(0, round(self.view.canvas.height() * ratio - 15 * self.view.scale)))
        if row not in self.heights:
            self.layout_for(row)
        return QSize(max(1, self.view.canvas.width()), self.heights[row])

    def _line_color(self, row: int, tint: float | None) -> QColor:
        normal = self.view.inactive_color
        document, position = self.view.document, self.view.position_ms
        if document is None or not document.lines or position is None:
            return normal
        line = document.lines[row]
        active = row == self.view.current_line and (line.end_ms is None or position < line.end_ms)
        level = float(active) if tint is None or row == self.view.current_line and not active else tint
        if not level:
            return normal
        accent = self.view.active_color
        return QColor(
            round(normal.red() + (accent.red() - normal.red()) * level),
            round(normal.green() + (accent.green() - normal.green()) * level),
            round(normal.blue() + (accent.blue() - normal.blue()) * level),
            round(normal.alpha() + (accent.alpha() - normal.alpha()) * level),
        )

    def formats(self, row: int, tint: float | None = None) -> list[QTextLayout.FormatRange]:
        document = self.view.document
        if document is None:
            return []
        normal = self.view.inactive_color
        accent = self.view.active_color
        future = QColor(normal)
        future.setAlphaF(normal.alphaF() * 0.4)
        text = self.view.rows.texts[row]

        def span(start: int, length: int, color: QColor) -> QTextLayout.FormatRange:
            result = QTextLayout.FormatRange()
            result.start, result.length = start, length
            style = QTextCharFormat()
            style.setForeground(color)
            result.format = style
            return result

        length = len(text.encode("utf-16-le")) // 2
        if not document.lines or self.view.position_ms is None:
            return [span(0, length, normal)]
        line = document.lines[row]
        position = self.view.position_ms
        if line.words and row != self.view.current_line:
            return [span(0, length, normal)]
        if line.words:
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
                    span(offset, count, accent if active else normal if position >= word.start_ms else future)
                )
                offset += count
            return ranges
        return [span(0, length, self._line_color(row, tint))]

    def paint(self, painter: QPainter | None, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        row = index.row() - 1
        if painter is None or not 0 <= row < len(self.view.rows.texts):
            return
        layout = self.layout_for(row)
        painter.save()
        painter.setClipRect(option.rect)
        bounds = layout.boundingRect()
        height = bounds.height()
        top = option.rect.y() + max(
            0, (option.rect.height() - round(self.view.options.line_spacing * self.view.scale) - height) / 2
        )
        margin = round(self.view.options.margins.horizontal * self.view.scale)
        text_width = bounds.width()
        if self.view.options.alignment == "center":
            left = option.rect.x() + (option.rect.width() - text_width) / 2
            origin_x, draw_x = text_width / 2, -text_width / 2
        elif self.view.options.alignment == "right":
            left = option.rect.right() - margin - text_width
            origin_x, draw_x = text_width, -text_width
        else:
            left = option.rect.x() + margin
            origin_x, draw_x = 0, 0
        ratio, opacity, tint = self.view.line_appearance(row)
        painter.setOpacity(painter.opacity() * opacity)
        painter.translate(left + origin_x, top + height / 2)
        painter.scale(ratio, ratio)
        origin = QPointF(draw_x, -height / 2)
        document = self.view.document
        if document and document.lines and document.lines[row].words:
            layout.draw(painter, origin, self.formats(row, tint))
        else:
            painter.setPen(self._line_color(row, tint))
            layout.draw(painter, origin)
        painter.restore()


class LyricsView(QListView):
    seek_requested = pyqtSignal(float, object)

    def __init__(self, scale: float, parent: QWidget, options: MediaLyricsConfig | None = None) -> None:
        super().__init__(parent)
        identify(self, "media-lyrics-view", "media-lyrics-view")
        self.scale = scale
        self.options = options or MediaLyricsConfig()
        self.document: LyricsDocument | None = None
        self.position_ms: int | None = None
        self.identity: tuple[str, int] | None = None
        self.current_line = -1
        self.browsing = False
        self.accept_input = False
        self._gesture_start: QPoint | None = None
        self._pressed: tuple[QPoint, int, LyricsDocument, tuple[str, int]] | None = None
        self._press_scroll = 0
        self._dragging = False
        self._scroll_motion: QPropertyAnimation | None = None
        self._line_from: dict[int, tuple[float, float, float]] = {}
        self._line_far_from = (0.8, 0.5, 0.0)
        self._line_progress = 1.0
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
        palette = self.palette()
        if self.options.inactive_color is not None:
            palette.setColor(QPalette.ColorRole.Text, QColor(self.options.inactive_color))
        if self.options.active_color is not None:
            palette.setColor(QPalette.ColorRole.Highlight, QColor(self.options.active_color))
        self.setPalette(palette)
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
        self._line_motion = QVariantAnimation(self)
        self._line_motion.setDuration(self.options.animation_duration_ms)
        self._line_motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._line_motion.setStartValue(0.0)
        self._line_motion.setEndValue(1.0)
        self._line_motion.valueChanged.connect(self._set_line_progress)
        self._line_motion.finished.connect(self.finish_line_motion)

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

    @staticmethod
    def _line_target(row: int, current: int) -> tuple[float, float, float]:
        if current < 0:
            return (0.8, 0.5, 0.0)
        distance = abs(row - current)
        if distance == 0:
            return (1.0, 1.0, 1.0)
        if distance == 1:
            return (0.88, 0.6, 0.0)
        return (0.8, max(0.2, 0.38 - 0.08 * (distance - 2)), 0.0)

    @staticmethod
    def _blend(
        old: tuple[float, float, float], new: tuple[float, float, float], fraction: float
    ) -> tuple[float, float, float]:
        return (
            old[0] + (new[0] - old[0]) * fraction,
            old[1] + (new[1] - old[1]) * fraction,
            old[2] + (new[2] - old[2]) * fraction,
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
        if self._line_progress >= 1:
            if self.options.inactive_opacity >= 0 and row != self.current_line:
                return (target[0], self.options.inactive_opacity, target[2])
            return target
        blended = self._blend(self._line_from.get(row, self._line_far_from), target, self._line_progress)
        if self.options.inactive_opacity >= 0 and row != self.current_line:
            return (blended[0], self.options.inactive_opacity, blended[2])
        return blended

    def _set_line_progress(self, value: object) -> None:
        if isinstance(value, int | float):
            self._line_progress = float(value)
            self.canvas.update()

    def finish_line_motion(self) -> None:
        self._line_motion.stop()
        self._line_from.clear()
        self._set_line_progress(1.0)

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
        starts = {row: self.line_appearance(row) for row in rows}
        far = self.line_appearance(len(self.rows.texts) + 4)
        self._line_motion.stop()
        self.current_line = current
        self._line_from, self._line_far_from = starts, far
        self._set_line_progress(0.0)
        self._line_motion.start()

    def _range_changed(self, minimum: int, maximum: int) -> None:
        if self.accept_input and not self.browsing:
            self._layout_follow.start(0)

    def set_document(self, document: LyricsDocument | None) -> None:
        if document is self.document:
            return
        self.cancel_interaction()
        self.finish_line_motion()
        self.document = document
        self.current_line = -1
        self.browsing = False
        self._return.stop()
        self.delegate.reset()
        self.rows.replace(document)
        if self.accept_input and document is not None:
            self._layout_follow.start(0)

    def set_position(self, position_ms: int | None, identity: tuple[str, int] | None) -> None:
        if identity != self.identity:
            self.cancel_interaction()
        self.identity, self.position_ms = identity, position_ms
        current = self.document.line_at(position_ms) if self.document and position_ms is not None else -1
        if current != self.current_line:
            if not self.browsing and self.follow(current):
                self.current_line = current
                self.finish_line_motion()
            else:
                self._transition_line(current)
        self.canvas.update()

    def _follow_after_layout(self) -> None:
        if not self.browsing:
            self.follow()

    def browse(self) -> None:
        self.browsing = True
        self._return.start()
        if self._scroll_motion is not None:
            self._scroll_motion.stop()

    def follow(self, line: int | None = None) -> bool:
        if self._gesture_start is not None or self.scroll_bar.isSliderDown():
            self._return.start()
            return False
        self.browsing = False
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
        if target == bar.value():
            if motion is not None:
                motion.stop()
            self._scroll_motion = None
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
