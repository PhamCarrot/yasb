"""Audio controls for the Media V2 popup."""

from __future__ import annotations

from typing import Literal

from PyQt6.QtCore import QEvent, QPoint, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QHideEvent,
    QIcon,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPen,
    QPixmap,
    QShowEvent,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QStyle,
    QStyleOptionSlider,
    QStylePainter,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from core.widgets.services.media.equalizer_apo import EqualizerApoController
from core.widgets.yasb.media_v2_components import CancellableSlider, MediaButton, identify
from core.widgets.yasb.media_v2_motion import RevealEffect


class AudioActionButton(MediaButton):
    def __init__(
        self, parent: QWidget, scale: float, glyph: Literal["headphones", "stop", "reset"], *classes: str
    ) -> None:
        super().__init__(parent, *classes)
        self._glyph = glyph
        self.setIconSize(QSize(round(14 * scale), round(14 * scale)))
        self._paint_icon()

    def set_glyph(self, glyph: Literal["headphones", "stop", "reset"]) -> None:
        if glyph != self._glyph:
            self._glyph = glyph
            self._paint_icon()

    def _paint_icon(self) -> None:
        pixmap = QPixmap(48, 48)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(3, 3)
        ink = self.palette().color(QPalette.ColorRole.ButtonText)
        if self._glyph == "stop":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ink)
            painter.drawRoundedRect(QRectF(3, 3, 10, 10), 1.3, 1.3)
        else:
            painter.setPen(QPen(ink, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            if self._glyph == "headphones":
                painter.drawArc(QRectF(2.5, 2.5, 11, 11), 0, 180 * 16)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(ink)
                for x in (2.2, 10.8):
                    painter.drawRoundedRect(QRectF(x, 7.8, 3, 5.7), 1, 1)
            else:
                painter.drawArc(QRectF(2.7, 2.7, 10.6, 10.6), 50 * 16, 300 * 16)
                painter.drawLine(QPointF(12.6, 4.5), QPointF(12.6, 1.8))
                painter.drawLine(QPointF(12.6, 4.5), QPointF(9.9, 4.5))
        painter.end()
        self.setIcon(QIcon(pixmap))

    def changeEvent(self, e: QEvent | None) -> None:
        super().changeEvent(e)
        if (
            e is not None
            and e.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange)
            and hasattr(self, "_glyph")
        ):
            self._paint_icon()


class AudioSwitch(QCheckBox):
    """Native checkbox input/accessibility with a presentation-only switch."""

    def __init__(self, text: str, scale: float, parent: QWidget, *, compact: bool = False) -> None:
        super().__init__(text, parent)
        self.scale = scale
        self.compact = compact
        self.setMinimumHeight(round((16 if compact else 24) * scale))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def hitButton(self, pos: QPoint) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ink = self.palette().color(QPalette.ColorRole.WindowText)
        if not self.isEnabled():
            ink.setAlphaF(0.45)
        painter.setPen(ink)
        knob = round((16 if self.compact else 24) * self.scale)
        width = round(knob * 1.84)
        top = (self.height() - knob) / 2 if self.compact else self.height() - knob
        track = QRectF(self.width() - width, top, width, knob)
        title = self.rect().adjusted(0, 0, -width - round(8 * self.scale), 0) if self.compact else self.rect()
        painter.drawText(
            title, Qt.AlignmentFlag.AlignVCenter if self.compact else Qt.AlignmentFlag.AlignTop, self.text()
        )
        accent = self.palette().color(QPalette.ColorRole.Highlight) if self.isChecked() else QColor("#45475a")
        if not self.isEnabled():
            accent.setAlphaF(0.45)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(track, knob / 2, knob / 2)
        diameter = knob * 0.72
        x = track.right() - diameter - knob * 0.14 if self.isChecked() else track.left() + knob * 0.14
        painter.setBrush(ink)
        painter.drawEllipse(QRectF(x, track.top() + knob * 0.14, diameter, diameter))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(ink)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)


