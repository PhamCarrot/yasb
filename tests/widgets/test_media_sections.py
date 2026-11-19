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

from core.utils.tooltip import TooltipEventFilter
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
        assert motions["offset"].duration() == 400
        assert motions["opacity"].duration() == 250
        popup.sections.finish()
        qapp.processEvents()
        assert common == (popup.art, popup.title, popup.progress, popup.controls, popup.selector)
        assert geometry == tuple(widget.geometry() for widget in common)
        assert popup.equalizer.header.geometry() == header and popup.size() == outer
        # 235 is preferred; the canonical 565-high reference negotiates 227.
        assert popup.sections.viewport.sizeHint().height() == 235
        assert popup.sections.viewport.height() == 227 and popup.height() == 565
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
        assert popup.sections.pages[0].offset == 0 and popup.sections.pages[0].opacity == 1
        assert popup.sections.pages[1].offset == 1 and popup.sections.pages[1].opacity == 0
        assert not popup.sections.audio._poll.isActive()
        popup.open_at_parent()
        qapp.processEvents()
        assert popup.sections.active_index == 0 and popup.sections.pages[0].isVisible()
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
        panel.mono.click()
        assert controller.calls == [{"mono": True}]
        assert not panel.balance.isEnabled() and panel.balance.value() == 20
        panel.balance_scale._fade.setCurrentTime(75)
        assert 0.45 < panel.balance_scale.dim.opacity() < 1.0
        panel.balance_scale._fade.setCurrentTime(150)
        assert panel.balance_scale.dim.opacity() == pytest.approx(0.45)
        assert panel.balance_value.isEnabled()
        panel.reset()
        assert controller.audio_state == NativeAudioState()
        assert len(controller.calls) == 2
        assert panel.balance.isEnabled() and panel.balance.value() == 0
        assert panel.adaptive.isEnabled() and "retains the manual curve" in panel.adaptive.accessibleDescription()
        controller.audio_available = False
        panel.sync()
        assert not panel.adaptive.isEnabled() and "Graphic EQ" in panel.adaptive.accessibleDescription()
        assert len(controller.calls) == 2
    finally:
        parent.hide()
        sip.delete(parent)


def test_audio_poll_lifetime_and_tooltip_recovery(qapp: QApplication) -> None:
    parent = QWidget()
    controller = AudioController()
    panel = MediaAudioPanel(cast(EqualizerApoController, controller), 1, parent)
    try:
        parent.show()
        panel.show()
        qapp.processEvents()
        assert panel._poll.isActive()
        assert panel.detail.toolTip() == "Owned disconnected fixture"
        controller.native_observation = NativeObservation(detail="")
        panel.sync()
        assert panel.detail.toolTip() == ""
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
        assert audio.adaptive.focusPolicy() == Qt.FocusPolicy.StrongFocus
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


def test_compact_header_preserves_error_reason_and_recovery(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        panel = popup.equalizer

        def hint(widget: QWidget) -> str:
            tooltip = getattr(widget, "_tooltip_filter", None)
            assert isinstance(tooltip, TooltipEventFilter)
            return tooltip.tooltip_text

        panel._on_apo_status("Error", "Fixture ConfigPath denied")
        assert panel.current.isVisible() and panel.apply_button.isVisible()
        assert "Fixture ConfigPath denied" in hint(panel.current)
        assert "Fixture ConfigPath denied" in hint(panel.apply_button)
        panel._sync_apply()
        assert "Fixture ConfigPath denied" in hint(panel.apply_button)
        panel._on_apo_status("Saved", "Fixture recovered")
        assert "denied" not in hint(panel.current) and "denied" not in hint(panel.apply_button)
        assert "Fixture recovered" in hint(panel.header)
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
