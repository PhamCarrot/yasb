# pyright: reportPrivateUsage=false

import asyncio
import math
import struct
import threading
from collections.abc import Awaitable, Callable
from typing import ClassVar, cast

import PyQt6.sip as sip
import pytest
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QObject, pyqtSignal
from PyQt6.QtMultimedia import QAudio, QAudioDevice, QAudioFormat
from PyQt6.QtWidgets import QApplication

from core.utils.qobject import is_valid_qobject
from core.widgets.services.media import stereo_test
from core.widgets.services.media.audio_device import AudioOutputState, DefaultAudioOutputService
from core.widgets.services.media.stereo_test import PCM_BYTES, SAMPLE_RATE, StereoTestService
from core.widgets.services.media.stereo_test import open_test_sink as real_open_test_sink
from tests.widgets.test_media_lyrics_owner import run_loop as run_loop
from tests.widgets.test_media_lyrics_owner import until

OUTPUT = AudioOutputState("owned-endpoint", "", "Owned synthetic output")


class Output(QObject):
    default_output_changed = pyqtSignal(object)
    state = OUTPUT

    def change(self, state: AudioOutputState) -> None:
        self.state = state
        self.default_output_changed.emit(state)


class Sink(QObject):
    stateChanged: ClassVar[pyqtSignal] = pyqtSignal(object)

    def __init__(self, parent: QObject, behavior: str = "active", events: list[str] | None = None) -> None:
        super().__init__(parent)
        self.behavior = behavior
        self.events = events if events is not None else []
        self.current = QAudio.State.StoppedState
        self.failure = QAudio.Error.NoError
        self.device: QIODevice | None = None
        self.starts = 0
        self.resets = 0
        self.open_at_reset = False
        self.on_reset: Callable[[], None] | None = None
        self.data = b""

    def start(self, device: QIODevice | None) -> None:
        assert device is not None and device.isOpen()
        self.device = device
        self.starts += 1
        self.data = device.readAll().data()
        if self.behavior == "raise":
            raise OSError("Owned start failure")
        if self.behavior == "error":
            self.failure = QAudio.Error.OpenError
            self.current = QAudio.State.StoppedState
        elif self.behavior == "idle":
            self.current = QAudio.State.IdleState
        elif self.behavior == "stopped":
            self.current = QAudio.State.StoppedState
        else:
            self.current = QAudio.State.ActiveState
        self.stateChanged.emit(self.current)

    def reset(self) -> None:
        self.events.append("reset")
        self.resets += 1
        self.open_at_reset = bool(self.device and self.device.isOpen())
        self.current = QAudio.State.StoppedState
        self.stateChanged.emit(self.current)
        if self.on_reset is not None:
            callback, self.on_reset = self.on_reset, None
            callback()

    def state(self) -> QAudio.State:
        return self.current

    def error(self) -> QAudio.Error:
        return self.failure


class Factory:
    def __init__(self, behavior: str = "active") -> None:
        self.behavior = behavior
        self.sinks: list[Sink] = []
        self.outputs: list[AudioOutputState] = []
        self.events: list[str] = []

    def __call__(self, output: AudioOutputState, parent: QObject) -> Sink:
        self.outputs.append(output)
        sink = Sink(parent, self.behavior, self.events)
        self.sinks.append(sink)
        return sink


def service_at(output: Output, factory: Factory, generator: Callable[[], bytes] | None = None) -> StereoTestService:
    return StereoTestService(
        output_service=cast(DefaultAudioOutputService, output),
        factory=factory,
        generator=generator or (lambda: bytes(PCM_BYTES)),
    )


async def close(service: StereoTestService) -> None:
    service.shutdown()
    if service._prepare_task is not None:
        await asyncio.shield(service._prepare_task)
    await asyncio.sleep(0)


