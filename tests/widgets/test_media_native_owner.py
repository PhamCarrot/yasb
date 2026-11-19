# pyright: reportPrivateUsage=false
"""Native route through the real shared writer, owned profiles/APO fixtures only."""

import asyncio
import base64
import hashlib
import json
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import cast

import psutil
import pytest
from PyQt6.QtWidgets import QApplication

from core import config as config_module
from core.validation.widgets.yasb.media_v2 import MediaEqualizerApoConfig, MediaEqualizerConfig
from core.widgets.services.media import equalizer_apo as apo
from core.widgets.services.media.audio_device import DefaultAudioOutputService
from core.widgets.services.media.native_api import NativeBootstrap, NativeParameters
from core.widgets.services.media.native_route import NativeApoRoute, NativeAudioState, NativeRouteOptions, canonical
from tests.widgets.test_equalizer_apo_ownership import Output, manager_at, settled
from tests.widgets.test_equalizer_apo_recovery import OUTPUT
from tests.widgets.test_media_native_dsp import native_host as native_host
from tests.widgets.test_media_native_transport import child, finish

pytestmark = pytest.mark.sdk


def options(native_host: tuple[Path, Path], folder: Path) -> apo.ApoWriteOptions:
    dll = native_host[1]
    return apo.ApoWriteOptions(
        True,
        0,
        False,
        "native",
        NativeRouteOptions(canonical(folder / "profile"), str(dll), hashlib.sha256(dll.read_bytes()).hexdigest()),
    )


def load_record(route: NativeApoRoute) -> tuple[NativeBootstrap, NativeParameters]:
    record = json.loads(route.record_path.read_text(encoding="utf-8"))
    return NativeBootstrap.unpack(base64.b64decode(record["bootstrap"])), NativeParameters.unpack(
        base64.b64decode(record["parameters"])
    )


