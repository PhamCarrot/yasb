"""Owned broker + native child process, synthetic audio only; never installs APO."""

import hashlib
import json
import subprocess
import time
from collections.abc import Callable
from ctypes import c_int32, c_void_p
from dataclasses import replace
from pathlib import Path

import pytest

from build_media_dsp import build
from core.widgets.services.media.native_api import (
    NativeBootstrap,
    NativeBroker,
    NativeDspApi,
    NativeParameters,
    NativeReport,
)
from tests.widgets.test_media_native_dsp import native_host as native_host

pytestmark = pytest.mark.sdk


@pytest.fixture(scope="module")
def api(native_host: tuple[Path, Path]) -> NativeDspApi:
    _, dll = native_host
    return NativeDspApi(dll, expected_sha256=hashlib.sha256(dll.read_bytes()).hexdigest())


def binding(api: NativeDspApi) -> NativeBootstrap:
    return api.bootstrap(hashlib.sha256(b"owned-config").digest(), hashlib.sha256(b"owned-endpoint").digest())


def child(
    native_host: tuple[Path, Path],
    route: NativeBootstrap,
    folder: Path,
    *,
    seconds: float = 2,
    rate_change: bool = False,
    destroy_on_notification: bool = False,
    stop_render: bool = False,
) -> subprocess.Popen[str]:
    exe, dll = native_host
    path = folder / "bootstrap.bin"
    path.write_bytes(route.pack())
    return subprocess.Popen(
        [
            str(exe),
            str(dll),
            "resident-destroy"
            if destroy_on_notification
            else "resident-rate"
            if rate_change
            else "resident-stop"
            if stop_render
            else "resident",
            str(path),
            str(seconds),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def wait_reports(
    broker: NativeBroker, predicate: Callable[[tuple[NativeReport, ...]], bool], timeout: float = 3
) -> tuple[NativeReport, ...]:
    deadline = time.monotonic() + timeout
    observed: tuple[NativeReport, ...] = ()
    while time.monotonic() < deadline:
        observed = broker.reports()
        if predicate(observed):
            return observed
        time.sleep(0.01)
    pytest.fail(f"Native reports did not satisfy condition: {observed}")


def finish(process: subprocess.Popen[str]) -> dict[str, object]:
    try:
        stdout, stderr = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        pytest.fail(f"Owned native host failed to exit: {stdout} {stderr}")
    assert process.returncode == 0, stdout + stderr
    return json.loads(stdout)


def test_real_cross_process_snapshot_and_processing_ack(
    api: NativeDspApi, native_host: tuple[Path, Path], tmp_path: Path
) -> None:
    route = binding(api)
    desired = NativeParameters(gains=(3.0,) * 10, balance=-0.25, preamp_db=-3)
    with api.create(route) as broker:
        assert broker.publish(route, desired, 1)
        process = child(native_host, route, tmp_path)
        try:
            reports = wait_reports(
                broker,
                lambda rows: bool(rows and rows[0].confirmed_generation == 1 and rows[0].status.processed_frames > 0),
            )
            report = reports[0]
            assert report.status.process_id == process.pid
            assert report.status.build == api.build
            assert report.status.applied_fingerprint == desired.fingerprint
            assert report.status.instance_uuid != b"\0" * 16
            assert report.config == route.config and report.endpoint == route.endpoint
            assert report.status.transport_state == 2 and report.status.sample_rate == 48000
            assert report.status.applied_revision == report.status.accepted_revision
        finally:
            result = finish(process)
        assert result["fingerprint"] == desired.fingerprint


def test_broker_first_instance_is_exclusive(api: NativeDspApi) -> None:
    route = binding(api)
    with api.create(route):
        with pytest.raises(OSError):
            api.create(route)
    with api.create(route) as replacement:
        assert replacement.reports() == ()


def test_wrong_controller_sid_is_rejected(api: NativeDspApi) -> None:
    route = replace(binding(api), controller_sid="S-1-5-18")
    with pytest.raises(OSError):
        api.create(route)


def test_latest_intent_aba_never_reports_stale_completion(
    api: NativeDspApi, native_host: tuple[Path, Path], tmp_path: Path
) -> None:
    route = binding(api)
    a, b = NativeParameters(gains=(4.0,) * 10), NativeParameters(gains=(-4.0,) * 10)
    with api.create(route) as broker:
        process = child(native_host, route, tmp_path)
        try:
            assert broker.publish(route, a, 1)
            wait_reports(broker, lambda rows: bool(rows and rows[0].confirmed_generation == 1))
            assert broker.publish(route, b, 2)
            assert broker.publish(route, a, 3)
            assert not broker.publish(route, b, 2)
            reports = wait_reports(broker, lambda rows: bool(rows and rows[0].confirmed_generation == 3))
            assert reports[0].status.applied_fingerprint == a.fingerprint
            assert reports[0].status.accepted_fingerprint == a.fingerprint
        finally:
            finish(process)


def test_stream_epoch_change_reconnects_without_reusing_old_confirmation(
    api: NativeDspApi, native_host: tuple[Path, Path], tmp_path: Path
) -> None:
    route = binding(api)
    desired = NativeParameters(preamp_db=-6)
    with api.create(route) as broker:
        assert broker.publish(route, desired, 1)
        process = child(native_host, route, tmp_path, seconds=2.5, rate_change=True)
        try:
            first = wait_reports(broker, lambda rows: bool(rows and rows[0].confirmed_generation == 1))[0]
            newer = wait_reports(
                broker,
                lambda rows: bool(
                    rows
                    and rows[0].status.stream_epoch > first.status.stream_epoch
                    and rows[0].confirmed_generation == 1
                ),
            )[0]
            assert newer.status.instance_uuid == first.status.instance_uuid
            assert newer.connection_epoch != first.connection_epoch
            assert newer.status.sample_rate == 96000
            assert newer.status.applied_fingerprint == desired.fingerprint
        finally:
            finish(process)


def test_shutdown_while_client_is_connected_joins_and_client_keeps_last_state(
    api: NativeDspApi, native_host: tuple[Path, Path], tmp_path: Path
) -> None:
    route = binding(api)
    desired = NativeParameters(preamp_db=-6)
    broker = api.create(route)
    process = child(native_host, route, tmp_path)
    try:
        assert broker.publish(route, desired, 1)
        wait_reports(broker, lambda rows: bool(rows and rows[0].confirmed_generation == 1))
        start = time.monotonic()
        broker.close()
        assert time.monotonic() - start < 1
        assert broker.reports() == ()
        with pytest.raises(RuntimeError):
            broker.publish(route, desired, 2)
        result = finish(process)
        assert result["fingerprint"] == desired.fingerprint
    finally:
        broker.close()
        if process.poll() is None:
            finish(process)


@pytest.mark.parametrize(
    "parameters",
    [NativeParameters(gains=(float("nan"),) * 10), NativeParameters(balance=2), NativeParameters(preamp_db=-25)],
)
def test_invalid_parameters_never_cross_the_bridge(parameters: NativeParameters) -> None:
    with pytest.raises(ValueError):
        parameters.pack()


def test_closed_broker_is_idempotent_and_dll_manifest_is_checked(api: NativeDspApi) -> None:
    broker = api.create(binding(api))
    broker.close()
    broker.close()
    assert broker.reports() == ()
    with pytest.raises(ValueError, match="manifest"):
        NativeDspApi(api.path, expected_sha256="0" * 64)


@pytest.fixture(scope="module")
def held_host(native_host: tuple[Path, Path], tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    return native_host[0], build(tmp_path_factory.mktemp("held-native-dsp"), test_hooks=True)


def test_reserved_b_packet_fences_aba_before_io(
    held_host: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = NativeDspApi(held_host[1])
    route = binding(api)
    a, b = NativeParameters(gains=(4.0,) * 10), NativeParameters(gains=(-4.0,) * 10)
    # Test exports exist only in the independently identified test-hook DLL.
    from ctypes import CDLL

    library = CDLL(str(api.path))
    hold, held = library.YasbMediaBrokerTestHold, library.YasbMediaBrokerTestHeld
    hold.argtypes, hold.restype = [c_void_p, c_int32], None
    held.argtypes, held.restype = [c_void_p], c_int32
    with api.create(route) as broker:
        # Capture the opaque test handle at creation rather than exposing it in production API.
        handles: list[int] = []
        original = api.broker_reports

        def reports(handle: int, output: object, capacity: int) -> int:
            handles[:] = [handle]
            return int(original(handle, output, capacity))

        monkeypatch.setattr(api, "broker_reports", reports)
        process = child(held_host, route, tmp_path, seconds=3)
        try:
            assert broker.publish(route, a, 1)
            first = wait_reports(broker, lambda rows: bool(rows and rows[0].confirmed_generation == 1))[0]
            handle = handles[0]
            hold(handle, 1)
            assert broker.publish(route, b, 2)
            deadline = time.monotonic() + 1
            while not held(handle) and time.monotonic() < deadline:
                time.sleep(0.005)
            assert held(handle), "SET reservation was never reached"
            assert broker.publish(route, a, 3)
            for _ in range(20):
                row = broker.reports()[0]
                assert row.status.applied_revision == first.status.applied_revision
                assert row.status.accepted_fingerprint == a.fingerprint
                assert row.confirmed_generation == 0
            hold(handle, 0)
            last = wait_reports(broker, lambda rows: bool(rows and rows[0].confirmed_generation == 3))[0]
            assert last.status.applied_revision >= first.status.applied_revision + 2
        finally:
            if handles:
                hold(handles[0], 0)
            finish(process)


def test_latency_notification_can_synchronously_destroy_on_host_thread(
    api: NativeDspApi, native_host: tuple[Path, Path], tmp_path: Path
) -> None:
    route = binding(api)
    with api.create(route) as broker:
        assert broker.publish(route, NativeParameters(dynamics=1), 1)
        process = child(native_host, route, tmp_path, destroy_on_notification=True)
        result = finish(process)
        assert result == {"destroyed_on_host_thread": True, "notifications": 1, "borrowed_chunk_survived": True}


def test_client_rejects_wrong_provisioned_server_owner(
    api: NativeDspApi, native_host: tuple[Path, Path], tmp_path: Path
) -> None:
    route = binding(api)
    with api.create(route) as broker:
        assert broker.publish(route, NativeParameters(preamp_db=-6), 1)
        result = finish(child(native_host, replace(route, controller_sid="S-1-5-18"), tmp_path, seconds=0.6))
        assert broker.reports() == ()
        assert result["fingerprint"] == route.initial.fingerprint
        assert result["transport"] == 1


def test_absent_broker_client_destruction_is_bounded(
    api: NativeDspApi, native_host: tuple[Path, Path], tmp_path: Path
) -> None:
    route = binding(api)
    start = time.monotonic()
    result = finish(child(native_host, route, tmp_path, seconds=0.1))
    assert time.monotonic() - start < 1.5
    assert result["fingerprint"] == route.initial.fingerprint


def test_burst_coalesces_for_two_independent_instances(
    api: NativeDspApi, native_host: tuple[Path, Path], tmp_path: Path
) -> None:
    route = binding(api)
    with api.create(route) as broker:
        children = [child(native_host, route, tmp_path, seconds=2.5) for _ in range(2)]
        try:
            wait_reports(broker, lambda rows: len(rows) == 2)
            desired = NativeParameters()
            for generation in range(1, 101):
                desired = NativeParameters(preamp_db=-generation / 10)
                assert broker.publish(route, desired, generation)
            rows = wait_reports(
                broker, lambda rows: len(rows) == 2 and all(r.confirmed_generation == 100 for r in rows)
            )
            assert len({r.status.instance_uuid for r in rows}) == 2
            assert {r.status.process_id for r in rows} == {p.pid for p in children}
            assert all(r.status.applied_fingerprint == desired.fingerprint for r in rows)
        finally:
            for process in children:
                finish(process)


def test_default_dll_has_no_dispatch_test_hook(api: NativeDspApi) -> None:
    from ctypes import CDLL

    with pytest.raises(AttributeError):
        getattr(CDLL(str(api.path)), "YasbMediaBrokerTestHold")


@pytest.mark.parametrize("mode", ["truncated", "oversized", "replay", "epoch", "response-stall"])
def test_malformed_or_stalled_peer_is_retired_without_blocking_others(
    api: NativeDspApi, native_host: tuple[Path, Path], tmp_path: Path, mode: str
) -> None:
    route = binding(api)
    exe, dll = native_host
    path = tmp_path / "bootstrap.bin"
    path.write_bytes(route.pack())
    with api.create(route) as broker:
        attack = subprocess.Popen(
            [str(exe), str(dll), f"raw-{mode}", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        process = child(native_host, route, tmp_path, seconds=3)
        try:
            assert broker.publish(route, NativeParameters(preamp_db=-3), 1)
            wait_reports(
                broker,
                lambda rows: any(r.status.process_id == process.pid and r.confirmed_generation == 1 for r in rows),
            )
            assert finish(attack) == {"closed": True, "count": 1}
            rows = wait_reports(broker, lambda rows: all(r.status.process_id != attack.pid for r in rows))
            assert all(r.status.process_id == process.pid for r in rows)
        finally:
            if attack.poll() is None:
                finish(attack)
            finish(process)


def test_sixteen_stalled_handshakes_expire_and_broker_recovers(
    api: NativeDspApi, native_host: tuple[Path, Path], tmp_path: Path
) -> None:
    route = binding(api)
    exe, dll = native_host
    path = tmp_path / "bootstrap.bin"
    path.write_bytes(route.pack())
    with api.create(route) as broker:
        attack = subprocess.Popen(
            [str(exe), str(dll), "raw-stall", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        process = None
        try:
            deadline = time.monotonic() + 2
            while not path.with_suffix(".bin.ready").exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            assert path.with_suffix(".bin.ready").exists()
            assert broker.publish(route, NativeParameters(preamp_db=-6), 1)
            process = child(native_host, route, tmp_path, seconds=3.5)
            wait_reports(broker, lambda rows: bool(rows and rows[0].confirmed_generation == 1), timeout=3)
            assert finish(attack) == {"closed": True, "count": 16}
        finally:
            if attack.poll() is None:
                finish(attack)
            if process is not None:
                finish(process)


def test_broker_recreation_reconnects_existing_instance(
    api: NativeDspApi, native_host: tuple[Path, Path], tmp_path: Path
) -> None:
    route = binding(api)
    process = child(native_host, route, tmp_path, seconds=3)
    try:
        with api.create(route) as broker:
            assert broker.publish(route, NativeParameters(preamp_db=-3), 1)
            first = wait_reports(broker, lambda rows: bool(rows and rows[0].confirmed_generation == 1))[0]
        with api.create(route) as replacement:
            assert replacement.publish(route, NativeParameters(preamp_db=-6), 1)
            second = wait_reports(replacement, lambda rows: bool(rows and rows[0].confirmed_generation == 1))[0]
            assert second.status.instance_uuid == first.status.instance_uuid
            assert second.connection_epoch != first.connection_epoch
            assert second.status.accepted_revision > first.status.accepted_revision
    finally:
        finish(process)


def test_broker_close_cancels_a_held_dispatch(
    held_host: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ctypes import CDLL

    api = NativeDspApi(held_host[1])
    route = binding(api)
    library = CDLL(str(api.path))
    hold, held = library.YasbMediaBrokerTestHold, library.YasbMediaBrokerTestHeld
    hold.argtypes, hold.restype = [c_void_p, c_int32], None
    held.argtypes, held.restype = [c_void_p], c_int32
    handles: list[int] = []
    original = api.broker_reports

    def reports(handle: int, output: object, capacity: int) -> int:
        handles[:] = [handle]
        return int(original(handle, output, capacity))

    monkeypatch.setattr(api, "broker_reports", reports)
    broker = api.create(route)
    process = child(held_host, route, tmp_path, seconds=1.5)
    try:
        assert broker.publish(route, NativeParameters(), 1)
        wait_reports(broker, lambda rows: bool(rows and rows[0].confirmed_generation == 1))
        handle = handles[0]
        hold(handle, 1)
        assert broker.publish(route, NativeParameters(preamp_db=-6), 2)
        deadline = time.monotonic() + 0.8
        while not held(handle) and time.monotonic() < deadline:
            time.sleep(0.005)
        assert held(handle)
        start = time.monotonic()
        broker.close()  # No release: stop must cancel the reservation itself.
        assert time.monotonic() - start < 1
        assert broker.reports() == ()
    finally:
        broker.close()
        finish(process)
