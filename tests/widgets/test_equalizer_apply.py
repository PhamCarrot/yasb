# pyright: reportPrivateUsage=false

import asyncio
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from PyQt6.QtCore import QObject, QPoint, QPropertyAnimation, QRect, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QStackedWidget, QStyle, QStyleOptionSlider, QWidget

from core.validation.widgets.yasb.media_v2 import MediaEqualizerConfig
from core.widgets.services.media import equalizer_apo as apo
from core.widgets.services.media.audio_device import AudioOutputState, DefaultAudioOutputService
from core.widgets.services.media.equalizer_apo import EqualizerApoController, EqualizerApoWriter
from core.widgets.yasb import media_v2_equalizer as panel_module
from core.widgets.yasb.media_v2_sections import MediaSections
from tests.widgets.test_equalizer_apo_ownership import Output, controller, manager_at, settled
from tests.widgets.test_equalizer_apo_recovery import OUTPUT, Registry
from tests.widgets.test_media_lyrics_owner import until

qt_test = cast(Any, QTest)


def owned_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[panel_module.EqualizerPanel, EqualizerApoWriter]:
    manager, output = manager_at(tmp_path), Output()

    def client(options: MediaEqualizerConfig, parent: QObject | None = None) -> EqualizerApoController:
        return EqualizerApoController(
            options, parent, manager=manager, output_service=cast(DefaultAudioOutputService, output)
        )

    monkeypatch.setattr(panel_module, "EqualizerApoController", client)
    panel = panel_module.EqualizerPanel(
        MediaEqualizerConfig.model_validate(
            {"backend": "equalizer_apo", "preset_effect": "none", "apo": {"enabled": True}}
        ),
        1,
    )
    panel.resize(583, 280)
    writer = panel.apo._writer
    assert writer is not None
    return panel, writer


def handle_center(slider: panel_module.GainSlider) -> QPoint:
    option = QStyleOptionSlider()
    slider.initStyleOption(option)
    return (
        cast(QStyle, slider.style())
        .subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider)
        .center()
    )


def drag_band(slider: panel_module.GainSlider, distance: int) -> None:
    start = handle_center(slider)
    end = start + QPoint(0, distance)
    qt_test.mousePress(slider, Qt.MouseButton.LeftButton, pos=start)
    assert slider.isSliderDown()
    qt_test.mouseMove(slider, end)
    qt_test.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=end)
    assert not slider.isSliderDown()