def test_default_graphic_eq_is_identical_and_never_loads_native(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("GraphicEQ must not construct a native route")

    monkeypatch.setattr(apo, "NativeApoRoute", unexpected)
    manager = manager_at(tmp_path)
    values = (3.0,) * 10
    assert manager.apply(values, OUTPUT, MediaEqualizerApoConfig()).applied
    assert (tmp_path / "config" / apo.MANAGED_FILENAME).read_bytes() == apo.render_managed_config(
        values, OUTPUT.endpoint_guid
    ).encode()
    assert not (tmp_path / "profile").exists()


def test_native_actions_persist_whole_state_without_watched_file_reload(
    native_host: tuple[Path, Path], tmp_path: Path
) -> None:
    manager = manager_at(tmp_path)
    target = Path(manager.target_key())
    old = b"# owned prior leaf\r\nGraphicEQ: 31 -2\r\n"
    target.write_bytes(old)
    opts = options(native_host, tmp_path)
    assert opts.native is not None
    route = NativeApoRoute(manager.target_key(), opts.native)
    try:
        first = manager.apply((2.0,) * 10, OUTPUT, opts, native=route, generation=1)
        assert first.applied and first.state is not None
        payload, modified = target.read_bytes(), target.stat().st_mtime_ns
        assert b"VSTPlugin:" in payload and b"GraphicEQ:" not in payload and b"Preamp:" not in payload
        assert b"Channel: L R" in payload
        assert target.with_suffix(".txt.yasb-native-backup").read_bytes() == old
        audio = NativeAudioState(balance=0.5, mono=True, swap=True, dynamics=2, adaptive=True)
        second = manager.apply((-3.0,) * 10, OUTPUT, opts, native=route, audio=audio, generation=2)
        assert second.applied and second.state is not None and second.state.audio == audio
        assert target.read_bytes() == payload and target.stat().st_mtime_ns == modified
        bootstrap, saved = load_record(route)
        assert bootstrap.initial.gains == (2.0,) * 10
        assert saved.gains == (-3.0,) * 10 and saved.preamp_db == 0 and saved.flags == 7 and saved.dynamics == 2
        assert route.record_path.with_suffix(".json.backup").is_file()
        # Only the actual optional DLL + synthetic fixture process consumes it.
        # Start from the ORIGINAL stable chunk: the resident broker must send
        # the newer whole state without modifying the watched file.
        process = child(native_host, bootstrap, tmp_path, seconds=1)
        try:
            deadline = time.monotonic() + 0.8
            while not route.observe(2).processing and time.monotonic() < deadline:
                time.sleep(0.02)
            assert route.observe(2).processing
        finally:
            result = finish(process)
        assert result["fingerprint"] == saved.fingerprint
        observation = route.observe(2)
        assert observation.persisted_revision == 2
        assert not route.observe(3).processing
    finally:
        route.close()


@pytest.mark.parametrize(
    "damage", ["invalid-json", "profile", "target", "library", "sha256", "build", "schema", "revision", "oversized"]
)
def test_unrecognizable_record_never_overwrites_files(
    native_host: tuple[Path, Path], tmp_path: Path, damage: str
) -> None:
    manager = manager_at(tmp_path)
    opts = options(native_host, tmp_path)
    assert opts.native is not None
    route = NativeApoRoute(manager.target_key(), opts.native)
    try:
        assert manager.apply((1.0,) * 10, OUTPUT, opts, native=route, generation=1).applied
        parent = tmp_path / "config/config.txt"
        target = Path(manager.target_key())
        before = (parent.read_bytes(), target.read_bytes())
        record = json.loads(route.record_path.read_text(encoding="utf-8"))
        if damage == "invalid-json":
            broken = "{"
        elif damage == "oversized":
            broken = " " * 32769
        else:
            record[damage] = "wrong" if damage in ("profile", "target", "library", "sha256") else 999
            broken = json.dumps(record)
        route.record_path.write_text(broken, encoding="utf-8")
        result = manager.apply((4.0,) * 10, OUTPUT, opts, native=route, generation=2)
        assert not result.applied and result.status == "Native DSP unavailable"
        assert (parent.read_bytes(), target.read_bytes()) == before
        assert route.record_path.read_text(encoding="utf-8") == broken
    finally:
        route.close()


def test_missing_or_wrong_native_artifact_fails_before_parent_mutation(
    native_host: tuple[Path, Path], tmp_path: Path
) -> None:
    manager = manager_at(tmp_path)
    parent = tmp_path / "config/config.txt"
    parent.write_text("# no managed include yet\n")
    opts = replace(options(native_host, tmp_path), manage_include=True)
    result = manager.apply((3.0,) * 10, OUTPUT, opts)
    assert not result.applied
    assert parent.read_text() == "# no managed include yet\n"
    assert not (tmp_path / "config" / apo.BACKUP_FILENAME).exists()
    assert opts.native is not None
    with pytest.raises(ValueError, match="manifest"):
        NativeApoRoute(manager.target_key(), replace(opts.native, sha256="0" * 64))


def test_endpoint_retarget_rewrites_bootstrap_and_fences_old_observation(
    native_host: tuple[Path, Path], tmp_path: Path
) -> None:
    manager = manager_at(tmp_path)
    opts = options(native_host, tmp_path)
    assert opts.native is not None
    route = NativeApoRoute(manager.target_key(), opts.native)
    try:
        assert manager.apply((1.0,) * 10, OUTPUT, opts, native=route, generation=1).applied
        old, _ = load_record(route)
        changed = replace(OUTPUT, endpoint_guid="{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}")
        assert manager.apply((2.0,) * 10, changed, opts, native=route, generation=2).applied
        new, _ = load_record(route)
        assert new.installation == old.installation and new.config == old.config and new.endpoint != old.endpoint
        assert new.initial.gains == (2.0,) * 10
        assert changed.endpoint_guid.encode() in Path(manager.target_key()).read_bytes()
        assert route.observe(1).reports == ()
    finally:
        route.close()


def make_controller(
    manager: apo.EqualizerApoConfigManager, output: Output, opts: apo.ApoWriteOptions
) -> apo.EqualizerApoController:
    assert opts.native is not None
    configuration = MediaEqualizerConfig(
        backend="equalizer_apo",
        apo=MediaEqualizerApoConfig(
            enabled=True, processor="native", native_library=opts.native.library, native_sha256=opts.native.sha256
        ),
    )
    return apo.EqualizerApoController(
        configuration, manager=manager, output_service=cast(DefaultAudioOutputService, output)
    )


def test_shared_audio_commit_does_not_consume_eq_draft_and_apply_merges_latest_audio(
    native_host: tuple[Path, Path], tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        opts = options(native_host, tmp_path)
        assert opts.native is not None
        monkeypatch.setattr(config_module, "HOME_CONFIGURATION_DIR", opts.native.profile)
        manager, output = manager_at(tmp_path), Output()
        first, second = make_controller(manager, output, opts), make_controller(manager, output, opts)
        writer = first._writer
        assert writer is not None
        try:
            first.start((1.0,) * 10)
            await settled(qapp, writer)
            second.start((9.0,) * 10)
            assert second.gains == (1.0,) * 10
            assert first.update_custom((5.0,) * 10)
            assert second.update_audio(balance=-0.5, dynamics=1)
            await settled(qapp, writer)
            assert first.has_draft and first.gains == (5.0,) * 10
            assert second.gains == (1.0,) * 10 and first.applied_gains == (1.0,) * 10
            assert first.audio_state.balance == -0.5 and first.audio_state.dynamics == 1
            assert first.apply_custom()
            await settled(qapp, writer)
            assert first.applied_gains == second.applied_gains == (5.0,) * 10
            assert first.audio_state == second.audio_state == NativeAudioState(balance=-0.5, dynamics=1)
            route = writer._native_routes[manager.target_key()]
            _, saved = load_record(route)
            assert saved.gains == (5.0,) * 10 and saved.preamp_db == -5
            assert saved.balance == -0.5 and saved.dynamics == 1
        finally:
            first.shutdown()
            second.shutdown()
            await apo.EqualizerApoWriter.aclose_shared()
        assert route.observe(3).reports == ()

    asyncio.run(run())


def test_restart_restores_committed_manual_and_audio_state(
    native_host: tuple[Path, Path], tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        manager, output = manager_at(tmp_path), Output()
        opts = options(native_host, tmp_path)
        assert opts.native is not None
        monkeypatch.setattr(config_module, "HOME_CONFIGURATION_DIR", opts.native.profile)
        first = make_controller(manager, output, opts)
        first.start((4.0,) * 10)
        writer = first._writer
        assert writer is not None
        await settled(qapp, writer)
        assert first.update_audio(mono=True, swap=True, dynamics=2, adaptive=True)
        await settled(qapp, writer)
        first.shutdown()
        await apo.EqualizerApoWriter.aclose_shared()
        # Model a fresh process: immutable manager snapshots do not survive it.
        apo.EqualizerApoConfigManager._states.clear()
        second = make_controller(manager, output, opts)
        second.start((0.0,) * 10)
        writer = second._writer
        assert writer is not None
        try:
            await settled(qapp, writer)
            assert second.gains == second.applied_gains == (4.0,) * 10
            assert second.audio_state == NativeAudioState(mono=True, swap=True, dynamics=2, adaptive=True)
            assert not second.pending
        finally:
            second.shutdown()
            await apo.EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_retry_after_parent_failure_keeps_prepared_installation(native_host: tuple[Path, Path], tmp_path: Path) -> None:
    manager = manager_at(tmp_path)
    parent = tmp_path / "config/config.txt"
    parent.write_text("# temporarily missing managed include\n")
    opts = options(native_host, tmp_path)
    assert opts.native is not None
    route = NativeApoRoute(manager.target_key(), opts.native)
    try:
        assert not manager.apply((2.0,) * 10, OUTPUT, opts, native=route, generation=1).applied
        first_installation = route._installation
        assert first_installation is not None and not route.record_path.exists()
        from tests.widgets.test_equalizer_apo_recovery import BLOCK

        parent.write_text(BLOCK)
        assert manager.apply((3.0,) * 10, OUTPUT, opts, native=route, generation=2).applied
        bootstrap, saved = load_record(route)
        assert bootstrap.installation == first_installation
        process = child(native_host, bootstrap, tmp_path, seconds=1)
        try:
            deadline = time.monotonic() + 0.8
            observed = route.observe(2)
            while not observed.processing and time.monotonic() < deadline:
                time.sleep(0.02)
                observed = route.observe(2)
            assert observed.processing and observed.reports[0].status.applied_fingerprint == saved.fingerprint
        finally:
            finish(process)
    finally:
        route.close()


def test_restore_barrier_rejects_edits_until_authoritative_state_is_ready(
    native_host: tuple[Path, Path], tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        manager, output = manager_at(tmp_path), Output()
        opts = options(native_host, tmp_path)
        assert opts.native is not None
        monkeypatch.setattr(config_module, "HOME_CONFIGURATION_DIR", opts.native.profile)
        route = NativeApoRoute(manager.target_key(), opts.native)
        assert manager.apply(
            (4.0,) * 10,
            OUTPUT,
            opts,
            native=route,
            audio=NativeAudioState(balance=0.5, mono=True, dynamics=2),
            generation=1,
        ).applied
        route.close()
        apo.EqualizerApoConfigManager._states.clear()
        entered, release = threading.Event(), threading.Event()
        original = NativeApoRoute.prepare

        def held(
            self: NativeApoRoute,
            parameters: NativeParameters,
            endpoint_guid: str,
            generation: int,
            *,
            restore: bool = False,
            auto_preamp: bool = True,
        ):
            entered.set()
            assert release.wait(3)
            return original(self, parameters, endpoint_guid, generation, restore=restore, auto_preamp=auto_preamp)

        monkeypatch.setattr(NativeApoRoute, "prepare", held)
        client = make_controller(manager, output, opts)
        client.start((0.0,) * 10)
        writer = client._writer
        assert writer is not None
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            assert not client.update_audio(balance=0.2)
            assert not client.update_custom((9.0,) * 10)
            assert not client.apply_preset((8.0,) * 10)
            release.set()
            await settled(qapp, writer)
            assert client.gains == (4.0,) * 10
            assert client.audio_state == NativeAudioState(balance=0.5, mono=True, dynamics=2)
            assert client.update_audio(balance=0.2)
            await settled(qapp, writer)
            assert client.gains == (4.0,) * 10
            assert client.audio_state == NativeAudioState(balance=0.2, mono=True, dynamics=2)
        finally:
            release.set()
            client.shutdown()
            await apo.EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_responsive_pipe_does_not_claim_stopped_audio_callbacks_are_processing(
    native_host: tuple[Path, Path], tmp_path: Path
) -> None:
    manager = manager_at(tmp_path)
    opts = options(native_host, tmp_path)
    assert opts.native is not None
    route = NativeApoRoute(manager.target_key(), opts.native)
    try:
        assert manager.apply((1.0,) * 10, OUTPUT, opts, native=route, generation=1).applied
        bootstrap, _ = load_record(route)
        process = child(native_host, bootstrap, tmp_path, seconds=2.5, stop_render=True)
        try:
            deadline = time.monotonic() + 0.8
            while not route.observe(1).processing and time.monotonic() < deadline:
                time.sleep(0.02)
            assert route.observe(1).processing
            time.sleep(1.7)
            observation = route.observe(1)
            assert observation.reports and observation.reports[0].age_ms < 200
            assert observation.reports[0].status.processing == 1
            assert not observation.processing
        finally:
            finish(process)
    finally:
        route.close()


@pytest.mark.parametrize("renew_writer", [False, True])
def test_failed_restore_stays_blocked_and_retry_restores_saved_state(
    native_host: tuple[Path, Path],
    tmp_path: Path,
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    renew_writer: bool,
) -> None:
    async def run() -> None:
        manager, output = manager_at(tmp_path), Output()
        opts = options(native_host, tmp_path)
        assert opts.native is not None
        monkeypatch.setattr(config_module, "HOME_CONFIGURATION_DIR", opts.native.profile)
        route = NativeApoRoute(manager.target_key(), opts.native)
        audio = NativeAudioState(balance=-0.3, mono=True, dynamics=2)
        assert manager.apply((5.0,) * 10, OUTPUT, opts, native=route, audio=audio, generation=1).applied
        record_bytes = route.record_path.read_bytes()
        route.close()
        apo.EqualizerApoConfigManager._states.clear()
        parent = tmp_path / "config/config.txt"
        parent_bytes = parent.read_bytes()
        parent.write_text("# invalid/missing parent include\n")
        client = make_controller(manager, output, opts)
        client.start((0.0,) * 10)
        writer = client._writer
        assert writer is not None
        try:
            await settled(qapp, writer)
            assert client.write_failed
            assert not client.update_audio(balance=0.2)
            assert not client.update_custom((8.0,) * 10)
            assert not client.apply_preset((9.0,) * 10)
            assert route.record_path.read_bytes() == record_bytes
            with monkeypatch.context() as different_profile:
                different_profile.setattr(config_module, "HOME_CONFIGURATION_DIR", str(tmp_path / "another-profile"))
                other = make_controller(manager, output, opts)
                try:
                    other.start((9.0,) * 10)
                    generation = writer._generation
                    assert not other.draft_available and not other.apply_custom()
                    assert writer._generation == generation
                finally:
                    other.shutdown()
            parent.write_bytes(parent_bytes)
            if renew_writer:
                await apo.EqualizerApoWriter.aclose_shared()
                client.reconnect_writer()
                writer = client._writer
                assert writer is not None and client.restore_required
                assert not client.update_custom((8.0,) * 10)
                assert not client.apply_preset((9.0,) * 10)
                assert route.record_path.read_bytes() == record_bytes
            assert client.apply_custom()  # Explicit Retry repeats restoration.
            await settled(qapp, writer)
            assert not client.write_failed and client.gains == (5.0,) * 10
            assert client.audio_state.balance == pytest.approx(-0.3)
            assert client.audio_state.mono and client.audio_state.dynamics == 2
            assert client.update_audio(balance=0.2)
            await settled(qapp, writer)
            assert client.gains == (5.0,) * 10 and client.audio_state.dynamics == 2
        finally:
            client.shutdown()
            await apo.EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_conflicting_controller_cannot_acquire_draft_lease(
    native_host: tuple[Path, Path], tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        manager, output = manager_at(tmp_path), Output()
        opts = options(native_host, tmp_path)
        assert opts.native is not None
        monkeypatch.setattr(config_module, "HOME_CONFIGURATION_DIR", opts.native.profile)
        first = make_controller(manager, output, opts)
        first.start((1.0,) * 10)
        writer = first._writer
        assert writer is not None
        await settled(qapp, writer)
        monkeypatch.setattr(config_module, "HOME_CONFIGURATION_DIR", str(tmp_path / "another-profile"))
        other = make_controller(manager, output, opts)
        try:
            other.start((9.0,) * 10)
            assert not other.update_custom((7.0,) * 10)
            assert writer.target(manager.target_key()).draft_owner is None
            assert first.update_custom((4.0,) * 10)
        finally:
            first.shutdown()
            other.shutdown()
            await apo.EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_audio_after_destination_change_never_commits_old_draft(
    native_host: tuple[Path, Path], tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        manager, output = manager_at(tmp_path / "first"), Output()
        opts = options(native_host, tmp_path)
        assert opts.native is not None
        monkeypatch.setattr(config_module, "HOME_CONFIGURATION_DIR", opts.native.profile)
        client = make_controller(manager, output, opts)
        client.start((1.0,) * 10)
        writer = client._writer
        assert writer is not None
        await settled(qapp, writer)
        try:
            old_key = manager.target_key()
            assert client.update_custom((8.0,) * 10)
            destination = manager_at(tmp_path / "second")
            manager._registry.values["ConfigPath"] = str(tmp_path / "second/config")
            assert not client.update_audio(mono=True)
            assert not client.has_draft and writer.target(old_key).draft_owner is None
            assert writer.target(destination.target_key()).intent is None
            assert not Path(destination.target_key()).exists()
        finally:
            client.shutdown()
            await apo.EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_retargeted_native_routes_release_threads_and_handles(
    native_host: tuple[Path, Path], tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        manager, output = manager_at(tmp_path / "target0"), Output()
        opts = options(native_host, tmp_path)
        assert opts.native is not None
        monkeypatch.setattr(config_module, "HOME_CONFIGURATION_DIR", opts.native.profile)
        client = make_controller(manager, output, opts)
        client.start((1.0,) * 10)
        writer = client._writer
        assert writer is not None
        await settled(qapp, writer)
        await asyncio.to_thread(writer._executor.submit(lambda: None).result)
        process = psutil.Process()
        baseline = (process.num_threads(), process.num_handles())
        try:
            for index in range(1, 13):
                destination = tmp_path / f"target{index}"
                manager_at(destination)
                manager._registry.values["ConfigPath"] = str(destination / "config")
                output.state = replace(OUTPUT, endpoint_guid=f"{{{index:08x}-0123-0123-0123-0123456789ab}}")
                output.default_output_changed.emit(output.state)
                await settled(qapp, writer)
                await asyncio.to_thread(writer._executor.submit(lambda: None).result)
                assert len(writer._native_routes) == 1
                assert not client.pending and client.applied_state is not None
                assert client.applied_state.target == manager.target_key()
            assert process.num_threads() <= baseline[0] + 1
            assert process.num_handles() <= baseline[1] + 4
        finally:
            client.shutdown()
            await apo.EqualizerApoWriter.aclose_shared()
        assert not writer._native_routes
        assert process.num_handles() <= baseline[1]

    asyncio.run(run())


def test_profile_record_write_failure_preserves_leaf_and_recovers(
    native_host: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = manager_at(tmp_path)
    target = Path(manager.target_key())
    target.write_bytes(b"# recoverable owned leaf\n")
    before = target.read_bytes()
    opts = options(native_host, tmp_path)
    assert opts.native is not None
    route = NativeApoRoute(manager.target_key(), opts.native)
    original = apo.atomic_write_text

    def denied(path: Path, text: str, encoding: str = "utf-8") -> None:
        if path.suffix == ".json":
            raise PermissionError("owned denied record fixture")
        original(path, text, encoding)

    monkeypatch.setattr(apo, "atomic_write_text", denied)
    try:
        assert not manager.apply((2.0,) * 10, OUTPUT, opts, native=route, generation=1).applied
        assert target.read_bytes() == before and not route.record_path.exists()
        monkeypatch.setattr(apo, "atomic_write_text", original)
        assert manager.apply((3.0,) * 10, OUTPUT, opts, native=route, generation=2).applied
        assert load_record(route)[0].installation == route._installation
    finally:
        route.close()


def test_leaf_failure_after_persistence_recovers_and_graphic_rollback_is_exclusive(
    native_host: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = manager_at(tmp_path)
    target = Path(manager.target_key())
    old = apo.render_managed_config((1.0,) * 10, OUTPUT.endpoint_guid).encode()
    target.write_bytes(old)
    opts = options(native_host, tmp_path)
    assert opts.native is not None
    route = NativeApoRoute(manager.target_key(), opts.native)
    original = apo.atomic_write_text

    def denied(path: Path, text: str, encoding: str = "utf-8") -> None:
        if path == target:
            raise PermissionError("owned denied leaf fixture")
        original(path, text, encoding)

    monkeypatch.setattr(apo, "atomic_write_text", denied)
    try:
        assert not manager.apply((2.0,) * 10, OUTPUT, opts, native=route, generation=1).applied
        assert target.read_bytes() == old and load_record(route)[1].gains == (2.0,) * 10
        monkeypatch.setattr(apo, "atomic_write_text", original)
        assert manager.apply((2.0,) * 10, OUTPUT, opts, native=route, generation=2).applied
        assert load_record(route)[1].revision == 2
        assert manager.apply((1.0,) * 10, OUTPUT, MediaEqualizerApoConfig()).applied
        assert target.read_bytes() == old
        assert target.with_suffix(".txt.yasb-native-backup").read_bytes() == old
    finally:
        route.close()


def test_float32_persisted_values_do_not_leave_matching_intent_pending(
    native_host: tuple[Path, Path], tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        manager, output = manager_at(tmp_path), Output()
        opts = options(native_host, tmp_path)
        assert opts.native is not None
        monkeypatch.setattr(config_module, "HOME_CONFIGURATION_DIR", opts.native.profile)
        client = make_controller(manager, output, opts)
        client.start((0.0,) * 10)
        writer = client._writer
        assert writer is not None
        try:
            await settled(qapp, writer)
            assert client.apply_preset((0.3,) * 10)
            await settled(qapp, writer)
            assert not client.pending
            target = writer.target(manager.target_key())
            assert target.applied is not None
            decoded = NativeParameters.unpack(NativeParameters(gains=client.gains).pack())
            assert decoded.gains != client.gains
            # The manager retains logical input until a persisted binary snapshot
            # is decoded. Supply that real float32 boundary explicitly.
            target.applied = replace(target.applied, gains=decoded.gains)
            assert not client.pending
            assert client.update_audio(balance=0.2)
            await settled(qapp, writer)
            assert not client.pending
            target = writer.target(manager.target_key())
            assert target.applied is not None
            target.applied = replace(target.applied, audio=NativeAudioState(balance=0.5))
            assert client.pending  # Different Audio cannot reuse EQ-only completion.
        finally:
            client.shutdown()
            await apo.EqualizerApoWriter.aclose_shared()

    asyncio.run(run())


def test_adaptive_activation_discards_manual_draft_and_blocks_preset_until_disabled(
    native_host: tuple[Path, Path], tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        manager, output = manager_at(tmp_path), Output()
        opts = options(native_host, tmp_path)
        assert opts.native is not None
        monkeypatch.setattr(config_module, "HOME_CONFIGURATION_DIR", opts.native.profile)
        first, second = make_controller(manager, output, opts), make_controller(manager, output, opts)
        first.start((2.0,) * 10)
        writer = first._writer
        assert writer is not None
        try:
            await settled(qapp, writer)
            second.start((0.0,) * 10)
            assert first.update_custom((8.0,) * 10)
            assert second.update_audio(adaptive=True)
            assert not first.has_draft and first.gains == (2.0,) * 10
            assert writer.target(manager.target_key()).draft_owner is None
            generation = writer._generation
            assert not first.update_custom((6.0,) * 10)
            assert not first.apply_preset((5.0,) * 10)
            assert not first.apply_custom()
            assert writer._generation == generation
            await settled(qapp, writer)
            assert first.applied_gains == (2.0,) * 10
            assert second.update_audio(adaptive=False)
            await settled(qapp, writer)
            assert first.update_custom((4.0,) * 10)
            assert first.apply_custom()
            await settled(qapp, writer)
            assert first.applied_gains == (4.0,) * 10
        finally:
            first.shutdown()
            second.shutdown()
            await apo.EqualizerApoWriter.aclose_shared()

    asyncio.run(run())