class BalanceSlider(CancellableSlider):
    def paintEvent(self, ev: QPaintEvent | None) -> None:
        style = self.style()
        if ev is None or style is None:
            return
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        control = QStyle.ComplexControl.CC_Slider
        groove = QRectF(style.subControlRect(control, option, QStyle.SubControl.SC_SliderGroove, self))
        handle = style.subControlRect(control, option, QStyle.SubControl.SC_SliderHandle, self)
        painter = QStylePainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        option.subControls = QStyle.SubControl.SC_SliderGroove
        painter.drawComplexControl(control, option)
        if self.value() != 0 and handle.isValid():
            center, thumb = groove.center().x(), QRectF(handle).center().x()
            clip = QPainterPath()
            clip.addRoundedRect(groove, groove.height() / 2, groove.height() / 2)
            painter.save()
            painter.setClipPath(clip)
            color = self.palette().color(QPalette.ColorRole.Highlight)
            color.setAlphaF(0.65)
            painter.fillRect(QRectF(min(center, thumb), groove.top(), abs(thumb - center), groove.height()), color)
            painter.restore()
        option.subControls = QStyle.SubControl.SC_SliderHandle
        painter.drawComplexControl(control, option)
        if self.hasFocus():
            focus = option.rect.adjusted(1, 1, -1, -1)
            painter.setPen(self.palette().color(QPalette.ColorRole.Highlight))
            painter.drawRoundedRect(focus, 5, 5)


class BalanceScale(QFrame):
    """Nine presentation ticks behind the existing captured-input slider."""

    def __init__(self, scale: float, parent: QWidget) -> None:
        super().__init__(parent)
        self.scale = scale
        self.setFixedHeight(round(45 * scale))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.slider = BalanceSlider(Qt.Orientation.Horizontal, self)
        layout.addWidget(self.slider)
        self.dim = QGraphicsOpacityEffect(self)
        self.dim.setOpacity(1)
        self.dim.setEnabled(False)
        self.setGraphicsEffect(self.dim)
        self._muted = False
        self._fade = QPropertyAnimation(self.dim, b"opacity", self)
        self._fade.setDuration(150)
        self._fade.finished.connect(self._settle_opacity)

    def set_muted(self, muted: bool) -> None:
        if muted == self._muted:
            return
        self._muted = muted
        opacity = 0.45 if muted else 1.0
        if self.isVisible():
            self.dim.setEnabled(True)
            self._fade.stop()
            self._fade.setStartValue(self.dim.opacity())
            self._fade.setEndValue(opacity)
            self._fade.start()
        else:
            self.dim.setOpacity(opacity)
            self.dim.setEnabled(muted)

    def _settle_opacity(self) -> None:
        self.dim.setEnabled(self._muted)

    def hideEvent(self, a0: QHideEvent | None) -> None:
        self._fade.stop()
        self.dim.setOpacity(0.45 if self._muted else 1.0)
        self._settle_opacity()
        super().hideEvent(a0)

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        super().paintEvent(a0)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        for index, height in enumerate((25, 18, 25, 18, 33, 18, 25, 18, 25)):
            width = (3 if index == 4 else 2) * self.scale
            x = 11 * self.scale + index * max(0, self.width() - 22 * self.scale) / 8
            ink = self.palette().color(QPalette.ColorRole.WindowText)
            ink.setAlphaF(0.7 if index == 4 else 0.32)
            painter.setBrush(ink)
            painter.drawRoundedRect(
                QRectF(x - width / 2, (self.height() - height * self.scale) / 2, width, height * self.scale),
                width / 2,
                width / 2,
            )


