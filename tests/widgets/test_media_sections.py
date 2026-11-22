# pyright: reportPrivateUsage=false

import time
from dataclasses import replace
from typing import Any, cast

import PyQt6.sip as sip
import pytest
from PyQt6.QtCore import QObject, QPoint, QPointF, QPropertyAnimation, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPalette, QPixmap, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QStyle, QStyleOptionSlider, QWidget

from core.widgets.services.media.audio_device import AudioOutputState
from core.widgets.services.media.equalizer_apo import EqualizerApoController
from core.widgets.services.media.lyrics import LyricsService
from core.widgets.services.media.model import MediaState, PlaybackState
from core.widgets.services.media.native_route import NativeAudioState, NativeObservation
from core.widgets.yasb.media_v2_audio import MediaAudioPanel
from core.widgets.yasb.media_v2_styles import media_section_fallbacks
from tests.widgets.test_media_lyrics_ui import Owner, snapshot
from tests.widgets.test_media_popup_geometry import make_popup

qt_test = cast(Any, QTest)  # PyQt6 6.10.2 namespace stub issue; same local driver as input tests.


def dispose(parent: QWidget, popup: Any) -> None:
    popup.hide()
    popup.equalizer.apo.shutdown()
    sip.delete(parent)


def test_switch_keeps_common_widgets_and_header_stationary(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        qapp.processEvents()
        common = (popup.art, popup.title, popup.progress, popup.controls, popup.selector)
        geometry = tuple(widget.geometry() for widget in common)
        header = popup.equalizer.header.geometry()
        outer = popup.size()
        popup.sections.tabs.setCurrentIndex(1)
        assert popup.sections.active_index == 1
        motions = cast(dict[str, QPropertyAnimation], getattr(popup.sections.pages[0], "_motion"))
        assert motions["offset"].duration() == 400 and motions["opacity"].duration() == 250
        motions["offset"].setCurrentTime(100)
        motions["opacity"].setCurrentTime(100)
        assert -1 < popup.sections.pages[0].offset < 0 and 0 < popup.sections.pages[0].opacity < 1
        assert popup.sections.pages[2].isHidden()
        popup.sections.finish()
        qapp.processEvents()
        assert common == (popup.art, popup.title, popup.progress, popup.controls, popup.selector)
        assert geometry == tuple(widget.geometry() for widget in common)
        assert popup.equalizer.header.geometry() == header and popup.size() == outer
        assert popup.sections.viewport.sizeHint().height() == 235
        assert popup.sections.viewport.height() == 227 and popup.height() == 569
        assert popup.sections.pages[1].geometry() == popup.sections.viewport.rect()
        assert not popup.sections.pages[0].isVisible()
        assert popup.sections.audio._poll.isActive()
        popup.sections.tabs.setCurrentIndex(0)
        popup.sections.finish()
        assert not popup.sections.audio._poll.isActive()
        assert popup.equalizer.effects.parentWidget() is popup.surface
    finally:
        dispose(parent, popup)


def test_tab_wheel_and_playback_updates_preserve_page_and_lyric_demand(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = Owner()

    def shared(cls: type[LyricsService]) -> LyricsService:
        return cast(LyricsService, owner)

    monkeypatch.setattr(LyricsService, "shared", classmethod(shared))
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    item = snapshot()

    def publish():
        popup.set_state(MediaState((item,), item.session_id), QPixmap())

    try:
        publish()
        popup.open_at_parent()
        sections = popup.sections
        tabs = sections.tabs
        for index, state in enumerate((PlaybackState.PLAYING, PlaybackState.PAUSED) * 2):
            item = replace(
                item, playback=replace(item.playback, state=state), timeline=replace(item.timeline, position=index + 10)
            )
            publish()
            qapp.processEvents()
            assert sections.active_index == 0 and not owner.watches
        for _ in range(2):
            point = tabs.rect().center()
            wheel = QWheelEvent(
                QPointF(point),
                QPointF(tabs.mapToGlobal(point)),
                QPoint(),
                QPoint(0, -120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.ScrollUpdate,
                False,
            )
            QApplication.sendEvent(tabs, wheel)
            assert wheel.isAccepted() and sections.active_index == tabs.currentIndex() == 0
        assert not owner.interests and not owner.watches

        popup.hide()
        item = replace(item, metadata=replace(item.metadata, title="New owned track"), seek_revision=2)
        publish()
        popup.open_at_parent()
        assert sections.active_index == 0 and not owner.watches
        qt_test.mouseClick(tabs, Qt.MouseButton.LeftButton, pos=tabs.tabRect(1).center())
        assert sections.active_index == 1 and not owner.watches
        tabs.setFocus()
        qt_test.keyClick(tabs, Qt.Key.Key_Right)
        sections.finish()
        qapp.processEvents()
        assert sections.active_index == 2 and len(owner.watches) == 1
        popup.hide()
        assert not owner.interests
        item = replace(item, timeline=replace(item.timeline, position=28))
        publish()
        assert not owner.interests and len(owner.watches) == 1
        popup.open_at_parent()
        sections.finish()
        qapp.processEvents()
        assert sections.active_index == 2 and len(owner.watches) == 2
    finally:
        dispose(parent, popup)


def test_theme_backplate_corners_and_lightning_extent(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    popup.setStyleSheet(".media-surface { background: #703757; } .eq-band { background: transparent; }")
    try:
        popup.open_at_parent()
        for effect in popup._intro:
            effect.finish()
        qapp.processEvents()
        panel, sections = popup.equalizer, popup.sections
        body = panel.body
        origin = body.mapTo(popup, QPoint())
        base = popup.grab().toImage()
        assert base.pixelColor(origin + QPoint(2, 10)) == QColor("#703757")

        # Contrast exposed corners with the inner fill, across both charge states.
        for elapsed in (0.11, popup.border.charge_duration + 0.2):
            popup.border._started = time.monotonic() - elapsed
            frame = popup.grab().toImage()
            canvas = QImage(frame.size(), QImage.Format.Format_ARGB32_Premultiplied)
            backplate = QColor("#12eb30")
            canvas.fill(backplate)
            painter = QPainter(canvas)
            painter.drawImage(0, 0, frame)
            painter.end()
            w, h = frame.width() - 1, frame.height() - 1
            assert all(canvas.pixelColor(x, y) == backplate for x, y in ((0, 0), (w, 0), (0, h), (w, h)))
            assert all(
                canvas.pixelColor(x, y) == QColor("#703757")
                for x, y in ((10, 10), (w - 10, 10), (10, h - 10), (w - 10, h - 10))
            )
        panel.bands.trigger()
        panel.bands.lightningPhase = 157
        charged = popup.grab().toImage()
        assert any(
            charged.pixelColor(x, y) != base.pixelColor(x, y)
            for y in range(origin.y() - 45, origin.y() - 16)
            for x in range(origin.x() + 5, origin.x() + 80)
        )
        assert any(
            charged.pixelColor(x, y) != base.pixelColor(x, y)
            for x in range(max(3, origin.x() - 16), origin.x() - 1)
            for y in range(origin.y() + 30, origin.y() + 90)
        )
        assert panel.effects.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        sections.tabs.setCurrentIndex(1)
        assert not panel.effects.isVisible() and panel.bands.phase == 1600.0
        sections.tabs.setCurrentIndex(0)
        sections.finish()
        assert panel.bands.phase == 1600.0
        popup.hide()
        assert not panel.effects.isVisible()
    finally:
        dispose(parent, popup)


def test_scaled_section_defaults_yield_to_ancestor_theme(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    previous = qapp.styleSheet()
    scales = (1, 1.5)
    qapp.setStyleSheet(
        media_section_fallbacks(
            {
                str(scale): {
                    "type": "yasb.media_v2.MediaWidgetV2",
                    "options": {"scale": scale, "use_default_styles": False},
                }
                for scale in scales
            }
        )
    )
    try:
        for scale in scales:
            parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=scale, use_default_styles=False)
            try:
                view = popup.sections.lyrics.view
                view.ensurePolished()
                assert view.font().pixelSize() == round(18 * scale)
                parent.setStyleSheet("QListView { color: #77bb55; font-size: 23px; }")
                view.ensurePolished()
                assert view.font().pixelSize() == 23
                assert view.palette().color(QPalette.ColorRole.Text) == QColor("#77bb55")
            finally:
                dispose(parent, popup)
    finally:
        qapp.setStyleSheet(previous)


def test_lyrics_scrollbar_has_scoped_identity_and_theme_states(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        scrollbar = popup.sections.lyrics.view.verticalScrollBar()
        assert scrollbar is not None
        assert scrollbar is popup.sections.lyrics.view.scroll_bar
        assert scrollbar.objectName() == "media-lyrics-scrollbar"
        assert scrollbar.property("class") == "media-lyrics-scrollbar"
        stylesheet = popup.styleSheet()
        assert ".media-lyrics-scrollbar:vertical" in stylesheet
        assert ".media-lyrics-scrollbar::handle:vertical:hover" in stylesheet
        assert ".media-lyrics-scrollbar::add-page:vertical" in stylesheet
    finally:
        dispose(parent, popup)


def test_lower_section_fits_full_bands_preset_box_and_tab_strip(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        qapp.processEvents()
        viewport = popup.sections.pages[0].viewport()
        assert viewport is not None
        bands = popup.equalizer.bands
        preset = popup.equalizer.buttons["Classic"]
        tabs = popup.sections.tabs
        assert bands.height() == 155
        assert viewport.rect().contains(QRect(bands.mapTo(viewport, QPoint()), bands.size()))
        assert viewport.rect().contains(QRect(preset.mapTo(viewport, QPoint()), preset.size()))
        assert popup.equalizer.header.rect().contains(QRect(tabs.pos(), tabs.size()))
    finally:
        dispose(parent, popup)


def test_preset_lightning_rebinds_after_lyrics_to_equalizer_navigation(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        popup.sections.finish()
        popup.sections.tabs.setCurrentIndex(2)
        popup.sections.finish()
        popup.sections.tabs.setCurrentIndex(0)
        popup.sections.finish()
        qapp.processEvents()
        effects = popup.equalizer.effects
        assert effects.isVisible()
        assert effects.width() >= popup.surface.width() - 10
        popup.equalizer.select_preset("Bass")
        assert popup.equalizer.bands.phase == 0.0
        assert effects.width() >= popup.surface.width() - 10
    finally:
        dispose(parent, popup)


def test_leaving_equalizer_cancels_held_gesture_before_discard(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        qapp.processEvents()
        slider = popup.equalizer.bands.sliders[0]
        slider.setSliderDown(True)
        slider.setValue(slider.value() + 1)
        assert popup.equalizer.apo.has_draft
        popup.sections.tabs.setCurrentIndex(1)
        assert not slider.isSliderDown() and not popup.equalizer.apo.has_draft
        assert popup.equalizer.apo.gains == (0.0,) * 10
        # A delayed release delivered to the outgoing page cannot recreate it.
        qt_test.keyClick(slider, Qt.Key.Key_Up)
        assert not popup.equalizer.apo.has_draft
        popup.sections.finish()
        popup.sections.tabs.setCurrentIndex(0)
        popup.sections.finish()
        assert not popup.equalizer.apo.has_draft
    finally:
        dispose(parent, popup)


def test_rapid_reversal_starts_at_current_presentation_and_close_settles(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        popup.sections.tabs.setCurrentIndex(1)
        qt_test.qWait(70)
        positions = tuple(page.offset for page in popup.sections.pages)
        assert -1 < positions[0] < 0 and 0 < positions[1] < 1
        popup.sections.tabs.setCurrentIndex(0)
        assert tuple(page.offset for page in popup.sections.pages) == positions
        popup.hide()
        assert popup.sections.pages[0].offset == 0 and not popup.sections.pages[0].isHidden()
        assert popup.sections.pages[1].offset == 1 and popup.sections.pages[1].isHidden()
        assert not popup.sections.audio._poll.isActive()
        popup.open_at_parent()
        qapp.processEvents()
        assert popup.sections.active_index == 0 and popup.sections.pages[0].isVisible()
    finally:
        dispose(parent, popup)


def test_same_turn_section_reversal_and_direct_jump_settle_only_the_chosen_page(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        sections = popup.sections
        for sequence in ((1, 0), (2,), (1, 2, 0)):
            for index in sequence:
                sections.tabs.setCurrentIndex(index)
            popup.hide_animated()
            popup.open_at_parent()
            sections.finish()
            selected = sequence[-1]
            for index, page in enumerate(sections.pages):
                assert page.isVisible() == (index == selected)
                assert page.offset == (0 if index == selected else -1 if index < selected else 1)
            assert not sections.audio._poll.isActive()
    finally:
        dispose(parent, popup)


def test_page_reversal_preserves_child_reveals_until_actually_hidden(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        sections = popup.sections
        band = popup.equalizer.bands.intro[0]
        band.sequence.setCurrentTime(480)
        before = band.progress
        sections.tabs.setCurrentIndex(1)
        assert 0 < band.progress == before < 1
        sections.finish()
        assert not band.isEnabled()
        cards = sections.audio.intro
        for effect in cards:
            effect.sequence.setCurrentTime(150)
        values = [effect.progress for effect in cards]
        assert 1 > values[0] > values[1] > values[2] == 0
        sections.tabs.setCurrentIndex(0)
        sections.tabs.setCurrentIndex(1)
        assert [effect.progress for effect in cards] == values
        sections.tabs.setCurrentIndex(2)
        sections.finish()
        assert all(not effect.isEnabled() for effect in cards)
        sections.tabs.setCurrentIndex(1)
        assert all(effect.isEnabled() and effect.progress == 0 for effect in cards)
    finally:
        dispose(parent, popup)


def test_lyrics_retry_uses_right_edge_without_an_empty_action_slot(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.widgets.services.media.lyrics import LyricsState

    owner = Owner()

    def shared(cls: type[LyricsService]) -> LyricsService:
        return cast(LyricsService, owner)

    monkeypatch.setattr(LyricsService, "shared", classmethod(shared))
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        item = snapshot()
        popup.set_state(MediaState((item,), item.session_id), QPixmap())
        popup.open_at_parent()
        sections = popup.sections
        sections.tabs.setCurrentIndex(2)
        sections.finish()
        assert sections.lyrics.retry_button.isHidden() and sections.action_slot.width() == 0
        owner.current = LyricsState("missing")
        owner.changed.emit(owner.watches[-1])
        qapp.processEvents()
        retry = sections.lyrics.retry_button
        assert retry.isVisible() and retry.geometry().right() == popup.equalizer.header.contentsRect().right()
        qt_test.mouseClick(retry, Qt.MouseButton.LeftButton)
        assert owner.retries == [owner.watches[-1]]
    finally:
        dispose(parent, popup)


def test_inactive_focus_is_rejected_without_disabling_outgoing_colors(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        popup.activateWindow()
        qapp.processEvents()
        slider = popup.equalizer.bands.sliders[0]
        slider.setFocus()
        popup.sections.tabs.setCurrentIndex(1)
        assert popup.sections.pages[0].isEnabled()
        assert slider.focusPolicy() == Qt.FocusPolicy.NoFocus
        slider.setFocus()
        qapp.processEvents()
        assert QApplication.focusWidget() is popup.sections.tabs
        qt_test.keyClick(slider, Qt.Key.Key_Up)
        assert not popup.equalizer.apo.has_draft
        popup.sections.tabs.setCurrentIndex(0)
        assert slider.focusPolicy() != Qt.FocusPolicy.NoFocus
    finally:
        dispose(parent, popup)


def test_qss_growth_keeps_last_control_reachable_inside_page(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 600, 450), scale=1)
    try:
        popup.setStyleSheet(popup.styleSheet() + "\n#media-presets { min-height: 400px; }\n")
        popup.open_at_parent()
        popup.activateWindow()
        qapp.processEvents()
        last = popup.equalizer.buttons["Classic"]
        last.setFocus()
        qapp.processEvents()
        page = popup.sections.pages[0]
        viewport = page.viewport()
        assert viewport is not None
        scrollbar = page.verticalScrollBar()
        assert scrollbar is not None and scrollbar.maximum() > 0
        assert viewport.rect().contains(QRect(last.mapTo(viewport, QPoint()), last.size()))
        outer = popup._scroll_area.viewport()
        assert outer is not None
        assert outer.rect().contains(QRect(last.mapTo(outer, QPoint()), last.size()))
    finally:
        dispose(parent, popup)


class AudioController(QObject):
    draft_changed = pyqtSignal()
    audio_state = NativeAudioState(balance=0.2, dynamics=2)
    audio_available = True
    output_state = AudioOutputState("owned", "", "Owned test output")
    restoring = False
    persistence_pending = False
    write_failed = False
    native_observation = NativeObservation(detail="Owned disconnected fixture")

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, object]] = []

    def update_audio(self, **changes: Any) -> bool:
        self.calls.append(changes)
        self.audio_state = replace(self.audio_state, **changes)
        self.draft_changed.emit()
        return True


def test_audio_hydration_is_read_only_mono_retains_balance_and_reset_is_whole(qapp: QApplication) -> None:
    parent = QWidget()
    controller = AudioController()
    panel = MediaAudioPanel(cast(EqualizerApoController, controller), 1, parent)
    try:
        parent.show()
        panel.show()
        qapp.processEvents()
        panel.sync()
        assert controller.calls == []
        assert panel.balance.value() == 20 and panel.dynamics.currentIndex() == 2
        panel.swap.click()
        assert panel.swap.isChecked()
        panel.mono.click()
        assert not panel.swap.isEnabled() and panel.swap.isChecked()
        panel.swap.click()
        assert controller.calls == [{"swap": True}, {"mono": True}]
        panel.mono.click()
        assert panel.swap.isEnabled() and panel.swap.isChecked()
        panel.mono.click()
        assert not panel.balance.isEnabled() and panel.balance.value() == 20
        panel.balance_scale._fade.setCurrentTime(75)
        assert 0.45 < panel.balance_scale.dim.opacity() < 1.0
        panel.balance_scale._fade.setCurrentTime(150)
        assert panel.balance_scale.dim.opacity() == pytest.approx(0.45)
        assert panel.balance_value.isEnabled()
        panel.reset()
        assert controller.audio_state == NativeAudioState()
        assert len(controller.calls) == 5
        assert panel.balance.isEnabled() and panel.balance.value() == 0
        assert panel.adaptive.isEnabled() and "retains the manual curve" in panel.adaptive.accessibleDescription()
        calls_before_sync = controller.calls.copy()
        controller.audio_available = False
        panel.sync()
        assert not panel.adaptive.isEnabled() and "Graphic EQ" in panel.adaptive.accessibleDescription()
        assert controller.calls == calls_before_sync
    finally:
        parent.hide()
        sip.delete(parent)


def test_audio_poll_lifetime_and_accessible_status(qapp: QApplication) -> None:
    parent = QWidget()
    controller = AudioController()
    panel = MediaAudioPanel(cast(EqualizerApoController, controller), 1, parent)
    try:
        parent.show()
        panel.show()
        qapp.processEvents()
        assert panel._poll.isActive()
        assert panel.adaptive.toolTip() == ""
        assert panel.detail.toolTip() == ""
        assert panel.detail.accessibleDescription() == "Owned disconnected fixture"
        assert panel.detail.text() == "Saved; audio host has not connected"
        controller.native_observation = NativeObservation(detail="")
        panel.sync()
        assert panel.detail.toolTip() == ""
        assert panel.detail.accessibleDescription() == ""
        parent.hide()
        assert not panel._poll.isActive()
        panel.sync()
        assert controller.calls == []
    finally:
        sip.delete(parent)


def test_audio_reset_retains_dynamic_eq_and_bypass(qapp: QApplication) -> None:
    parent = QWidget()
    controller = AudioController()
    controller.audio_state = NativeAudioState(balance=0.4, mono=True, swap=True, dynamics=2, adaptive=True, bypass=True)
    panel = MediaAudioPanel(cast(EqualizerApoController, controller), 1, parent)
    try:
        panel.reset()
        assert controller.audio_state == NativeAudioState(adaptive=True, bypass=True)
        assert controller.calls == [{"balance": 0.0, "mono": False, "swap": False, "dynamics": 0}]
    finally:
        sip.delete(parent)


def test_captured_drag_cannot_return_during_close_or_interrupted_reopen(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        qapp.processEvents()
        slider = popup.equalizer.bands.sliders[0]
        option = QStyleOptionSlider()
        slider.initStyleOption(option)
        style = slider.style()
        assert style is not None
        handle = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider
        )
        start = handle.center()
        qt_test.mousePress(slider, Qt.MouseButton.LeftButton, pos=start)
        qt_test.mouseMove(slider, start + QPoint(0, -20))
        assert slider.isSliderDown() and popup.equalizer.apo.has_draft
        popup.hide_animated()
        assert not slider.isSliderDown() and not popup.equalizer.apo.has_draft
        qt_test.mouseMove(slider, start + QPoint(0, -40))
        assert not popup.equalizer.apo.has_draft
        popup.open_at_parent()
        qt_test.mouseMove(slider, start + QPoint(0, -50))
        assert not slider.isSliderDown() and not popup.equalizer.apo.has_draft
        qt_test.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=start + QPoint(0, -50))
        assert not popup.equalizer.apo.has_draft
        qt_test.keyClick(slider, Qt.Key.Key_Up)  # A new keyboard gesture still works.
        assert popup.equalizer.apo.has_draft
    finally:
        dispose(parent, popup)


def test_dynamic_header_input_belongs_to_equalizer_after_reparenting(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        qapp.processEvents()
        controller = AudioController()
        audio = popup.sections.audio
        audio.controller = cast(EqualizerApoController, controller)
        controller.draft_changed.connect(audio.sync)
        audio.sync()
        assert audio.adaptive.isVisible() and audio.adaptive.isEnabled()
        qt_test.mouseClick(audio.adaptive, Qt.MouseButton.LeftButton)
        assert controller.calls == [{"adaptive": True}]
        assert audio.adaptive.focusPolicy() == Qt.FocusPolicy.TabFocus
        popup.sections.tabs.setCurrentIndex(1)
        assert not audio.adaptive.isVisible()
        qt_test.keyClick(audio.adaptive, Qt.Key.Key_Space)
        assert controller.calls == [{"adaptive": True}]
        popup.sections.tabs.setCurrentIndex(0)
        popup.hide_animated()
        qt_test.keyClick(audio.adaptive, Qt.Key.Key_Space)
        assert controller.calls == [{"adaptive": True}]
    finally:
        dispose(parent, popup)


def test_compact_header_preserves_accessible_error_reason_and_recovery(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        panel = popup.equalizer

        panel._on_apo_status("Error", "Fixture ConfigPath denied")
        assert panel.current.isVisible() and panel.apply_button.isVisible()
        assert "Fixture ConfigPath denied" in panel.current.accessibleDescription()
        assert "Fixture ConfigPath denied" in panel.apply_button.accessibleDescription()
        panel._sync_apply()
        assert "Fixture ConfigPath denied" in panel.apply_button.accessibleDescription()
        panel._on_apo_status("Saved", "Fixture recovered")
        assert "denied" not in panel.current.accessibleDescription()
        assert "denied" not in panel.apply_button.accessibleDescription()
        assert "Fixture recovered" in panel.header.accessibleDescription()
    finally:
        dispose(parent, popup)


def test_section_tabs_leave_rounded_outer_corners(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        for effect in popup._intro:
            effect.finish()
        tabs = popup.sections.tabs
        selected = QColor("#cba6f7")
        for index in (0, 2):
            tabs.setCurrentIndex(index)
            popup.sections.finish()
            qapp.processEvents()
            image = tabs.grab().toImage()
            x = 0 if index == 0 else image.width() - 1
            assert image.pixelColor(x, 0) != selected
            assert image.pixelColor(x, image.height() - 1) != selected
            tab = tabs.tabRect(index)
            inside_edge = tab.left() + 5 if index == 0 else tab.right() - 5
            assert image.pixelColor(inside_edge, tab.center().y()) == selected
        tab_bottom = tabs.mapTo(popup.equalizer, tabs.rect().bottomLeft()).y()
        assert popup.sections.viewport.y() - tab_bottom >= 16
    finally:
        dispose(parent, popup)


def test_returning_to_preset_keeps_header_stable_until_slider_release(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        panel, sections = popup.equalizer, popup.sections
        panel.select_preset("Bass", motion=False)
        sections.finish()
        qapp.processEvents()
        slider = panel.bands.sliders[0]
        option = QStyleOptionSlider()
        slider.initStyleOption(option)
        style = cast(QStyle, slider.style())
        point = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider
        ).center()
        qt_test.mousePress(slider, Qt.MouseButton.LeftButton, pos=point)
        qt_test.mouseMove(slider, point + QPoint(0, 20))
        assert panel.apo.has_draft and panel.current.text() == "Custom"
        assert panel.apply_button.isHidden() and sections.action_slot.width() == 0
        qt_test.mouseClick(slider, Qt.MouseButton.RightButton, pos=point + QPoint(0, 20))
        assert slider.pointer_held and slider.isSliderDown() and panel.apply_button.isHidden()
        qt_test.mouseMove(slider, point)
        slider.setSliderPosition(5 * slider.SCALE)
        assert slider.isSliderDown() and not panel.apo.has_draft
        assert panel.apply_button.isHidden() and not panel.apply_button.isEnabled()
        assert panel.current.text() == "Custom" and sections.action_slot.width() == 0
        qt_test.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=point)
        assert panel.current.text() == "Bass" and panel.buttons["Bass"].isChecked()
        assert panel.apply_button.isHidden() and sections.action_slot.width() == 0 and not panel.apo.has_draft

        qt_test.mousePress(slider, Qt.MouseButton.LeftButton, pos=point)
        qt_test.mouseMove(slider, point + QPoint(0, 20))
        assert panel.apply_button.isHidden()
        qt_test.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=point + QPoint(0, 20))
        assert panel.apo.has_draft and panel.apply_button.text() == "Apply" and panel.apply_button.isEnabled()
        slot = sections.action_slot
        animation = cast(dict[str, QPropertyAnimation], getattr(slot, "_motion"))["extent"]
        animation.setCurrentTime(100)
        assert 0 < slot.width() < slot.content_width
        sections.finish()
        slider.initStyleOption(option)
        edited_handle = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider
        ).center()
        qt_test.mousePress(slider, Qt.MouseButton.LeftButton, pos=edited_handle)
        qt_test.mouseMove(slider, point)
        slider.setSliderPosition(5 * slider.SCALE)
        assert not panel.apo.has_draft and panel.apply_button.isVisible() and not panel.apply_button.isEnabled()
        assert slot.width() == slot.content_width
        qt_test.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=point)
        animation.setCurrentTime(100)
        assert 0 < slot.width() < slot.content_width and panel.apply_button.isVisible()
        sections.finish()
        assert slot.width() == 0 and panel.apply_button.isHidden()
    finally:
        dispose(parent, popup)


def test_preset_caption_retains_reflowed_width_on_interrupted_reopen(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        panel, sections = popup.equalizer, popup.sections
        tabs = sections.tabs
        for index in (1, 0):
            qt_test.mouseClick(tabs, Qt.MouseButton.LeftButton, pos=tabs.tabRect(index).center())
            sections.finish()
        qapp.processEvents()
        tab_rect = tabs.geometry()
        old_width = sections.preset_slot.width()
        qt_test.mouseClick(panel.buttons["Classic"], Qt.MouseButton.LeftButton)
        assert panel.current.text() == "Classic"
        caption_width = panel.current.sizeHint().width()
        assert caption_width > old_width
        assert sections.preset_slot.width() == caption_width

        popup.hide_animated()
        popup.open_at_parent()
        qapp.processEvents()

        assert sections.preset_slot.width() == caption_width
        assert panel.header.rect().contains(QRect(panel.current.mapTo(panel.header, QPoint()), panel.current.size()))
        assert tabs.geometry() == tab_rect
    finally:
        dispose(parent, popup)


def test_clean_equalizer_header_hides_action_box_until_a_draft_exists(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        popup.sections.finish()
        assert not popup.equalizer.apply_button.isVisible()
        slider = popup.equalizer.bands.sliders[0]
        slider.setFocus()
        qt_test.keyClick(slider, Qt.Key.Key_Up)
        assert popup.equalizer.apply_button.isVisible()
        assert popup.equalizer.apply_button.text() == "Apply"
    finally:
        dispose(parent, popup)


def test_audio_segmented_dynamics_accepts_keys_only_on_selected_page(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        popup.sections.tabs.setCurrentIndex(1)
        popup.sections.finish()
        controller = AudioController()
        audio = popup.sections.audio
        audio.controller = cast(EqualizerApoController, controller)
        controller.draft_changed.connect(audio.sync)
        audio.sync()
        qt_test.keyClick(audio.dynamics, Qt.Key.Key_Left)
        assert controller.calls == [{"dynamics": 1}]
        popup.sections.tabs.setCurrentIndex(0)
        qt_test.keyClick(audio.dynamics, Qt.Key.Key_Left)
        assert controller.calls == [{"dynamics": 1}]
    finally:
        dispose(parent, popup)


def test_audio_switches_and_segmented_selection_animate_without_mouse_focus(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        sections = popup.sections
        panel = sections.audio
        controller = AudioController()
        panel.controller = cast(EqualizerApoController, controller)
        controller.draft_changed.connect(panel.sync)
        panel.sync()
        for effect in popup._intro:
            effect.finish()
        sections.tabs.setFocus(Qt.FocusReason.TabFocusReason)
        for switch in (panel.adaptive, panel.mono, panel.swap):
            if switch is panel.mono:
                sections.tabs.setCurrentIndex(1)
                sections.finish()
                for effect in panel.intro:
                    effect.finish()
            qt_test.mouseClick(switch, Qt.MouseButton.LeftButton)
            assert switch.isChecked() and not switch.hasFocus()
            motion = cast(dict[str, QPropertyAnimation], getattr(switch, "_motion"))["mix"]
            motion.setCurrentTime(100)
            assert 0 < switch.mix < 1
            partial = switch.mix
            qt_test.mouseClick(switch, Qt.MouseButton.LeftButton)
            assert not switch.isChecked() and motion.startValue() == partial
            motion.setCurrentTime(250)
            assert switch.mix == 0
        sections.tabs.setFocus(Qt.FocusReason.TabFocusReason)
        qt_test.mouseClick(panel.balance, Qt.MouseButton.LeftButton, pos=panel.balance.rect().center())
        assert not panel.balance.hasFocus()
        pill = panel.dynamics
        qt_test.mouseClick(pill, Qt.MouseButton.LeftButton, pos=pill.tabRect(0).center())
        tween = cast(dict[str, QPropertyAnimation], getattr(pill, "_motion"))["position"]
        tween.setCurrentTime(90)
        assert 0 < pill.position < 2
        ink = QColor("#cba6f7")
        snapshot = pill.grab().toImage()
        x = round(pill.tabRect(0).left() + pill.tabRect(0).width() * pill.position) + 12
        assert snapshot.pixelColor(x, 5) == ink
        tween.setCurrentTime(1)
        initial = pill.grab().toImage()
        label = pill.tabRect(0).adjusted(10, 5, -10, -5)
        assert any(
            initial.pixelColor(x, y).lightness() > 120
            for x in range(label.left(), label.right())
            for y in range(label.top(), label.bottom())
        )
        for index in (0, 1, 2):
            pill.setCurrentIndex(index)
            tween.setCurrentTime(250)
            qapp.processEvents()
            tab = pill.tabRect(index)
            image = pill.grab().toImage()
            assert image.pixelColor(tab.center().x(), 5) == ink
            if index == 1:
                assert image.pixelColor(tab.left() + 1, 2) == ink
            else:
                outer = tab.left() if index == 0 else tab.right()
                assert image.pixelColor(outer, 0) != ink
    finally:
        dispose(parent, popup)


def audio_panel(qapp: QApplication, **options: object) -> tuple[QWidget, MediaAudioPanel, AudioController]:
    from core.validation.widgets.yasb.media_v2 import MediaV2AudioConfig

    parent = QWidget()
    controller = AudioController()
    panel = MediaAudioPanel(
        cast(EqualizerApoController, controller), 1, parent, MediaV2AudioConfig.model_validate(options)
    )
    panel.resize(600, 230)
    parent.show()
    panel.show()
    qapp.processEvents()
    return parent, panel, controller


def test_reference_audio_motion_is_unchanged_and_off_track_colour_is_themable(qapp: QApplication) -> None:
    parent, panel, controller = audio_panel(qapp)
    try:
        assert panel.property("audioMotion") is None and not panel._fades and panel._lease is None
        controller.audio_state = replace(controller.audio_state, balance=-0.5)
        panel.sync()
        assert panel.balance.value() == -50 and panel.left_value.text() == "L  100%"
        assert not getattr(panel.balance, "_motion", {})
        assert panel.mono.offColor == QColor("#45475a")
        panel.mono.setStyleSheet("QCheckBox { qproperty-offColor: #ff0000; }")
        panel.mono.ensurePolished()
        assert panel.mono.offColor == QColor("#ff0000")
        assert controller.calls == []
    finally:
        sip.delete(parent)


def test_enhanced_balance_animates_without_writes_and_reset_writes_once(qapp: QApplication) -> None:
    parent, panel, controller = audio_panel(qapp, motion="enhanced")
    try:
        assert panel.property("audioMotion") == "enhanced"
        controller.audio_state = replace(controller.audio_state, balance=-0.6)
        panel.sync()
        motion = cast(dict[str, QPropertyAnimation], getattr(panel.balance, "_motion"))["presented"]
        assert motion.state() == QPropertyAnimation.State.Running and motion.duration() == 220
        motion.setCurrentTime(110)
        assert -60 < panel.balance.value() < 20 and controller.calls == []
        assert panel.left_value.text() != "L  100%" or panel.right_value.text() != "40%  R"
        panel.reset()
        assert controller.calls == [{"balance": 0.0, "mono": False, "swap": False, "dynamics": 0}]
        motion.setCurrentTime(motion.duration())
        assert panel.balance.value() == 0 and len(controller.calls) == 1
        controller.audio_state = replace(controller.audio_state, balance=0.8)
        panel.sync()
        motion.setCurrentTime(60)
        parent.hide()
        assert panel.balance.value() == 80 and not panel._poll.isActive()
        assert motion.state() != QPropertyAnimation.State.Running and len(controller.calls) == 1
    finally:
        sip.delete(parent)


def test_meters_lease_only_while_active_playing_and_visible(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.widgets.test_media_v2 import install_capture

    capture = install_capture(monkeypatch)
    parent, panel, controller = audio_panel(qapp, meters=True)
    try:
        panel.set_playing(True)
        assert not capture.readers and not panel._meter_frames.isActive()
        panel.set_active(True)
        assert capture.readers == [(30, frozenset({"left", "right"}))] and panel._meter_frames.isActive()
        capture.is_active = True

        def magnitudes(channel: str) -> list[float]:
            return [0.25 if channel == "left" else 0.0] * 1025

        monkeypatch.setattr(capture, "magnitudes", magnitudes)
        controller.audio_state = replace(controller.audio_state, balance=0.0, swap=True)
        panel._meter_tick()
        assert panel.balance_scale.levels[0] == 0 and panel.balance_scale.levels[1] > 0.5
        controller.audio_state = replace(controller.audio_state, mono=True)
        panel._levels = [0.0, 0.0]
        panel._meter_tick()
        assert panel.balance_scale.levels[0] == panel.balance_scale.levels[1] > 0
        panel.set_playing(False)
        assert not capture.readers and not panel._meter_frames.isActive() and panel.balance_scale.levels == (0, 0)
        panel.set_playing(True)
        parent.hide()
        assert not capture.readers and not panel._meter_frames.isActive()
        assert controller.calls == []
    finally:
        sip.delete(parent)