@pytest.mark.parametrize("presets", [("Bass",), ("Classic", "Treble", "Bass")])
def test_mouse_drag_applies_only_edited_bands_during_preset_tween(
    tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, presets: tuple[str, ...]
) -> None:
    async def run() -> None:
        panel, writer = owned_panel(tmp_path, monkeypatch)
        sections = MediaSections(panel, 1)
        try:
            panel.show()
            await settled(qapp, writer)
            for name in presets:
                qt_test.mouseClick(panel.buttons[name], Qt.MouseButton.LeftButton)
            sliders = panel.bands.sliders
            travel = panel.bands.travel
            bass = panel_module.PRESETS["Bass"]
            travel.setCurrentTime(50)
            assert 0 < sliders[1].gain < bass[1]
            generation = writer._generation
            managed = tmp_path / "config" / apo.MANAGED_FILENAME
            slider = sliders[0]
            handle = handle_center(slider)
            qt_test.mousePress(slider, Qt.MouseButton.LeftButton, pos=handle)
            assert slider.isSliderDown() and panel.apply_button.isHidden()
            qt_test.mouseMove(slider, handle + QPoint(0, 18))
            await settled(qapp, writer)
            assert panel.apo.has_draft and panel.apply_button.isHidden()
            assert managed.read_bytes() == apo.render_managed_config(bass, OUTPUT.endpoint_guid).encode()
            qt_test.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=handle + QPoint(0, 18))
            assert panel.apply_button.isVisible()
            first = sliders[0].gain_from_slider()
            assert first != bass[0]
            expected = (first, *bass[1:])
            first_draft = panel.apo.editing_gains
            assert panel.current.text() == "Custom"
            lease = panel.apo._draft_token
            drag_band(sliders[8], 0)
            assert panel.apo.editing_gains == first_draft and panel.apo._draft_token is lease
            drag_band(sliders[3], -14)
            expected = (*expected[:3], sliders[3].gain_from_slider(), *expected[4:])
            before_apply = panel.apo.editing_gains
            assert panel.apo._draft_token is lease and writer._generation == generation
            await settled(qapp, writer)
            assert managed.read_bytes() == apo.render_managed_config(bass, OUTPUT.endpoint_guid).encode()
            travel.setCurrentTime(travel.duration())
            assert sliders[1].gain == bass[1]
            assert panel.apply_button.isEnabled() and panel.apply_button.text() == "Apply"
            qt_test.mouseClick(panel.apply_button, Qt.MouseButton.LeftButton)
            await settled(qapp, writer)
            assert (first_draft, before_apply, managed.read_bytes()) == (
                (first, *bass[1:]),
                expected,
                apo.render_managed_config(expected, OUTPUT.endpoint_guid).encode(),
            )
            assert writer._generation == generation + 1
        finally:
            sections.suspend()
            panel.apo.shutdown()
            panel.close()
            panel.deleteLater()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_two_visible_apo_views_keep_preset_travel_through_writer_readback(
    tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        panel, writer = owned_panel(tmp_path, monkeypatch)
        other = panel_module.EqualizerPanel(panel.options, 1)
        try:
            panel.show()
            other.show()
            await settled(qapp, writer)
            held = other.bands.sliders[1]
            held.setSliderDown(True)
            qt_test.mouseClick(panel.buttons["Bass"], Qt.MouseButton.LeftButton)
            for view in (panel, other):
                handle = view.bands.sliders[0]
                tween = view.bands.travel
                tween.setCurrentTime(70)
                position = handle.gain
                assert 0 < position < 5 and view.apo.editing_gains[0] == 5
                view.apo._on_owner_changed(view.apo._target, force=True)
                assert tween.currentTime() == 70 and handle.gain == pytest.approx(position)
                assert not view.apo.has_draft
            assert held.gain == 0
            generation = writer._generation
            held.setSliderDown(False)
            assert held.gain == 7 and not other.apo.has_draft and writer._generation == generation
            await settled(qapp, writer)
            data = (tmp_path / "config" / apo.MANAGED_FILENAME).read_bytes()
            assert data == apo.render_managed_config(panel_module.PRESETS["Bass"], OUTPUT.endpoint_guid).encode()
            held.setSliderDown(True)
            custom = (3.0,) * 10
            assert panel.apo.apply_preset(custom)
            assert other.apo.editing_gains == custom and held.gain == 7
            held.setSliderDown(False)
            assert held.gain == 3 and not other.apo.has_draft
            held.setSliderDown(True)
            assert panel.apo.update_custom((2.0,) * 10)
            assert not held.isEnabled() and not held.isSliderDown()
            assert panel.apo.apply_custom()
            assert held.isEnabled() and held.gain == 2 and not other.apo.has_draft
        finally:
            for view in (other, panel):
                view.close()
                view.apo.shutdown()
                view.deleteLater()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_preset_caption_fits_during_held_write_and_rapid_selection(
    tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        panel, writer = owned_panel(tmp_path, monkeypatch)
        panel.current.setFont(QFont("Segoe UI", 14))
        sections = MediaSections(panel, 1)
        entered, release = threading.Event(), threading.Event()
        write = apo.atomic_write_text

        def held(path: Path, text: str, encoding: str = "utf-8") -> None:
            entered.set()
            assert release.wait(5)
            write(path, text, encoding)

        try:
            panel.show()
            await settled(qapp, writer)
            sections.finish()
            initial = panel.current.width()
            monkeypatch.setattr(apo, "atomic_write_text", held)
            qt_test.mouseClick(panel.buttons["Classic"], Qt.MouseButton.LeftButton)
            assert panel.header.rect().contains(
                QRect(panel.current.mapTo(panel.header, QPoint()), panel.current.size())
            )
            await until(entered.is_set)
            motions = cast(dict[str, QPropertyAnimation], getattr(sections.preset_slot, "_motion", {}))
            if "extent" in motions:
                motions["extent"].setCurrentTime(110)
            assert panel.current.text() == "Classic" and panel.buttons["Classic"].isChecked()
            needed = panel.current.sizeHint().width()
            assert needed > initial
            assert panel.current.width() == sections.preset_slot.width() == needed
            for name in ("Pop", "Classic", "Bass"):
                qt_test.mouseClick(panel.buttons[name], Qt.MouseButton.LeftButton)
                assert panel.current.text() == name and panel.buttons[name].isChecked()
                assert panel.current.width() == sections.preset_slot.width() == panel.current.sizeHint().width()
            drag_band(panel.bands.sliders[0], 18)
            assert panel.current.text() == "Custom" and not any(button.isChecked() for button in panel.buttons.values())
            assert panel.current.width() == sections.preset_slot.width() == panel.current.sizeHint().width()
            sections.tabs.setCurrentIndex(1)
            morph = cast(dict[str, QPropertyAnimation], getattr(sections.preset_slot, "_motion"))["extent"]
            morph.setCurrentTime(100)
            elapsed, width = morph.currentTime(), sections.preset_slot.width()
            writer.changed.emit(panel.apo._target)
            assert (morph.currentTime(), sections.preset_slot.width()) == (elapsed, width)
            sections.finish()
            sections.tabs.setCurrentIndex(0)
            morph.setCurrentTime(100)
            extent = sections.preset_slot.extent
            qt_test.mouseClick(panel.buttons["Classic"], Qt.MouseButton.LeftButton)
            assert sections.preset_slot.extent == pytest.approx(extent)
            assert morph.state().name == "Running" and morph.duration() == 300
        finally:
            release.set()
            panel.apo.shutdown()
            panel.close()
            panel.deleteLater()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_mouse_release_does_not_change_synchronous_successor_draft(
    tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        panel, writer = owned_panel(tmp_path, monkeypatch)
        replaced = False
        successor = (8.0,) * 10

        def replace_draft(key: str) -> None:
            nonlocal replaced
            if not replaced and panel.apo.has_draft:
                replaced = True
                assert panel.apo.apply_custom()
                assert panel.apo.update_custom(successor)

        try:
            panel.show()
            await settled(qapp, writer)
            writer.changed.connect(replace_draft)
            slider = panel.bands.sliders[0]
            option = QStyleOptionSlider()
            slider.initStyleOption(option)
            start = (
                cast(QStyle, slider.style())
                .subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider)
                .center()
            )
            end = start - QPoint(0, 18)
            qt_test.mousePress(slider, Qt.MouseButton.LeftButton, pos=start)
            qt_test.mouseMove(slider, end)
            successor_lease = panel.apo.draft_identity
            assert replaced and successor_lease is not None and panel.apo.editing_gains == successor
            await settled(qapp, writer)
            managed = tmp_path / "config" / apo.MANAGED_FILENAME
            before_release, generation = managed.read_bytes(), writer._generation
            qt_test.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=end)
            assert panel.apo.draft_identity is successor_lease
            assert managed.read_bytes() == before_release and writer._generation == generation
            assert panel.apply_button.isEnabled()
            qt_test.mouseClick(panel.apply_button, Qt.MouseButton.LeftButton)
            await settled(qapp, writer)
            assert panel.apo.applied_gains == successor
            assert managed.read_bytes() == apo.render_managed_config(successor, OUTPUT.endpoint_guid).encode()
        finally:
            panel.apo.shutdown()
            panel.close()
            panel.deleteLater()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_controller_rebinds_a_closed_default_output_service(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    def init(service: DefaultAudioOutputService) -> None:
        QObject.__init__(service)
        service._state = AudioOutputState("owned-endpoint", "", "Owned output")
        service._closed = True

    monkeypatch.setattr(DefaultAudioOutputService, "__init__", init)
    closed = DefaultAudioOutputService()
    replacement = DefaultAudioOutputService()
    replacement._closed = False
    monkeypatch.setattr(DefaultAudioOutputService, "instance", staticmethod(lambda: replacement))
    client = EqualizerApoController(MediaEqualizerConfig(), output_service=closed)
    try:
        assert client.output_state is replacement.state
        assert client._output is replacement
    finally:
        client.shutdown()


@pytest.mark.parametrize("debounce_ms", [50, 500])
def test_manual_release_is_draft_only(tmp_path: Path, qapp: QApplication, debounce_ms: int) -> None:
    async def run() -> None:
        client = controller(manager_at(tmp_path), Output(), write_debounce_ms=debounce_ms)
        managed = tmp_path / "config" / apo.MANAGED_FILENAME
        writer = client._writer
        assert writer is not None
        try:
            client.start((0.0,) * 10)
            await settled(qapp, writer)
            generation = writer._generation
            before = managed.read_bytes()
            client.update_custom((3.0,) * 10, final=True)
            deadline = asyncio.get_running_loop().time() + 0.6
            while asyncio.get_running_loop().time() < deadline:
                qapp.processEvents()
                await asyncio.sleep(0.01)
            await settled(qapp, writer)
            assert writer._generation == generation
            assert managed.read_bytes() == before
            assert client.editing_gains == (3.0,) * 10
            assert client.applied_gains == (0.0,) * 10
            assert client.apply_custom()
            await settled(qapp, writer)
            assert writer._generation == generation + 1
            assert managed.read_bytes() == apo.render_managed_config((3.0,) * 10, OUTPUT.endpoint_guid).encode()
        finally:
            client.shutdown()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_enabled_apply_rejects_missing_writer_without_consuming_draft(tmp_path: Path) -> None:
    async def run() -> None:
        client = controller(manager_at(tmp_path), Output())
        try:
            assert client.update_custom((3.0,) * 10)
            await EqualizerApoWriter.aclose_shared()
            assert EqualizerApoWriter.shared_instance() is None
            assert not client.apply_custom()
            assert not client.apply_preset((7.0,) * 10)
            assert client.has_draft and client.gains == (3.0,) * 10
            assert client.applied_state is None
            assert EqualizerApoWriter.shared_instance() is None
            assert not (tmp_path / "config" / apo.MANAGED_FILENAME).exists()
            client.reconnect_writer()
            assert client.draft_needs_review
            assert not client.apply_custom()
            client.review_custom()
            assert not client.has_draft and client.gains == (0.0,) * 10
            assert not (tmp_path / "config" / apo.MANAGED_FILENAME).exists()
        finally:
            client.shutdown()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_replacement_writer_rejects_stale_draft_after_newer_commit(tmp_path: Path, qapp: QApplication) -> None:
    async def run() -> None:
        old = controller(manager_at(tmp_path), output := Output())
        writer = old._writer
        assert writer is not None
        new = None
        try:
            old.start((0.0,) * 10)
            await settled(qapp, writer)
            assert old.update_custom((3.0,) * 10)
            await EqualizerApoWriter.aclose_shared()
            new = controller(apo.EqualizerApoConfigManager(Registry(tmp_path)), output)
            replacement = new._writer
            assert replacement is not None and replacement is not writer
            new.start((0.0,) * 10)
            assert new.update_custom((6.0,) * 10)
            assert new.apply_custom()
            await settled(qapp, replacement)
            managed = tmp_path / "config" / apo.MANAGED_FILENAME
            before = managed.read_bytes()
            assert new.applied_gains == (6.0,) * 10
            assert replacement.target(new._target).draft_owner is None
            accepted = old.apply_custom()
            await settled(qapp, replacement)
            assert (accepted, managed.read_bytes()) == (False, before)
            assert old.has_draft and old.gains == (3.0,) * 10
            assert old.applied_gains == (0.0,) * 10
            assert not old.update_custom((4.0,) * 10)
            assert not old.apply_preset((4.0,) * 10)
            assert old.draft_needs_review
            old.review_custom()
            assert old.gains == (6.0,) * 10 and not old.has_draft
            assert managed.read_bytes() == before
            assert old.update_custom((4.0,) * 10)
            assert replacement.target(old._target).draft_owner is old._draft_token
            assert old.apply_custom()
            await settled(qapp, replacement)
            assert old.applied_gains == (4.0,) * 10
        finally:
            old.shutdown()
            if new is not None:
                new.shutdown()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_fresh_destination_lease_blocks_stale_view_preset_and_retry(tmp_path: Path, qapp: QApplication) -> None:
    async def run() -> None:
        registry = Registry(tmp_path / "a")
        manager_at(tmp_path / "a")
        first = controller(apo.EqualizerApoConfigManager(registry), Output())
        second = controller(manager_at(tmp_path / "c"), Output())
        writer = first._writer
        assert writer is not None
        try:
            first.start((1.0,) * 10)
            second.start((2.0,) * 10)
            await settled(qapp, writer)
            assert second.update_custom((8.0,) * 10)
            generation = writer._generation
            registry.values["ConfigPath"] = str(tmp_path / "c/config")
            assert not first.apply_preset((3.0,) * 10)
            assert not first.apply_custom()
            assert not first.update_custom((4.0,) * 10)
            assert writer._generation == generation
            assert second.has_draft and second.gains == (8.0,) * 10
            assert writer.target(second._target).draft_owner is second._draft_token
        finally:
            first.shutdown()
            second.shutdown()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


@pytest.mark.parametrize("rebind", [False, True])
def test_commit_notification_cannot_release_a_newer_same_view_draft(
    tmp_path: Path, qapp: QApplication, rebind: bool
) -> None:
    async def run() -> None:
        client = controller(manager_at(tmp_path), Output())
        writer = client._writer
        assert writer is not None
        try:
            client.start((1.0,) * 10)
            await settled(qapp, writer)
            client.update_custom((3.0,) * 10)
            old_token = client._draft_token
            if rebind:
                await EqualizerApoWriter.aclose_shared()
                client.reconnect_writer()
                writer = client._writer
                assert writer is not None
            began = False
            premature_reclaim = False

            def edit_during_commit(key: str) -> None:
                nonlocal began, premature_reclaim
                assert writer is not None
                target = writer.target(key)
                if not began and (target.intent is None or target.intent.gains == (3.0,) * 10):
                    premature_reclaim = target.intent is None
                    began = True
                    if premature_reclaim:
                        client.discard_custom()
                    assert client.update_custom((4.0,) * 10)

            writer.changed.connect(edit_during_commit)
            assert client.apply_custom()
            await settled(qapp, writer)
            assert began and not premature_reclaim and client.has_draft and client.gains == (4.0,) * 10
            assert client.applied_gains == (3.0,) * 10
            assert client._draft_target == client._target
            assert client._draft_token is not old_token
            assert writer.target(client._target).draft_owner is client._draft_token
        finally:
            client.shutdown()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_visual_only_apply_and_discard_never_create_writer(qapp: QApplication) -> None:
    client = EqualizerApoController(MediaEqualizerConfig(), output_service=cast(DefaultAudioOutputService, Output()))
    try:
        client.start((1.0,) * 10)
        assert client.update_custom((3.0,) * 10, final=True)
        assert client.has_draft and client.pending
        client.discard_custom()
        assert client.gains == (1.0,) * 10 and not client.has_draft
        client.update_custom((2.0,) * 10)
        assert client.apply_custom()
        assert client.gains == (2.0,) * 10 and not client.has_draft
        assert client.applied_state is None and client._writer is None
    finally:
        client.shutdown()


def test_apply_commits_one_complete_curve_and_discard_never_writes(tmp_path: Path, qapp: QApplication) -> None:
    async def run() -> None:
        client = controller(manager_at(tmp_path), Output())
        writer = client._writer
        assert writer is not None
        try:
            client.start((0.0,) * 10)
            await settled(qapp, writer)
            generation = writer._generation
            client.update_custom(tuple(float(x) for x in range(10)))
            client.update_custom((4.0,) * 10, final=True)
            assert client.has_draft
            assert client.apply_custom()
            await settled(qapp, writer)
            assert writer._generation == generation + 1
            assert client.applied_gains == (4.0,) * 10
            assert not client.has_draft and not client.pending
            generation = writer._generation
            client.update_custom((-3.0,) * 10, final=True)
            client.discard_custom()
            assert not client.has_draft
            assert client.gains == client.applied_gains == (4.0,) * 10
            assert writer._generation == generation
        finally:
            client.shutdown()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_foreign_view_cannot_overwrite_or_discard_active_draft(tmp_path: Path, qapp: QApplication) -> None:
    async def run() -> None:
        first = controller(manager_at(tmp_path), output := Output())
        second = controller(apo.EqualizerApoConfigManager(Registry(tmp_path)), output)
        writer = first._writer
        assert writer is not None
        try:
            first.start((1.0,) * 10)
            await settled(qapp, writer)
            second.start((0.0,) * 10)
            assert first.update_custom((5.0,) * 10)
            assert not second.draft_available
            assert not second.update_custom((9.0,) * 10, final=True)
            assert not second.apply_preset((-2.0,) * 10)
            second.discard_custom()
            assert first.has_draft and first.gains == (5.0,) * 10
            assert writer.target(first._target).draft_owner is first._draft_token
            first.shutdown()
            assert second.draft_available
            assert second.update_custom((2.0,) * 10)
            assert second.apply_custom()
            await settled(qapp, writer)
            assert second.applied_gains == (2.0,) * 10
        finally:
            first.shutdown()
            second.shutdown()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_output_retarget_uses_committed_curve_while_draft_is_local(tmp_path: Path, qapp: QApplication) -> None:
    async def run() -> None:
        client = controller(manager_at(tmp_path), output := Output())
        writer = client._writer
        assert writer is not None
        try:
            client.start((1.0,) * 10)
            await settled(qapp, writer)
            client.update_custom((9.0,) * 10)
            output.state = replace(OUTPUT, endpoint_guid="{11111111-1111-1111-1111-111111111111}")
            output.default_output_changed.emit(output.state)
            await settled(qapp, writer)
            assert client.has_draft and client.gains == (9.0,) * 10
            assert client.applied_gains == (1.0,) * 10
            assert client.applied_state is not None and client.applied_state.output == output.state
            client.discard_custom()
            assert client.gains == (1.0,) * 10
        finally:
            client.shutdown()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_failed_apply_preserves_curve_and_retry_requires_explicit_action(
    tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        client = controller(manager_at(tmp_path), Output())
        writer = client._writer
        assert writer is not None
        try:
            client.start((0.0,) * 10)
            await settled(qapp, writer)
            write = apo.atomic_write_text
            failed = False

            def fail_once(path: Path, text: str, encoding: str = "utf-8") -> None:
                nonlocal failed
                if not failed:
                    failed = True
                    raise PermissionError("Owned test failure")
                write(path, text, encoding)

            monkeypatch.setattr(apo, "atomic_write_text", fail_once)
            client.update_custom((4.0,) * 10)
            client.apply_custom()
            await settled(qapp, writer)
            assert client.write_failed and client.pending
            assert client.gains == (4.0,) * 10 and client.applied_gains == (0.0,) * 10
            generation = writer._generation
            await asyncio.sleep(0.15)
            qapp.processEvents()
            assert writer._generation == generation
            client.apply_custom()
            await settled(qapp, writer)
            assert client.applied_gains == (4.0,) * 10
            assert not client.write_failed and not client.pending
        finally:
            client.shutdown()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_same_curve_edit_has_no_draft_and_preset_is_immediate(tmp_path: Path, qapp: QApplication) -> None:
    async def run() -> None:
        client = controller(manager_at(tmp_path), Output())
        writer = client._writer
        assert writer is not None
        try:
            client.start((0.0,) * 10)
            await settled(qapp, writer)
            generation = writer._generation
            client.update_custom((3.0,) * 10)
            client.update_custom((0.0,) * 10)
            assert not client.has_draft
            assert writer.target(client._target).draft_owner is None
            assert writer._generation == generation
            client.update_custom((8.0,) * 10)
            client.apply_preset((2.0,) * 10)
            await settled(qapp, writer)
            assert client.gains == client.applied_gains == (2.0,) * 10
            assert not client.has_draft
        finally:
            client.shutdown()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_target_change_discards_old_draft_without_implicit_write(tmp_path: Path, qapp: QApplication) -> None:
    async def run() -> None:
        registry = Registry(tmp_path / "a")
        manager_at(tmp_path / "a")
        manager_at(tmp_path / "b")
        client = controller(apo.EqualizerApoConfigManager(registry), Output())
        writer = client._writer
        assert writer is not None
        try:
            client.start((1.0,) * 10)
            await settled(qapp, writer)
            client.update_custom((5.0,) * 10)
            generation = writer._generation
            registry.values["ConfigPath"] = str(tmp_path / "b/config")
            assert not client.apply_custom()
            assert not client.has_draft and client.gains == (1.0,) * 10
            assert writer._generation == generation
            assert not (tmp_path / "b/config" / apo.MANAGED_FILENAME).exists()
            client.update_custom((2.0,) * 10)
            assert client.apply_custom()
            await settled(qapp, writer)
            assert client.applied_gains == (2.0,) * 10
        finally:
            client.shutdown()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_panel_apply_button_and_tab_hide_discard(
    tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        manager, output = manager_at(tmp_path), Output()

        def client(options: MediaEqualizerConfig, parent: QObject | None = None) -> EqualizerApoController:
            return EqualizerApoController(
                options, parent, manager=manager, output_service=cast(DefaultAudioOutputService, output)
            )

        monkeypatch.setattr(panel_module, "EqualizerApoController", client)
        panel = panel_module.EqualizerPanel(
            MediaEqualizerConfig.model_validate({"backend": "equalizer_apo", "apo": {"enabled": True}}), 1
        )
        stack = QStackedWidget()
        stack.addWidget(panel)
        stack.addWidget(other := QWidget())
        writer = panel.apo._writer
        assert writer is not None
        try:
            stack.show()
            await settled(qapp, writer)
            slider = panel.bands.sliders[0]
            slider.setValue(4 * slider.SCALE)
            assert panel.apo.has_draft
            assert panel.apply_button.text() == "Apply" and panel.apply_button.isEnabled()
            panel.apply_button.click()
            await settled(qapp, writer)
            assert panel.apply_button.text() == "Saved" and not panel.apply_button.isEnabled()
            generation = writer._generation
            slider.setValue(7 * slider.SCALE)
            assert panel.apo.has_draft
            stack.setCurrentWidget(other)
            qapp.processEvents()
            assert not panel.apo.has_draft
            assert writer._generation == generation
            assert panel.apo.gains == panel.apo.applied_gains
        finally:
            panel.apo.shutdown()
            stack.close()
            stack.deleteLater()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


@pytest.mark.parametrize("owner_already_replaced", [False, True])
def test_panel_reconnects_without_writing_and_applies_unchanged_base(
    tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, owner_already_replaced: bool
) -> None:
    async def run() -> None:
        manager, output = manager_at(tmp_path), Output()

        def client(options: MediaEqualizerConfig, parent: QObject | None = None) -> EqualizerApoController:
            return EqualizerApoController(
                options, parent, manager=manager, output_service=cast(DefaultAudioOutputService, output)
            )

        monkeypatch.setattr(panel_module, "EqualizerApoController", client)
        panel = panel_module.EqualizerPanel(
            MediaEqualizerConfig.model_validate({"backend": "equalizer_apo", "apo": {"enabled": True}}), 1
        )
        writer = panel.apo._writer
        assert writer is not None
        entered, release = threading.Event(), threading.Event()

        def hold_shutdown() -> None:
            entered.set()
            assert release.wait(5)

        try:
            panel.show()
            await settled(qapp, writer)
            monkeypatch.setattr(writer, "_close_native", hold_shutdown)
            managed = tmp_path / "config" / apo.MANAGED_FILENAME
            before = managed.read_bytes()
            slider = panel.bands.sliders[0]
            slider.setValue(4 * slider.SCALE)
            assert panel.apo.has_draft
            old_token = panel.apo._draft_token
            drain = asyncio.create_task(EqualizerApoWriter.aclose_shared())
            await until(entered.is_set)
            assert not drain.done()
            assert not panel.apo.apply_custom()
            assert panel.apply_button.text() == "Reconnect" and panel.apply_button.isEnabled()
            panel.apply_button.click()
            assert not panel.apo.writer_available and panel.apo.has_draft
            assert panel.apo.gains[0] == 4 and managed.read_bytes() == before
            assert EqualizerApoWriter.shared_instance() is writer
            release.set()
            await drain
            if owner_already_replaced:
                EqualizerApoWriter.shared()
            assert panel.apply_button.text() == "Reconnect"
            panel.apply_button.click()
            replacement = panel.apo._writer
            assert replacement is not None and replacement is not writer
            assert replacement._generation == 0 and managed.read_bytes() == before
            assert not panel.apo.update_custom((5.0,) * 10, expected_draft=old_token)
            assert replacement.target(panel.apo._target).draft_owner is None
            assert panel.apply_button.text() == "Apply" and panel.apply_button.isEnabled()
            panel.apply_button.click()
            await settled(qapp, replacement)
            assert panel.apo._draft_token is not old_token
            assert panel.apo.applied_gains is not None and panel.apo.applied_gains[0] == 4
            assert managed.read_bytes() != before

            slider.setValue(8 * slider.SCALE)
            assert panel.apo.has_draft
            await EqualizerApoWriter.aclose_shared()
            new = controller(apo.EqualizerApoConfigManager(Registry(tmp_path)), output)
            try:
                new.start((0.0,) * 10)
                assert new.apply_preset((6.0,) * 10)
                latest = new._writer
                assert latest is not None
                await settled(qapp, latest)
                before = managed.read_bytes()
                panel._sync_apply()
                assert panel.apply_button.text() == "Review" and panel.apply_button.isEnabled()
                assert not slider.isEnabled() and panel.apo.gains[0] == 8
                panel.apply_button.click()
                assert panel.apo.gains == (6.0,) * 10 and not panel.apo.has_draft
                assert slider.isEnabled() and managed.read_bytes() == before
                slider.setValue(9 * slider.SCALE)
                assert panel.apo.has_draft and latest.target(panel.apo._target).draft_owner is panel.apo._draft_token
            finally:
                new.shutdown()
        finally:
            release.set()
            panel.apo.shutdown()
            panel.close()
            panel.deleteLater()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())
