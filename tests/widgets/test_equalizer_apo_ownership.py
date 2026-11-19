# pyright: reportPrivateUsage=false

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import cast

import PyQt6.sip as sip
import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from core.validation.widgets.yasb.media_v2 import MediaEqualizerApoConfig, MediaEqualizerConfig
from core.widgets.services.media import equalizer_apo as apo
from core.widgets.services.media.audio_device import AudioOutputState, DefaultAudioOutputService
from core.widgets.services.media.equalizer_apo import (
    MANAGED_FILENAME,
    EqualizerApoConfigManager,
    EqualizerApoController,
    EqualizerApoWriter,
    render_managed_config,
)
from core.widgets.yasb import media_v2_equalizer as panel_module
from tests.widgets.test_equalizer_apo_recovery import BLOCK, OUTPUT, Registry


def test_writer_shared_recreates_after_direct_shutdown(qapp: QApplication) -> None:
    previous = EqualizerApoWriter._shared
    writer = EqualizerApoWriter()
    EqualizerApoWriter._shared = writer
    try:
        writer.shutdown()
        replacement = EqualizerApoWriter.shared()
        assert replacement is not writer
        assert not replacement.closed
        replacement.shutdown()
    finally:
        EqualizerApoWriter._shared = previous
        EqualizerApoWriter._closing = False


def test_writer_shared_recreates_after_deleted_qobject(qapp: QApplication) -> None:
    previous = EqualizerApoWriter._shared
    writer = EqualizerApoWriter()
    EqualizerApoWriter._shared = writer
    replacement: EqualizerApoWriter | None = None
    try:
        writer.shutdown()
        sip.delete(writer)
        replacement = EqualizerApoWriter.shared()
        assert replacement is not writer
        assert not replacement.closed
    finally:
        if replacement is not None:
            replacement.shutdown()
        EqualizerApoWriter._shared = previous
        EqualizerApoWriter._closing = False


def test_controller_reacquires_closed_writer(qapp: QApplication, tmp_path: Path) -> None:
    previous = EqualizerApoWriter._shared
    first = EqualizerApoWriter()
    replacement = EqualizerApoWriter()
    EqualizerApoWriter._shared = first
    client = controller(manager_at(tmp_path), Output())
    try:
        assert client._writer is first
        first.shutdown()
        EqualizerApoWriter._shared = replacement
        assert client.pending is False
        assert client._writer is replacement
    finally:
        client.shutdown()
        first.shutdown()
        replacement.shutdown()
        EqualizerApoWriter._shared = previous
        EqualizerApoWriter._closing = False