class MediaAudioPanel(QFrame):
    def __init__(self, controller: EqualizerApoController, scale: float, parent: QWidget) -> None:
        super().__init__(parent)
        identify(self, "media-audio", "media-audio")
        self.controller = controller
        self._syncing = False
        self._page_active = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, round(9 * scale), 0, 0)
        layout.setSpacing(round(8 * scale))
        self.balance_card = identify(QFrame(self), "media-audio-balance-card", "audio-card")
        self.balance_card.setFixedHeight(round(82 * scale))
        card = QVBoxLayout(self.balance_card)
        card.setContentsMargins(round(14 * scale), round(5 * scale), round(14 * scale), round(9 * scale))
        card.setSpacing(0)
        self.balance_scale = BalanceScale(scale, self.balance_card)
        card.addWidget(self.balance_scale)
        self.balance = identify(self.balance_scale.slider, "media-audio-balance", "audio-balance")
        self.balance.setRange(-100, 100)
        self.balance.setAccessibleName("Stereo balance")
        self.balance.setAccessibleDescription(
            "Left minus one hundred, center zero, right one hundred. Inactive in mono."
        )
        self.balance.valueChanged.connect(self._balance_changed)
        labels = QHBoxLayout()
        self.left_value = identify(QLabel("L  100%", self.balance_card), "media-audio-left-value", "audio-percentage")
        self.balance_value = identify(QLabel("Centered", self.balance_card), "media-audio-balance-value", "audio-value")
        self.balance_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.right_value = identify(QLabel("100%  R", self.balance_card), "media-audio-right-value", "audio-percentage")
        self.right_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for label in (self.left_value, self.balance_value, self.right_value):
            labels.addWidget(label, 1 if label is not self.balance_value else 2)
        card.addLayout(labels)
        layout.addWidget(self.balance_card)
        self.flags = QFrame(self)
        switches = QHBoxLayout(self.flags)
        switches.setContentsMargins(0, 0, 0, 0)
        switches.setSpacing(round(8 * scale))
        self.mono = AudioSwitch("Mono audio", scale, self.flags)
        self.mono.setObjectName("media-audio-mono")
        self.swap = AudioSwitch("Swap L/R", scale, self.flags)
        self.swap.setObjectName("media-audio-swap")
        self.mono.toggled.connect(self._mono_changed)
        self.swap.toggled.connect(self._swap_changed)
        for switch in (self.mono, self.swap):
            flag = identify(QFrame(self.flags), "media-audio-flag-" + switch.objectName(), "audio-card")
            flag.setFixedHeight(round(54 * scale))
            row = QHBoxLayout(flag)
            row.setContentsMargins(round(14 * scale), round(7 * scale), round(14 * scale), round(7 * scale))
            row.addWidget(switch)
            switches.addWidget(flag, 1)
        layout.addWidget(self.flags)
        self.dynamics_card = identify(QFrame(self), "media-audio-dynamics-card", "audio-card")
        self.dynamics_card.setFixedHeight(round(46 * scale))
        dynamics_row = QHBoxLayout(self.dynamics_card)
        dynamics_row.setContentsMargins(round(14 * scale), round(9 * scale), round(14 * scale), round(9 * scale))
        dynamics_row.addWidget(QLabel("Dynamic range", self.dynamics_card), 1)
        self.dynamics = identify(QTabBar(self.dynamics_card), "media-audio-dynamics", "audio-dynamics")
        self.dynamics.setAccessibleName("Dynamics mode")
        self.dynamics.setFixedSize(round(210 * scale), round(28 * scale))
        self.dynamics.setExpanding(True)
        self.dynamics.setDrawBase(False)
        self.dynamics.setUsesScrollButtons(False)
        self.dynamics.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        for name in ("Off", "Balanced", "Night"):
            self.dynamics.addTab(name)
        self.dynamics.currentChanged.connect(self._dynamics_changed)
        dynamics_row.addWidget(self.dynamics)
        layout.addWidget(self.dynamics_card)
        # Reparented into the lower header by MediaSections; same state owner.
        self.adaptive = AudioSwitch("Dynamic", scale, self, compact=True)
        self.adaptive.setObjectName("media-audio-adaptive")
        self.adaptive.toggled.connect(self._adaptive_changed)
        self.adaptive.hide()
        self.intro = [
            RevealEffect(widget, delay, 560, offset=(0, round(14 * scale)))
            for widget, delay in ((self.balance_card, 0), (self.flags, 70), (self.dynamics_card, 150))
        ]
        self.detail = identify(QLabel(self), "media-audio-status", "audio-status")
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.detail)
        layout.addStretch(1)
        self.reset_button = AudioActionButton(self, scale, "reset", "reset", "audio-reset")
        self.reset_button.setObjectName("media-audio-reset")
        self.reset_button.setText("Reset")
        self.reset_button.setAccessibleName("Reset audio settings")
        self.reset_button.clicked.connect(self.reset)
        self._poll = QTimer(self)
        self._poll.setInterval(200)
        self._poll.timeout.connect(self.sync)
        controller.draft_changed.connect(self.sync)
        self.sync()

    def _mono_changed(self, value: bool) -> None:
        self._update(mono=value)

    def _swap_changed(self, value: bool) -> None:
        self._update(swap=value)

    def _dynamics_changed(self, value: int) -> None:
        self._update(dynamics=value)

    def _adaptive_changed(self, value: bool) -> None:
        self._update(adaptive=value)

    def _balance_changed(self, value: int) -> None:
        self._update(balance=value / 100)

    def _update(self, **changes: object) -> None:
        if not self._syncing and not self.controller.update_audio(**changes):
            self.sync()

    def reset(self) -> None:
        self._update(balance=0.0, mono=False, swap=False, dynamics=0)

    def set_active(self, active: bool, *, preserve_motion: bool = False) -> None:
        entering = active and not self._page_active
        self._page_active = active
        if not active:
            if not preserve_motion:
                for effect in self.intro:
                    effect.finish()
        elif entering and self.isVisible() and not preserve_motion:
            for effect in self.intro:
                effect.replay()
        self.sync()

    def sync(self) -> None:
        state = self.controller.audio_state
        available = self.controller.audio_available
        self._syncing = True
        tooltip = ""
        try:
            self.balance.setValue(round(state.balance * 100))
            amount = abs(state.balance)
            side = "right" if state.balance > 0 else "left"
            description = (
                "Centered"
                if amount < 0.005
                else f"{side.title()} only"
                if amount >= 0.995
                else f"Slightly {side} favored"
                if amount < 0.25
                else f"{side.title()} favored"
            )
            self.balance_value.setText(description)
            self.left_value.setText(f"L  {round((1 - max(0, state.balance)) * 100)}%")
            self.right_value.setText(f"{round((1 + min(0, state.balance)) * 100)}%  R")
            self.mono.setChecked(state.mono)
            self.swap.setChecked(state.swap)
            self.adaptive.setChecked(state.adaptive)
            self.dynamics.setCurrentIndex(state.dynamics)
            for widget in (self.mono, self.swap, self.adaptive, self.dynamics, self.reset_button):
                widget.setEnabled(available)
            self.balance.setEnabled(available and not state.mono)
            self.balance_scale.set_muted(not available or state.mono)
            dynamic_help = (
                "Learns a bounded correction from audio and retains the manual curve."
                if available
                else "Dynamic equalizer requires ready native audio processing. Graphic EQ does not support it."
            )
            self.adaptive.setToolTip(dynamic_help)
            self.adaptive.setAccessibleDescription(dynamic_help)
            if self.controller.restoring:
                text = (
                    "Saved settings unavailable. Use Retry."
                    if self.controller.write_failed
                    else "Loading saved audio settings…"
                )
            elif not available:
                text = "Audio processing requires the native processor."
            elif self.controller.write_failed:
                text = "Settings could not be saved."
            elif self.controller.persistence_pending:
                text = "Saving settings…"
            elif self.isVisible():
                observation = self.controller.native_observation
                text = (
                    ("Bypass confirmed" if state.bypass else "Processing frames confirmed")
                    if observation.processing
                    else "Saved; waiting for native processing"
                )
                tooltip = observation.detail
            else:
                text = "Saved"
            self.detail.setText(text)
            self.detail.setToolTip(tooltip)
            self.detail.setAccessibleName(text)
        finally:
            self._syncing = False

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        self.sync()
        self._poll.start()
        if self._page_active:
            for effect in self.intro:
                effect.replay()

    def hideEvent(self, a0: QHideEvent | None) -> None:
        for effect in self.intro:
            effect.finish()
        self._poll.stop()
        super().hideEvent(a0)
