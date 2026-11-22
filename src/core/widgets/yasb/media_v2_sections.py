"""Equalizer, Audio and Lyrics pages for the media popup."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import PyQt6.QtCore as QtCore
from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, QSize, Qt
from PyQt6.QtGui import QKeySequence, QResizeEvent, QShortcut, QWheelEvent
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractSlider,
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QScrollArea,
    QSizePolicy,
    QTabBar,
    QWidget,
)

from core.validation.widgets.yasb.media_v2 import MediaLyricsConfig, MediaV2AudioConfig
from core.widgets.yasb.media_v2_audio import MediaAudioPanel
from core.widgets.yasb.media_v2_components import CancellableSlider, identify
from core.widgets.yasb.media_v2_equalizer import EqualizerPanel
from core.widgets.yasb.media_v2_lyrics import MediaLyricsPanel
from core.widgets.yasb.media_v2_motion import FrameClock, RevealEffect, animate, settle

pyqtProperty: Callable[..., Any] = getattr(QtCore, "pyqtProperty")


class MediaPage(QScrollArea):
    def __init__(self, content: QWidget, index: int, scale: float, parent: QWidget) -> None:
        super().__init__(parent)
        identify(self, f"media-section-page-{index}", "media-section-page")
        self.scale = scale
        self.selected = index == 0
        self.overlay: QWidget | None = None
        self._offset = 0.0 if self.selected else 1.0
        self._opacity = 1.0 if self.selected else 0.0
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setWidget(content)
        # QScrollArea enables palette fills when installing its content.
        # Leave the album surface visible while retaining explicit QSS fills.
        content.setAutoFillBackground(False)
        viewport = self.viewport()
        assert viewport is not None
        viewport.setAutoFillBackground(False)
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self._set_opacity(self._opacity)

    def set_overlay(self, overlay: QWidget) -> None:
        self.overlay = overlay
        overlay.setParent(self.viewport())
        self._place_overlay()

    def _place_overlay(self) -> None:
        viewport = self.viewport()
        if self.overlay is not None and viewport is not None:
            self.overlay.setGeometry(viewport.rect())

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        self._place_overlay()

    def place(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            distance = parent.width() + round(24 * self.scale)
            self.setGeometry(round(self._offset * distance), 0, parent.width(), parent.height())

    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, value: float) -> None:
        self._offset = value
        self.place()

    offset: float = pyqtProperty(float, _get_offset, _set_offset)

    def _get_opacity(self) -> float:
        return self._opacity

    def _set_opacity(self, value: float) -> None:
        self._opacity = max(0.0, min(1.0, value))
        self.opacity_effect.setOpacity(self._opacity)
        self.opacity_effect.setEnabled((self.selected or self._opacity > 0) and self._opacity < 1)
        self.setVisible(self._opacity > 0 or self.selected)

    opacity: float = pyqtProperty(float, _get_opacity, _set_opacity)


class PageViewport(QFrame):
    def __init__(self, scale: float, parent: QWidget) -> None:
        super().__init__(parent)
        identify(self, "media-section-viewport", "media-section-viewport")
        self.scale = scale
        # Keep scrollable content reachable when custom styles need more room.
        self.setMinimumHeight(round(100 * scale))
        self.setMaximumHeight(round(235 * scale))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.pages: list[MediaPage] = []

    def sizeHint(self) -> QSize:
        return QSize(0, round(235 * self.scale))

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        for page in self.pages:
            page.place()


class HeaderSlot(QFrame):
    """One clipped action envelope; existing buttons retain their input/state."""

    def __init__(self, parent: QWidget, scale: float, *, fade: bool = False) -> None:
        super().__init__(parent)
        self.scale = scale
        self._extent = 0.0
        self.widgets: list[QWidget] = []
        self.content_width = 1
        self._presented: QWidget | None = None
        self.alpha = QGraphicsOpacityEffect(self) if fade else None
        if self.alpha is not None:
            self.setGraphicsEffect(self.alpha)
        self.setFixedHeight(round(26 * scale))
        self.setFixedWidth(0)

    def add(self, widget: QWidget) -> None:
        widget.setParent(self)
        widget.setMinimumWidth(0)
        widget.setMaximumWidth(16777215)
        self.widgets.append(widget)

    def present(
        self, widget: QWidget | None, width: int, duration: int, motion: bool = True, *, reflow: bool = False
    ) -> None:
        content_width = max(1, width)
        same_widget = self._presented is widget
        if motion and same_widget and (widget is None or self.content_width == content_width):
            return
        animation = cast(dict[str, QPropertyAnimation], getattr(self, "_motion", {})).get("extent")
        if motion and same_widget and reflow:
            motion = animation is not None and animation.state() == QPropertyAnimation.State.Running
            if animation is not None and motion:
                duration = max(1, animation.duration() - animation.currentTime())
        self._presented = widget
        self.setEnabled(widget is not None)
        if widget is not None:
            self.content_width = content_width
            for child in self.widgets:
                child.setVisible(child is widget)
        target = float(width if widget is not None else 0)
        if motion and self.isVisible():
            animate(self, "extent", target, duration, QEasingCurve.Type.OutCubic)
        else:
            if animation is not None:
                animation.stop()
                animation.setEndValue(target)
            self.extent = target
        self._place()

    def _get_extent(self) -> float:
        return self._extent

    def _set_extent(self, value: float) -> None:
        self._extent = value
        if value <= 0 and self._presented is None:
            for child in self.widgets:
                child.hide()
        self.setFixedWidth(max(0, round(value)))
        if self.alpha is not None:
            ratio = max(0.0, min(1.0, value / self.content_width))
            self.alpha.setOpacity(ratio)
            self.alpha.setEnabled(ratio < 1)
        self._place()

    extent: float = pyqtProperty(float, _get_extent, _set_extent)

    def _place(self) -> None:
        for widget in self.widgets:
            # Sliding the preset from the right follows its shrinking envelope.
            widget.setGeometry(max(0, self.content_width - self.width()), 0, self.content_width, self.height())

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        self._place()


class SectionTabs(QTabBar):
    def __init__(self, scale: float, parent: QWidget) -> None:
        super().__init__(parent)
        self.scale = scale

    def sizeHint(self) -> QSize:
        return QSize(round(224 * self.scale), round(26 * self.scale))

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        if event is not None:
            event.accept()


class MediaSections(QObject):
    def __init__(
        self,
        panel: EqualizerPanel,
        scale: float,
        lyrics_options: MediaLyricsConfig | None = None,
        *,
        clock: FrameClock | None = None,
        audio_options: MediaV2AudioConfig | None = None,
    ) -> None:
        super().__init__(panel)
        self.panel = panel
        self.active_index = 0
        self._accept_input = True
        self._policies: list[dict[QWidget, Qt.FocusPolicy]] = []
        self._membership: dict[QObject, int] = {}
        self.tabs = identify(SectionTabs(scale, panel.header), "media-section-tabs", "media-section-tabs")
        self.tabs.setAccessibleName("Media sections")
        self.tabs.addTab("Equalizer")
        self.tabs.addTab("Audio")
        self.tabs.addTab("Lyrics")
        self.tabs.setExpanding(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.setDrawBase(False)
        self.tabs.setUsesScrollButtons(False)
        self.tabs.setFixedSize(self.tabs.sizeHint())
        self.tabs.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        panel.title.hide()
        panel.header_layout.insertWidget(0, self.tabs)
        panel.header_layout.insertStretch(panel.header_layout.indexOf(panel.apply_button), 1)
        panel.main_layout.removeWidget(panel.body)
        self.viewport = PageViewport(scale, panel)
        panel.main_layout.addWidget(self.viewport)
        self.audio = MediaAudioPanel(panel.apo, scale, self.viewport, audio_options, clock=clock)
        self.lyrics = MediaLyricsPanel(scale, self.viewport, options=lyrics_options, clock=clock)
        self.pages = [
            MediaPage(panel.body, 0, scale, self.viewport),
            MediaPage(self.audio, 1, scale, self.viewport),
            MediaPage(self.lyrics, 2, scale, self.viewport),
        ]
        self.viewport.pages = self.pages
        self.pages[0].set_overlay(panel.adaptive_overlay)
        for index, page in enumerate(self.pages):
            widgets = [page, *page.findChildren(QWidget)]
            self._policies.append({widget: widget.focusPolicy() for widget in widgets})
            for widget in widgets:
                self._membership[widget] = index
                widget.installEventFilter(self)
            self._set_interactive(index, index == 0)
            page.place()
        panel.sync_effect_overlay()
        self.audio.reset_button.setParent(panel.header)
        self.audio.reset_button.setFixedSize(round(70 * scale), round(26 * scale))
        self.audio.reset_button.hide()
        self.audio.adaptive.setParent(panel.header)
        policy = self._policies[1].pop(self.audio.adaptive)
        self._policies[0][self.audio.adaptive] = policy
        self._membership[self.audio.adaptive] = 0
        self.audio.adaptive.setFocusPolicy(policy)
        self.audio.adaptive.setFixedSize(round(108 * scale), round(26 * scale))
        self.audio.adaptive.show()
        self.lyrics.retry_button.setParent(panel.header)
        self.lyrics.retry_button.setFixedSize(round(54 * scale), round(26 * scale))
        self.lyrics.retry_button.hide()
        for widget in (panel.status, panel.current, panel.apply_button):
            panel.header_layout.removeWidget(widget)
        panel.status.hide()
        panel.status.setProperty("compact_header", True)
        panel.header_layout.setSpacing(round(6 * scale))
        panel.header_layout.addWidget(self.audio.adaptive)
        panel.apply_button.setFixedSize(round(68 * scale), round(26 * scale))
        self.audio.reset_button.setFixedWidth(round(84 * scale))
        self.audio.adaptive.setAccessibleName("Dynamic equalizer")
        self.action_slot = HeaderSlot(panel.header, scale)
        self.preset_slot = HeaderSlot(panel.header, scale, fade=True)
        for widget in (panel.apply_button, self.audio.reset_button):
            self.action_slot.add(widget)
        self.preset_slot.add(panel.current)
        panel.header_layout.addWidget(self.action_slot)
        panel.header_layout.addWidget(self.preset_slot)
        panel.header_layout.addWidget(self.lyrics.retry_button)
        self._header_scale = scale
        self._sync_header(motion=False)
        for index, controls in enumerate(
            (
                (panel.apply_button,),
                (self.audio.reset_button,),
                (self.lyrics.retry_button,),
            )
        ):
            for control in controls:
                self._membership[control] = index
                self._policies[index][control] = control.focusPolicy()
        panel.apo.draft_changed.connect(self._sync_header)
        panel.caption_changed.connect(lambda: self._sync_header(caption_changed=True))
        panel.header_changed.connect(self._sync_header)
        panel.intro[0] = RevealEffect(panel.header, 370, 710, offset=(0, round(12 * scale)))
        self._headers = (
            self.tabs,
            panel.apply_button,
            self.audio.reset_button,
            self.audio.adaptive,
            self.lyrics.retry_button,
        )
        for widget in self._headers:
            widget.installEventFilter(self)
        self.tabs.currentChanged.connect(self.select)
        self._next = QShortcut(QKeySequence("Ctrl+Tab"), panel)
        self._next.activated.connect(lambda: self.tabs.setCurrentIndex((self.active_index + 1) % len(self.pages)))
        self._previous = QShortcut(QKeySequence("Ctrl+Shift+Tab"), panel)
        self._previous.activated.connect(lambda: self.tabs.setCurrentIndex((self.active_index - 1) % len(self.pages)))

    def _sync_header(self, *, motion: bool = True, caption_changed: bool = False) -> None:
        scale = self._header_scale
        index = self.active_index
        button = (self.panel.apply_button, self.audio.reset_button, self.lyrics.retry_button)[index]
        minimum, padding = ((68, 26), (84, 46), (54, 26))[index]
        action_visible = index == 1 or (index == 0 and self.panel.apply_action_visible)
        width = (
            max(round(minimum * scale), button.fontMetrics().horizontalAdvance(button.text()) + round(padding * scale))
            if action_visible
            else 0
        )
        self.action_slot.present(button if action_visible else None, width, 400, motion)
        preset_width = self.panel.current.sizeHint().width()
        self.preset_slot.present(
            self.panel.current if index == 0 else None, preset_width, 400, motion, reflow=caption_changed
        )
        if index == 0 and caption_changed:
            # The rightmost slot keeps its previous origin until the header
            # relayouts. Place it before the new text can paint at that origin.
            self.panel.header_layout.activate()

    def _set_interactive(self, index: int, active: bool) -> None:
        self.pages[index].setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not active)
        # Scrollbars proxy focus to their owning view. Restore descendants
        # first so their NoFocus policy cannot overwrite the view's policy.
        for widget, policy in reversed(self._policies[index].items()):
            widget.setFocusPolicy(policy if active else Qt.FocusPolicy.NoFocus)

    def select(self, index: int) -> None:
        if not self._accept_input:
            blocked = self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(self.active_index)
            self.tabs.blockSignals(blocked)
            return
        if index == self.active_index or not 0 <= index < len(self.pages):
            return
        previous = self.active_index
        focused = QApplication.focusWidget()
        outgoing = self.pages[previous]
        if focused is not None and (
            outgoing is focused
            or outgoing.isAncestorOf(focused)
            or self.panel.apply_button is focused
            or self.audio.reset_button is focused
            or self.audio.adaptive is focused
            or focused is self.lyrics.retry_button
        ):
            self.tabs.setFocus(Qt.FocusReason.OtherFocusReason)
        self._cancel_gestures(previous)
        self.panel.set_page_active(index == 0, preserve_motion=True)
        self.active_index = index
        self.audio.adaptive.setVisible(index == 0)
        self.lyrics.retry_button.setVisible(index == 2)
        self.lyrics.set_active(index == 2)
        self.audio.set_active(index == 1)
        self._sync_header()
        for number, page in enumerate(self.pages):
            page.selected = number == index
            self._set_interactive(number, page.selected)
            target = 0.0 if page.selected else -1.0 if number < index else 1.0
            animate(page, "offset", target, 400, QEasingCurve.Type.OutQuart)
            animate(page, "opacity", 1.0 if page.selected else 0.0, 250, QEasingCurve.Type.OutCubic)

    def _cancel_gestures(self, index: int) -> None:
        # Cancel captured gestures before discard; emitting sliderReleased after
        # discard could otherwise recreate the just-abandoned EQ draft.
        outgoing = self.pages[index]
        if index == 2:
            self.lyrics.cancel_interaction()
        for widget in self._policies[index]:
            if isinstance(widget, CancellableSlider):
                widget.cancel_interaction()
            elif isinstance(widget, QAbstractSlider) and widget.isSliderDown():
                blocked = widget.blockSignals(True)
                widget.setSliderDown(False)
                widget.blockSignals(blocked)
            elif isinstance(widget, QAbstractButton):
                widget.setDown(False)
        grabber = QWidget.mouseGrabber()
        if grabber is not None and outgoing.isAncestorOf(grabber):
            grabber.releaseMouse()

    def suspend(self, *, preserve_motion: bool = False) -> None:
        self._accept_input = False
        self._next.setEnabled(False)
        self._previous.setEnabled(False)
        for index in range(len(self.pages)):
            self._set_interactive(index, False)
            self._cancel_gestures(index)
        self.panel.set_page_active(False, preserve_motion=preserve_motion)
        self.lyrics.set_active(False)
        self.audio.set_active(False)

    def resume(self, *, preserve_motion: bool = False) -> None:
        self._accept_input = True
        self._next.setEnabled(True)
        self._previous.setEnabled(True)
        for index in range(len(self.pages)):
            self._set_interactive(index, index == self.active_index)
        self.panel.set_page_active(self.active_index == 0, preserve_motion=preserve_motion)
        self.lyrics.set_active(self.active_index == 2)
        self.audio.set_active(self.active_index == 1)

    def finish(self) -> None:
        for slot in (self.action_slot, self.preset_slot):
            settle(slot)
        for page in self.pages:
            settle(page)

    def ensure_control_visible(self, widget: QWidget) -> None:
        page = self.pages[self.active_index]
        if page.isAncestorOf(widget):
            page.ensureWidgetVisible(widget, 0, 0)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        watched, event = a0, a1
        index = self._membership.get(watched) if watched is not None else None
        if event is not None and watched is self.panel.body and event.type() == QEvent.Type.Resize:
            self.panel.sync_effect_overlay()
        if event is not None and watched is self.pages[0] and event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
            self.panel.sync_effect_overlay()
        guarded = index is not None or watched in self._headers
        if (
            event is not None
            and guarded
            and (not self._accept_input or (index is not None and index != self.active_index))
        ):
            if event.type() == QEvent.Type.FocusIn:
                if self._accept_input:
                    self.tabs.setFocus(Qt.FocusReason.OtherFocusReason)
                elif isinstance(watched, QWidget):
                    watched.clearFocus()
                return True
            if event.type() in (
                QEvent.Type.KeyPress,
                QEvent.Type.KeyRelease,
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseButtonDblClick,
                QEvent.Type.MouseMove,
                QEvent.Type.Wheel,
            ):
                return True
        return super().eventFilter(watched, event)