def test_controller_replaces_deleted_output_service(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replacement = Output()
    deleted = DefaultAudioOutputService.__new__(DefaultAudioOutputService)
    QObject.__init__(deleted)
    sip.delete(deleted)
    monkeypatch.setattr(DefaultAudioOutputService, "instance", staticmethod(lambda: replacement))
    previous = EqualizerApoWriter._shared
    client = controller(manager_at(tmp_path), cast(Output, deleted))
    try:
        assert client._output is replacement
    finally:
        writer = client._writer
        client.shutdown()
        if writer is not None:
            writer.shutdown()
        EqualizerApoWriter._shared = previous
        EqualizerApoWriter._closing = False


def test_independent_managers_a_b_a_persist_a(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.txt").write_text(BLOCK)
    first, second = EqualizerApoConfigManager(Registry(tmp_path)), EqualizerApoConfigManager(Registry(tmp_path))
    options = MediaEqualizerApoConfig()
    a, b = (3.0,) * 10, (-3.0,) * 10
    assert first.apply(a, OUTPUT, options).applied
    assert second.apply(b, OUTPUT, options).applied
    assert first.apply(a, OUTPUT, options).applied
    assert (config / MANAGED_FILENAME).read_bytes() == render_managed_config(a, OUTPUT.endpoint_guid).encode()


def manager_at(root: Path) -> EqualizerApoConfigManager:
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "config.txt").write_text(BLOCK)
    return EqualizerApoConfigManager(Registry(root))


class Output(QObject):
    default_output_changed = pyqtSignal(object)
    state = OUTPUT

    def request_refresh(self) -> None:
        pass


async def settled(qapp: QApplication, writer: EqualizerApoWriter) -> None:
    async with asyncio.timeout(5):
        while writer._running is not None or writer._pending:
            qapp.processEvents()
            await asyncio.sleep(0.001)
        qapp.processEvents()


def controller(manager: EqualizerApoConfigManager, output: Output, **options: object) -> EqualizerApoController:
    config = MediaEqualizerConfig.model_validate({"backend": "equalizer_apo", "apo": {"enabled": True, **options}})
    return EqualizerApoController(config, output_service=cast(DefaultAudioOutputService, output), manager=manager)


@pytest.mark.parametrize("change", ["overwrite", "delete"])
def test_dedup_validates_actual_file(tmp_path: Path, change: str) -> None:
    manager = manager_at(tmp_path)
    options = MediaEqualizerApoConfig()
    values = (2.0,) * 10
    assert manager.apply(values, OUTPUT, options).applied
    path = tmp_path / "config" / MANAGED_FILENAME
    if change == "overwrite":
        path.write_bytes(b"external edit")
    else:
        path.unlink()
    result = manager.apply(values, OUTPUT, options)
    assert result.applied and result.state is not None
    assert path.read_bytes() == render_managed_config(values, OUTPUT.endpoint_guid).encode()


def test_direct_transactions_include_parent_and_backup_serialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = manager_at(tmp_path)
    second = EqualizerApoConfigManager(Registry(tmp_path))
    parent = tmp_path / "config/config.txt"
    original = b"# original owned bytes\r\n"
    parent.write_bytes(original)
    entered, release = threading.Event(), threading.Event()
    lock = threading.Lock()
    active = peak = 0
    writes = 0
    write = apo.atomic_write_text

    def held(path: Path, text: str, encoding: str = "utf-8") -> None:
        nonlocal active, peak, writes
        with lock:
            active += 1
            peak = max(peak, active)
            writes += 1
        entered.set()
        try:
            assert release.wait(5)
            write(path, text, encoding)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(apo, "atomic_write_text", held)
    options = MediaEqualizerApoConfig(manage_include=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(first.apply, (2.0,) * 10, OUTPUT, options)
        try:
            assert entered.wait(3)
            b = pool.submit(second.apply, (-2.0,) * 10, OUTPUT, options)
            assert not b.done()
        finally:
            release.set()
        assert a.result().applied and b.result().applied
    assert peak == 1 and active == 0 and writes == 3
    assert (tmp_path / "config" / apo.BACKUP_FILENAME).read_bytes() == original


def test_two_clients_coalesce_and_closing_client_preserves_writer(
    tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        manager = manager_at(tmp_path)
        output = Output()
        first, second = controller(manager, output), controller(EqualizerApoConfigManager(Registry(tmp_path)), output)
        writer = first._writer
        assert writer is not None and writer is second._writer
        entered, release = threading.Event(), threading.Event()
        calls: list[tuple[float, ...]] = []
        apply = EqualizerApoConfigManager.apply

        def held(
            owner: EqualizerApoConfigManager,
            gains: tuple[float, ...],
            device: AudioOutputState,
            options: apo.ApoWriteOptions,
        ) -> apo.ApoApplyResult:
            calls.append(gains)
            entered.set()
            assert release.wait(5)
            return apply(owner, gains, device, options)

        monkeypatch.setattr(EqualizerApoConfigManager, "apply", held)
        try:
            first.start((1.0,) * 10)
            async with asyncio.timeout(3):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            second.start((0.0,) * 10)  # Hydration must not queue/reset to its configured Flat.
            assert second.gains == (1.0,) * 10
            first.apply_preset((2.0,) * 10)
            second.apply_preset((3.0,) * 10)
            first.shutdown()
            second.shutdown()
            reopened = controller(EqualizerApoConfigManager(Registry(tmp_path)), output)
            reopened.start((0.0,) * 10)
            assert reopened._writer is writer and reopened.gains == (3.0,) * 10
            release.set()
            await settled(qapp, writer)
            assert calls == [(1.0,) * 10, (3.0,) * 10]
            assert reopened.applied_gains == (3.0,) * 10
            assert not reopened.pending
            assert reopened.applied_state is not None
            assert reopened.applied_state == writer.target(reopened._target).applied
            reopened.shutdown()
        finally:
            release.set()
            first.shutdown()
            second.shutdown()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_option_snapshot_endpoint_change_and_shared_failure_state(
    tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        first = controller(manager_at(tmp_path), output := Output(), auto_preamp=False, preamp_db=-2)
        second = controller(EqualizerApoConfigManager(Registry(tmp_path)), output, auto_preamp=False, preamp_db=-8)
        writer = first._writer
        assert writer is not None
        try:
            first.start((1.0,) * 10)
            first.apo_options.preamp_db = -11
            await settled(qapp, writer)
            path = tmp_path / "config" / MANAGED_FILENAME
            assert b"Preamp: -2 dB" in path.read_bytes()
            second.start((0.0,) * 10)
            assert first.applied_state == second.applied_state
            second.apply_preset((1.0,) * 10)
            await settled(qapp, writer)
            assert b"Preamp: -8 dB" in path.read_bytes()
            first._editing_gains = (9.0,) * 10
            first._dirty = True  # A local draft must not retarget this stale/local curve.
            output.state = replace(OUTPUT, endpoint_guid="{11111111-1111-1111-1111-111111111111}")
            output.default_output_changed.emit(output.state)
            await settled(qapp, writer)
            assert output.state.endpoint_guid.encode() in path.read_bytes()
            assert b"31 1;" in path.read_bytes()
            assert b"Preamp: -8 dB" in path.read_bytes()
            previous = first.applied_state

            def denied(path: Path, text: str, encoding: str = "utf-8") -> None:
                raise PermissionError("Owned injected denial")

            monkeypatch.setattr(apo, "atomic_write_text", denied)
            second.apply_preset((4.0,) * 10)
            await settled(qapp, writer)
            assert first.applied_state == second.applied_state == previous
            assert first.write_failed and second.write_failed
            assert first.pending and second.pending
        finally:
            first.shutdown()
            second.shutdown()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_first_enabled_panel_hydrates_and_second_panel_does_not_write(
    tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        manager, output = manager_at(tmp_path), Output()

        def client(options: MediaEqualizerConfig, parent: QObject | None = None) -> EqualizerApoController:
            return EqualizerApoController(
                options, parent, manager=manager, output_service=cast(DefaultAudioOutputService, output)
            )

        monkeypatch.setattr(panel_module, "EqualizerApoController", client)
        first = panel_module.EqualizerPanel(
            MediaEqualizerConfig.model_validate(
                {"preset": "Bass", "backend": "equalizer_apo", "apo": {"enabled": True}}
            ),
            1,
        )
        writer = first.apo._writer
        assert writer is not None
        try:
            await settled(qapp, writer)
            assert tuple(s.gain for s in first.bands.sliders) == tuple(panel_module.PRESETS["Bass"])
            generation = writer._generation
            second = panel_module.EqualizerPanel(
                MediaEqualizerConfig.model_validate(
                    {"preset": "Flat", "backend": "equalizer_apo", "apo": {"enabled": True}}
                ),
                1,
            )
            try:
                assert second.preset == "Bass"
                assert tuple(s.gain for s in second.bands.sliders) == tuple(panel_module.PRESETS["Bass"])
                assert writer._generation == generation
                assert first.apo.applied_state == second.apo.applied_state
            finally:
                second.apo.shutdown()
                second.deleteLater()
        finally:
            first.apo.shutdown()
            first.deleteLater()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_aliases_share_state_and_distinct_files_keep_independent_state(tmp_path: Path, qapp: QApplication) -> None:
    async def run() -> None:
        root = tmp_path / "first"
        manager = manager_at(root)
        alias_registry = Registry(root / "config" / "..")
        alias = EqualizerApoConfigManager(alias_registry)
        output = Output()
        first, second = controller(manager, output), controller(alias, output)
        other = controller(manager_at(tmp_path / "other"), output)
        writer = first._writer
        assert writer is not None
        try:
            assert manager.target_key() == alias.target_key()
            first.start((2.0,) * 10)
            second.start((0.0,) * 10)
            other.start((-2.0,) * 10)
            await settled(qapp, writer)
            assert first.applied_state == second.applied_state
            assert other.applied_state is not None and first.applied_state is not None
            assert other.applied_state.target != first.applied_state.target
            assert other.applied_gains == (-2.0,) * 10
            assert first.applied_gains == (2.0,) * 10
            # A delayed notification cannot replace a newer persisted revision.
            older = first.applied_state
            first.apply_preset((4.0,) * 10)
            await settled(qapp, writer)
            current = first.applied_state
            writer._on_state(older)
            assert first.applied_state == second.applied_state == current
        finally:
            first.shutdown()
            second.shutdown()
            other.shutdown()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_shutdown_keeps_owner_until_actual_worker_is_joined(
    tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        client = controller(manager_at(tmp_path), Output())
        writer = client._writer
        assert writer is not None
        entered, release = threading.Event(), threading.Event()
        write = apo.atomic_write_text

        def held(path: Path, text: str, encoding: str = "utf-8") -> None:
            entered.set()
            assert release.wait(5)
            write(path, text, encoding)

        monkeypatch.setattr(apo, "atomic_write_text", held)
        client.start((1.0,) * 10)
        async with asyncio.timeout(3):
            while not entered.is_set():
                await asyncio.sleep(0.001)
        closing = asyncio.create_task(EqualizerApoWriter.aclose_shared())
        try:
            await asyncio.sleep(0)
            assert writer._closed and not closing.done()
            assert EqualizerApoWriter.shared() is writer
            queued = writer._generation
            client.apply_preset((8.0,) * 10)
            assert writer._generation == queued
            release.set()
            await closing
            qapp.processEvents()
            assert EqualizerApoWriter._shared is None
            assert writer._running is None
            assert not writer._pending
        finally:
            release.set()
            client.shutdown()
            await closing

    asyncio.run(run())


def test_canceled_writer_drain_keeps_shared_owner_until_worker_finishes(
    tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        client = controller(manager_at(tmp_path), Output())
        writer = client._writer
        assert writer is not None
        entered, release = threading.Event(), threading.Event()
        write = apo.atomic_write_text

        def held(path: Path, text: str, encoding: str = "utf-8") -> None:
            entered.set()
            assert release.wait(5)
            write(path, text, encoding)

        monkeypatch.setattr(apo, "atomic_write_text", held)
        client.start((1.0,) * 10)
        async with asyncio.timeout(3):
            while not entered.is_set():
                await asyncio.sleep(0.001)
        closing = asyncio.create_task(EqualizerApoWriter.aclose_shared())
        try:
            await asyncio.sleep(0)
            assert writer._closed and not closing.done()
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
            assert EqualizerApoWriter.shared() is writer
            release.set()
            await EqualizerApoWriter.aclose_shared()
            assert EqualizerApoWriter._shared is None
        finally:
            release.set()
            client.shutdown()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_pending_target_a_b_a_preserves_latest_global_order(
    tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        registry = Registry(tmp_path / "a")
        manager_at(tmp_path / "a")
        manager_at(tmp_path / "b")
        manager = EqualizerApoConfigManager(registry)
        client = controller(manager, Output())
        writer = client._writer
        assert writer is not None
        entered, release = threading.Event(), threading.Event()
        apply = EqualizerApoConfigManager.apply
        seen: list[float] = []

        def held(
            owner: EqualizerApoConfigManager,
            gains: tuple[float, ...],
            device: AudioOutputState,
            options: apo.ApoWriteOptions,
        ) -> apo.ApoApplyResult:
            seen.append(gains[0])
            entered.set()
            assert release.wait(5)
            return apply(owner, gains, device, options)

        monkeypatch.setattr(EqualizerApoConfigManager, "apply", held)
        try:
            client.start((1.0,) * 10)
            async with asyncio.timeout(3):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            client.apply_preset((2.0,) * 10)
            registry.values["ConfigPath"] = str(tmp_path / "b/config")
            client.apply_preset((3.0,) * 10)
            registry.values["ConfigPath"] = str(tmp_path / "a/config")
            client.apply_preset((4.0,) * 10)
            release.set()
            await settled(qapp, writer)
            assert seen == [1, 3, 4]
            assert client.applied_gains == (4.0,) * 10
            assert not client.pending
            assert (tmp_path / "a/config" / MANAGED_FILENAME).read_bytes() == render_managed_config(
                (4.0,) * 10, OUTPUT.endpoint_guid
            ).encode()
        finally:
            release.set()
            client.shutdown()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_output_change_cannot_revive_older_intent_from_historical_target(tmp_path: Path, qapp: QApplication) -> None:
    async def run() -> None:
        registry = Registry(tmp_path / "a")
        manager_at(tmp_path / "a")
        manager_at(tmp_path / "b")
        output = Output()
        client = controller(EqualizerApoConfigManager(registry), output)
        writer = client._writer
        assert writer is not None
        try:
            client.start((1.0,) * 10)
            await settled(qapp, writer)
            registry.values["ConfigPath"] = str(tmp_path / "b/config")
            client.apply_preset((2.0,) * 10)
            await settled(qapp, writer)
            registry.values["ConfigPath"] = str(tmp_path / "a/config")
            client.apply_preset((3.0,) * 10)
            await settled(qapp, writer)
            output.state = replace(OUTPUT, endpoint_guid="{11111111-1111-1111-1111-111111111111}")
            output.default_output_changed.emit(output.state)
            await settled(qapp, writer)
            assert client.applied_gains == client.gains == (3.0,) * 10
            assert not client.pending
            assert (tmp_path / "a/config" / MANAGED_FILENAME).read_bytes() == render_managed_config(
                (3.0,) * 10, output.state.endpoint_guid
            ).encode()
            active = [target.intent for target in writer._targets.values() if target.intent is not None]
            assert len(active) == 1 and active[0].gains == (3.0,) * 10
        finally:
            client.shutdown()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


@pytest.mark.parametrize("reentrant", [False, True])
def test_late_discovery_migration_restores_newer_explicit_destination_intent(
    tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, reentrant: bool
) -> None:
    async def run() -> None:
        registry = Registry(tmp_path / "a")
        manager_at(tmp_path / "a")
        first_output, second_output = Output(), Output()
        first = controller(EqualizerApoConfigManager(registry), first_output)
        second = controller(manager_at(tmp_path / "b"), second_output)
        writer = first._writer
        assert writer is not None
        entered, release = threading.Event(), threading.Event()
        apply = EqualizerApoConfigManager.apply
        try:
            first.start((1.0,) * 10)
            await settled(qapp, writer)
            second.start((2.0,) * 10)
            await settled(qapp, writer)
            submitted = False

            def commit_during_notification(key: str) -> None:
                nonlocal submitted
                if (
                    reentrant
                    and not submitted
                    and writer._running is None
                    and key == second._target
                    and second.applied_gains == (1.0,) * 10
                ):
                    submitted = True
                    second.apply_preset((3.0,) * 10)

            writer.changed.connect(commit_during_notification)

            def held(
                owner: EqualizerApoConfigManager,
                gains: tuple[float, ...],
                device: AudioOutputState,
                options: apo.ApoWriteOptions,
            ) -> apo.ApoApplyResult:
                if owner is first._manager:
                    entered.set()
                    assert release.wait(5)
                return apply(owner, gains, device, options)

            monkeypatch.setattr(EqualizerApoConfigManager, "apply", held)
            first_output.state = replace(OUTPUT, endpoint_guid="{11111111-1111-1111-1111-111111111111}")
            first_output.default_output_changed.emit(first_output.state)
            async with asyncio.timeout(3):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            registry.values["ConfigPath"] = str(tmp_path / "b/config")
            release.set()
            await settled(qapp, writer)
            expected = (3.0 if reentrant else 2.0,) * 10
            assert submitted is reentrant
            assert first.applied_gains == second.applied_gains == expected
            assert not first.pending and not second.pending
            assert (tmp_path / "b/config" / MANAGED_FILENAME).read_bytes() == render_managed_config(
                expected, OUTPUT.endpoint_guid
            ).encode()
        finally:
            release.set()
            first.shutdown()
            second.shutdown()
            await EqualizerApoWriter.aclose_shared()

    asyncio.run(run())