def test_shared_recreates_after_direct_shutdown(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    output = Output()
    monkeypatch.setattr(DefaultAudioOutputService, "instance", staticmethod(lambda: output))
    previous = StereoTestService._shared
    service = service_at(output, Factory())
    StereoTestService._shared = service
    try:
        service.shutdown()
        replacement = StereoTestService.shared()
        assert replacement is not service
        assert not replacement.closed
        replacement.shutdown()
    finally:
        StereoTestService._shared = previous
        StereoTestService._closing = False


def test_stereo_service_replaces_closed_or_deleted_output(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    replacement = Output()
    monkeypatch.setattr(DefaultAudioOutputService, "instance", staticmethod(lambda: replacement))
    for deleted in (False, True):
        output = DefaultAudioOutputService.__new__(DefaultAudioOutputService)
        QObject.__init__(output)
        output._closed = not deleted
        if deleted:
            sip.delete(output)
        service = StereoTestService(output_service=output, factory=Factory())
        try:
            assert service._output is replacement
        finally:
            service.shutdown()


def output_wrapper() -> DefaultAudioOutputService:
    output = DefaultAudioOutputService.__new__(DefaultAudioOutputService)
    QObject.__init__(output)
    output._closed = False
    output._state = OUTPUT
    return output


def test_deleting_stereo_service_disconnects_output(qapp: QApplication) -> None:
    output = Output()
    service = service_at(output, Factory())
    assert output.receivers(output.default_output_changed) == 1
    sip.delete(service)
    assert output.receivers(output.default_output_changed) == 0


@pytest.mark.parametrize("deleted", [False, True])
def test_rebound_output_stops_playing_once_and_ignores_queued_old_signal(
    deleted: bool,
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    run_loop: Callable[[Awaitable[None]], None],
) -> None:
    async def run() -> None:
        old, replacement, factory = output_wrapper(), Output(), Factory()
        monkeypatch.setattr(DefaultAudioOutputService, "instance", staticmethod(lambda: replacement))
        service = StereoTestService(output_service=old, factory=factory, generator=lambda: bytes(PCM_BYTES))
        changed = AudioOutputState("different", "", "Different synthetic output")
        try:
            # Emit from a worker while the Qt thread is still bound to old.
            late = threading.Thread(target=lambda: old.default_output_changed.emit(changed))
            late.start()
            late.join()
            if deleted:
                sip.delete(old)
            else:
                old._closed = True
            assert service.start("first", OUTPUT)
            await until(lambda: len(factory.sinks) == 1)
            assert service.state_for("first").status == "playing"
            assert service.start("again", OUTPUT)
            assert service.start("final", OUTPUT)
            qapp.processEvents()
            assert len(factory.sinks) == 3 and service.active("final")
            sink = factory.sinks[-1]
            assert sink.starts == 1 and sink.resets == 0
            if not deleted:
                old.default_output_changed.emit(changed)
                assert sink.resets == 0
            replacement.change(changed)
            replacement.change(AudioOutputState())
            assert sink.resets == 1 and not service.active("final")
            assert service.state_for("final").detail == "Output changed; test stopped"
            assert replacement.receivers(replacement.default_output_changed) == 1
        finally:
            await close(service)
            assert replacement.receivers(replacement.default_output_changed) == 0

    run_loop(run())


@pytest.mark.parametrize("deleted", [False, True])
def test_prepared_clip_never_opens_sink_on_replacement_endpoint(
    deleted: bool,
    monkeypatch: pytest.MonkeyPatch,
    run_loop: Callable[[Awaitable[None]], None],
) -> None:
    async def run() -> None:
        entered, release = threading.Event(), threading.Event()

        def generate() -> bytes:
            entered.set()
            assert release.wait(5)
            return bytes(PCM_BYTES)

        old, replacement, factory = output_wrapper(), Output(), Factory()
        monkeypatch.setattr(DefaultAudioOutputService, "instance", staticmethod(lambda: replacement))
        service = StereoTestService(output_service=old, factory=factory, generator=generate)
        try:
            assert service.start("view", OUTPUT)
            await until(entered.is_set)
            if deleted:
                sip.delete(old)
            else:
                old._closed = True
            replacement.state = AudioOutputState("different", "", "Different synthetic output")
            release.set()
            await until(lambda: service._prepare_task is None)
            assert not factory.sinks and not service.active("view")
            assert service.state_for("view").detail == "Output changed; test stopped"
        finally:
            release.set()
            await close(service)

    run_loop(run())


def test_pcm_exact_channels_frequencies_silence_and_fades() -> None:
    pcm = stereo_test.make_test_pcm()
    assert len(pcm) == 614400 == PCM_BYTES

    def sample(frame: int, channel: int) -> int:
        return struct.unpack_from("<h", pcm, frame * 4 + channel * 2)[0]

    for start, duration in ((0.75, 0.18), (1.68, 0.18), (2.86, 0.34)):
        first, last = round(start * SAMPLE_RATE) * 4, round((start + duration) * SAMPLE_RATE) * 4
        assert not any(pcm[first:last])
    for offset, frequency, channels in ((0, 660, (0,)), (0.93, 880, (1,)), (1.86, 770, (0, 1))):
        first = round((offset + 0.1) * SAMPLE_RATE)
        for channel in (0, 1):
            values = [sample(first + index, channel) for index in range(4800)]
            if channel not in channels:
                assert not any(values)
                continue
            sine = sum(
                value * math.sin(2 * math.pi * frequency * index / SAMPLE_RATE) for index, value in enumerate(values)
            )
            cosine = sum(
                value * math.cos(2 * math.pi * frequency * index / SAMPLE_RATE) for index, value in enumerate(values)
            )
            assert 2 * math.hypot(sine, cosine) / len(values) == pytest.approx(9000, abs=1)
            begin = round(offset * SAMPLE_RATE)
            assert sample(begin, channel) == 0
            assert max(abs(sample(begin + index, channel)) for index in range(240)) < 3100
    assert max(abs(value[0]) for value in struct.iter_unpack("<h", pcm)) <= 9000


def test_owned_deadline_finishes_and_late_timeout_cannot_stop_successor(
    run_loop: Callable[[Awaitable[None]], None],
) -> None:
    async def run() -> None:
        output, factory = Output(), Factory()
        service = service_at(output, factory)
        try:
            service.start("one", OUTPUT)
            await until(lambda: service._timer is not None)
            timer = service._timer
            assert timer is not None and timer.isSingleShot() and timer.interval() == 3200
            timer.timeout.emit()
            assert service.state_for("one").detail == "Stereo test finished"
            assert not service.active("one") and factory.sinks[0].resets == 1
            service.start("two", OUTPUT)
            timer.timeout.emit()
            assert service.active("two") and factory.sinks[1].resets == 0
            assert service._buffer is not None and service._buffer.isOpen()
        finally:
            await close(service)

    run_loop(run())


def test_stop_restart_retains_one_actual_preparation_and_uses_latest_output(
    run_loop: Callable[[Awaitable[None]], None],
) -> None:
    async def run() -> None:
        entered, release = threading.Event(), threading.Event()
        calls = 0

        def generate() -> bytes:
            nonlocal calls
            calls += 1
            entered.set()
            assert release.wait(5)
            return bytes(PCM_BYTES)

        output, factory = Output(), Factory()
        service = service_at(output, factory, generate)
        try:
            assert service.start("one", OUTPUT)
            await until(entered.is_set)
            service.cancel("one")
            assert not service.active("one") and service._prepare_task is not None
            for _ in range(8):
                service.start("two", OUTPUT)
                service.cancel("two")
            service.start("latest", OUTPUT)
            await asyncio.sleep(0.03)
            assert calls == 1 and not factory.sinks
            release.set()
            await until(lambda: service.state_for("latest").status == "playing")
            assert len(factory.sinks) == calls == 1
            assert len(factory.sinks[0].data) == PCM_BYTES
            service.cancel("one")
            assert service.active("latest")
        finally:
            release.set()
            await close(service)

    run_loop(run())


@pytest.mark.parametrize("behavior", ["active", "idle", "error", "raise"])
def test_synchronous_start_callbacks_and_reset_before_buffer_close(
    run_loop: Callable[[Awaitable[None]], None], behavior: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        output, factory = Output(), Factory(behavior)

        class ObservedBuffer(QBuffer):
            def close(self) -> None:
                factory.events.append("close")
                super().close()

        monkeypatch.setattr(stereo_test, "QBuffer", ObservedBuffer)
        service = service_at(output, factory)
        try:
            service.start("view", OUTPUT)
            await until(lambda: bool(factory.sinks))
            sink = factory.sinks[0]
            if behavior == "active":
                assert service.state_for("view").status == "playing"
                assert service._timer is not None and service._timer.interval() == 3200
                service.cancel("view")
            else:
                assert service.state_for("view").status == ("idle" if behavior == "idle" else "error")
            assert sink.resets == 1 and sink.open_at_reset
            assert sink.device is not None
            assert not is_valid_qobject(sink.device) or not sink.device.isOpen()
            assert factory.events == ["reset", "close"]
            assert service._sink is None and service._buffer is None and service._timer is None
            service.cancel("view")
            assert sink.resets == 1
        finally:
            await close(service)

    run_loop(run())


def test_old_token_and_callback_cannot_stop_successor_and_reset_can_reenter(
    run_loop: Callable[[Awaitable[None]], None],
) -> None:
    async def run() -> None:
        output, factory = Output(), Factory()
        service = service_at(output, factory)
        try:
            service.start("a", OUTPUT)
            await until(lambda: service.active("a") and service._sink is not None)
            old_sink, old_intent = factory.sinks[0], service._desired
            assert old_intent is not None
            service.start("b", OUTPUT)
            service.cancel("a")
            service._sink_changed(old_sink, old_intent, QAudio.State.IdleState)
            assert service.active("b") and service.state_for("b").status == "playing"

            def restart() -> None:
                service.start("reentrant", OUTPUT)

            factory.sinks[-1].on_reset = restart
            service.start("superseded", OUTPUT)
            assert service.active("reentrant") and not service.active("superseded")
            assert service.state_for("reentrant").status == "playing"
        finally:
            await close(service)

    run_loop(run())


def test_output_change_cancels_preparing_and_playing_without_default_fallback(
    run_loop: Callable[[Awaitable[None]], None],
) -> None:
    async def run() -> None:
        entered, release = threading.Event(), threading.Event()

        def generate() -> bytes:
            entered.set()
            assert release.wait(5)
            return bytes(PCM_BYTES)

        output, factory = Output(), Factory()
        service = service_at(output, factory, generate)
        try:
            assert not service.start("missing", AudioOutputState())
            assert service._prepare_task is None and not factory.sinks
            service.start("view", OUTPUT)
            await until(entered.is_set)
            replacement = AudioOutputState("replacement", "", "Other output")
            output.change(replacement)
            release.set()
            await until(lambda: service._prepare_task is None)
            assert not factory.sinks and not service.active("view")
            service.start("other", replacement)
            assert service.active("other") and factory.outputs == [replacement]
            output.change(AudioOutputState())
            assert not service.active("other") and factory.sinks[-1].resets == 1
        finally:
            release.set()
            await close(service)

    run_loop(run())


def test_shutdown_waits_for_actual_preparation_and_does_not_publish_late(
    run_loop: Callable[[Awaitable[None]], None],
) -> None:
    async def run() -> None:
        entered, release = threading.Event(), threading.Event()

        def generate() -> bytes:
            entered.set()
            assert release.wait(5)
            return bytes(PCM_BYTES)

        factory = Factory()
        service = service_at(Output(), factory, generate)
        StereoTestService._shared = service
        try:
            service.start("view", OUTPUT)
            await until(entered.is_set)
            drain = asyncio.create_task(StereoTestService.aclose_shared())
            await asyncio.sleep(0.03)
            assert not drain.done() and StereoTestService.shared() is service
            assert not service.start("new", OUTPUT)
            release.set()
            await drain
            assert StereoTestService._shared is None and service._prepare_task is None
            assert not factory.sinks and service._pcm is None
        finally:
            release.set()
            await close(service)
            StereoTestService._shared = None

    run_loop(run())


def test_canceled_stereo_drain_keeps_shared_owner_until_preparation_finishes(
    run_loop: Callable[[Awaitable[None]], None],
) -> None:
    async def run() -> None:
        entered, release = threading.Event(), threading.Event()

        def generate() -> bytes:
            entered.set()
            assert release.wait(5)
            return bytes(PCM_BYTES)

        service = service_at(Output(), Factory(), generate)
        StereoTestService._shared = service
        try:
            service.start("view", OUTPUT)
            await until(entered.is_set)
            drain = asyncio.create_task(StereoTestService.aclose_shared())
            await asyncio.sleep(0.03)
            assert not drain.done() and StereoTestService.shared() is service
            drain.cancel()
            with pytest.raises(asyncio.CancelledError):
                await drain
            assert StereoTestService.shared() is service
            release.set()
            await StereoTestService.aclose_shared()
            assert StereoTestService._shared is None
        finally:
            release.set()
            await close(service)
            StereoTestService._shared = None

    run_loop(run())


@pytest.mark.parametrize("fault", ["factory", "buffer", "length", "generator", "stopped"])
def test_failures_release_owned_resources_and_remain_retryable(
    run_loop: Callable[[Awaitable[None]], None], monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    async def run() -> None:
        factory = Factory("stopped" if fault == "stopped" else "active")

        def generate() -> bytes:
            if fault == "generator":
                raise OSError("Owned generator fault")
            return b"short" if fault == "length" else bytes(PCM_BYTES)

        def create(output: AudioOutputState, parent: QObject) -> Sink:
            if fault == "factory":
                raise OSError("Owned factory fault")
            return factory(output, parent)

        class ClosedBuffer(QBuffer):
            def open(self, openMode: QIODevice.OpenModeFlag) -> bool:
                return False

        if fault == "buffer":
            monkeypatch.setattr(stereo_test, "QBuffer", ClosedBuffer)
        service = StereoTestService(
            output_service=cast(DefaultAudioOutputService, Output()), factory=create, generator=generate
        )
        try:
            service.start("view", OUTPUT)
            await until(lambda: service.state_for("view").status == "error")
            assert not service.active("view") and service._sink is None and service._buffer is None
            assert service._timer is None
            if factory.sinks:
                assert factory.sinks[0].resets == 1
            monkeypatch.setattr(stereo_test, "QBuffer", QBuffer)
            service._factory = factory
            service._generator = lambda: bytes(PCM_BYTES)
            factory.behavior = "active"
            service.start("view", OUTPUT)
            await until(lambda: service.state_for("view").status == "playing")
        finally:
            await close(service)

    run_loop(run())


class Device:
    def __init__(self, identity: str, supported: bool = True) -> None:
        self.identity = identity
        self.supported = supported

    def id(self) -> QByteArray:
        return QByteArray(self.identity.encode())

    def isFormatSupported(self, format: QAudioFormat) -> bool:
        assert format.sampleRate() == 48000 and format.channelCount() == 2
        assert format.sampleFormat() == QAudioFormat.SampleFormat.Int16
        return self.supported


@pytest.mark.parametrize("kind", ["match", "missing", "unsupported"])
def test_production_adapter_matches_captured_endpoint_and_exact_format_without_real_devices(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    selected = Device("OWNED-ENDPOINT" if kind != "missing" else "other", supported=kind != "unsupported")
    monkeypatch.setattr(stereo_test.QMediaDevices, "audioOutputs", staticmethod(lambda: [cast(QAudioDevice, selected)]))
    constructed: list[Device] = []

    def sink(device: QAudioDevice, format: QAudioFormat, parent: QObject) -> Sink:
        assert device is selected
        constructed.append(selected)
        return Sink(parent)

    monkeypatch.setattr(stereo_test, "QAudioSink", sink)
    parent = QObject()
    if kind == "match":
        assert real_open_test_sink(OUTPUT, parent) is not None
        assert constructed == [selected]
    else:
        with pytest.raises(ValueError, match="no longer|does not support"):
            real_open_test_sink(OUTPUT, parent)
        assert not constructed
