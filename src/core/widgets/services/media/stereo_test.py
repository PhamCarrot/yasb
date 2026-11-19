"""Stereo test playback on the selected audio output."""

from __future__ import annotations

import asyncio
import math
import struct
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, Literal, Protocol, cast

from PyQt6.QtCore import QBuffer, QIODevice, QObject, QTimer, pyqtBoundSignal, pyqtSignal, pyqtSlot
from PyQt6.QtMultimedia import QAudio, QAudioDevice, QAudioFormat, QAudioSink, QMediaDevices
from PyQt6.QtWidgets import QApplication

from core.utils.qobject import is_valid_qobject
from core.widgets.services.media.audio_device import AudioOutputState, DefaultAudioOutputService

SAMPLE_RATE = 48000
TEST_MS = 3200
PCM_BYTES = SAMPLE_RATE * TEST_MS // 1000 * 4


def make_test_pcm() -> bytes:
    """Generate PCM tones for the left, right and both channels, in order."""
    data = bytearray(PCM_BYTES)
    fade = round(0.015 * SAMPLE_RATE)
    for offset, duration, frequency, channels in (
        (0, 0.75, 660, (0,)),
        (0.93, 0.75, 880, (1,)),
        (1.86, 1.0, 770, (0, 1)),
    ):
        start, count = round(offset * SAMPLE_RATE), round(duration * SAMPLE_RATE)
        for frame in range(count):
            envelope = min(1.0, frame / fade, (count - 1 - frame) / fade)
            sample = round(9000 * envelope * math.sin(2 * math.pi * frequency * frame / SAMPLE_RATE))
            for channel in channels:
                struct.pack_into("<h", data, (start + frame) * 4 + channel * 2, sample)
    return bytes(data)


class TestSink(Protocol):
    stateChanged: ClassVar[pyqtSignal]

    def start(self, device: QIODevice | None) -> None: ...
    def reset(self) -> None: ...
    def state(self) -> QAudio.State: ...
    def error(self) -> QAudio.Error: ...
    def deleteLater(self) -> None: ...


def open_test_sink(output: AudioOutputState, parent: QObject) -> TestSink:
    # This is called only after an explicit Test activation, never on show/sync.
    selected: QAudioDevice | None = None
    for device in QMediaDevices.audioOutputs():
        identity = device.id().data().decode("utf-8", errors="strict")
        if identity.casefold() == output.endpoint_id.casefold():
            selected = device
            break
    if selected is None:
        raise ValueError("The captured output is no longer available")
    format = QAudioFormat()
    format.setSampleRate(SAMPLE_RATE)
    format.setChannelCount(2)
    format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    if not selected.isFormatSupported(format):
        raise ValueError("The output does not support 48kHz stereo Int16")
    return QAudioSink(selected, format, parent)


@dataclass(frozen=True)
class StereoTestState:
    status: Literal["idle", "preparing", "playing", "error"] = "idle"
    detail: str = ""


@dataclass(frozen=True)
class _Intent:
    token: object
    output: AudioOutputState
    generation: int


class StereoTestService(QObject):
    changed = pyqtSignal()
    _shared: ClassVar[StereoTestService | None] = None
    _closing: ClassVar[bool] = False
    _drain_task: ClassVar[asyncio.Task[None] | None] = None

    @classmethod
    def shared(cls) -> StereoTestService:
        if cls._shared is None or not is_valid_qobject(cls._shared) or (cls._shared._closed and not cls._closing):
            cls._shared = cls()
        return cls._shared

    @classmethod
    async def aclose_shared(cls) -> None:
        task = cls._drain_task
        if task is None or task.done():
            service = cls._shared
            if service is None:
                return
            cls._closing = True
            service.shutdown()
            task = asyncio.create_task(cls._drain_shared(service))
            cls._drain_task = task
        await asyncio.shield(task)

    @classmethod
    async def _drain_shared(cls, service: StereoTestService) -> None:
        if service._prepare_task is not None:
            await asyncio.shield(service._prepare_task)
        if cls._shared is service:
            cls._shared = None
        if cls._drain_task is asyncio.current_task():
            cls._drain_task = None
        cls._closing = False

    def __init__(
        self,
        *,
        output_service: DefaultAudioOutputService | None = None,
        factory: Callable[[AudioOutputState, QObject], TestSink] | None = None,
        generator: Callable[[], bytes] = make_test_pcm,
    ) -> None:
        super().__init__(QApplication.instance())
        self._output = output_service or DefaultAudioOutputService.instance()
        self._output_connected = False
        self._factory, self._generator = factory or open_test_sink, generator
        self._generation = 0
        self._desired: _Intent | None = None
        self._state = StereoTestState()
        self._state_token: object | None = None
        self._prepare_task: asyncio.Task[None] | None = None
        self._pcm: bytes | None = None
        self._sink: TestSink | None = None
        self._buffer: QBuffer | None = None
        self._timer: QTimer | None = None
        self._closed = False
        self._ensure_output()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    @property
    def closed(self) -> bool:
        return self._closed

    def state_for(self, token: object) -> StereoTestState:
        return self._state if self._state_token is token else StereoTestState()

    def active(self, token: object) -> bool:
        return self._desired is not None and self._desired.token is token

    @staticmethod
    def _usable_output(output: DefaultAudioOutputService) -> bool:
        return is_valid_qobject(output) and (type(output) is not DefaultAudioOutputService or not output.closed)

    def _disconnect_output(self) -> None:
        if self._output_connected and is_valid_qobject(self._output):
            try:
                self._output.default_output_changed.disconnect(self._output_changed)
            except RuntimeError, TypeError:
                pass
        self._output_connected = False

    def _ensure_output(self) -> DefaultAudioOutputService | None:
        if not self._usable_output(self._output):
            self._disconnect_output()
            self._output = DefaultAudioOutputService.instance()
        output = self._output
        if not self._usable_output(output):
            return None
        if not self._output_connected:
            output.default_output_changed.connect(self._output_changed)
            self._output_connected = True
        return output

    def start(self, token: object, output: AudioOutputState) -> bool:
        if self._closed or not output.available or self._ensure_output() is None:
            return False
        self._generation += 1
        intent = _Intent(token, output, self._generation)
        self._desired = intent
        self._retire()
        if not self._wanted(intent):
            return False
        self._state_token, self._state = token, StereoTestState("preparing", "Preparing stereo test…")
        self.changed.emit()
        self._pump()
        return True

    def cancel(self, token: object) -> None:
        if not self.active(token):
            return
        self._generation += 1
        generation = self._generation
        self._desired = None
        self._retire()
        if self._generation == generation and not self._closed:
            self._state_token, self._state = token, StereoTestState()
            self.changed.emit()

    def _wanted(self, intent: _Intent) -> bool:
        return not self._closed and self._desired is intent

    def _pump(self) -> None:
        intent = self._desired
        if intent is None or not self._wanted(intent) or self._sink is not None:
            return
        if self._pcm is None:
            if self._prepare_task is None:
                try:
                    self._prepare_task = asyncio.get_running_loop().create_task(self._prepare())
                except RuntimeError:
                    self._finish(intent, "error", "Stereo test needs the application event loop")
            return
        output = self._ensure_output()
        if output is None or output.state.endpoint_id.casefold() != intent.output.endpoint_id.casefold():
            self._finish(intent, "idle", "Output changed; test stopped")
            return
        sink: TestSink | None = None
        buffer: QBuffer | None = None
        installed = False
        try:
            sink = self._factory(intent.output, self)
            if not self._wanted(intent):
                sink.reset()
                sink.deleteLater()
                return
            buffer = QBuffer(self)
            buffer.setData(self._pcm)
            if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
                raise OSError("Could not open the stereo test buffer")
            self._sink, self._buffer = sink, buffer
            installed = True
            timer = self._timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: self._finish(intent, "idle", "Stereo test finished"))
            current_sink = sink

            def changed(state: QAudio.State) -> None:
                self._sink_changed(current_sink, intent, state)

            # Qt's signal descriptor is bound to a QObject at runtime; the
            # structural sink protocol does not itself inherit QObject.
            cast(pyqtBoundSignal, getattr(sink, "stateChanged")).connect(changed)
            timer.start(TEST_MS)
            # State callbacks may run synchronously inside start. All fields and
            # the timeout are installed before it, and retired before reset.
            sink.start(buffer)
            if self._wanted(intent) and self._sink is sink:
                self._sink_changed(sink, intent, sink.state())
        except (ValueError, OSError, RuntimeError) as error:
            if sink is not None and not installed:
                sink.reset()
                sink.deleteLater()
                if buffer is not None:
                    buffer.close()
                    buffer.deleteLater()
            self._finish(intent, "error", str(error)[:256])

    async def _prepare(self) -> None:
        try:
            pcm = await asyncio.to_thread(self._generator)
            if len(pcm) != PCM_BYTES:
                raise ValueError("Invalid stereo test clip length")
            if not self._closed:
                self._pcm = pcm
        except (ValueError, OSError, RuntimeError) as error:
            intent = self._desired
            if intent is not None:
                self._finish(intent, "error", str(error)[:256])
        finally:
            self._prepare_task = None
            self._pump()

    def _sink_changed(self, sink: TestSink, intent: _Intent, state: QAudio.State) -> None:
        if sink is not self._sink or not self._wanted(intent):
            return
        error = sink.error()
        if error != QAudio.Error.NoError:
            self._finish(intent, "error", f"Stereo test failed: {error.name}")
        elif state == QAudio.State.ActiveState:
            if self._state.status != "playing":
                self._state = StereoTestState("playing", "Stereo test playing")
                self.changed.emit()
        elif state == QAudio.State.IdleState:
            self._finish(intent, "idle", "Stereo test finished")
        elif state == QAudio.State.StoppedState:
            self._finish(intent, "error", "Stereo test could not start")

    def _finish(self, intent: _Intent, status: Literal["idle", "error"], detail: str) -> None:
        if not self._wanted(intent):
            return
        self._desired = None
        self._retire()
        if self._generation != intent.generation or self._closed:
            return
        self._state_token, self._state = intent.token, StereoTestState(status, detail)
        self.changed.emit()

    def _retire(self) -> None:
        sink, buffer, timer = self._sink, self._buffer, self._timer
        self._sink = self._buffer = self._timer = None
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        try:
            if sink is not None:
                sink.reset()
        finally:
            if buffer is not None:
                buffer.close()
                buffer.deleteLater()
            if sink is not None:
                sink.deleteLater()

    @pyqtSlot(object)
    def _output_changed(self, output: AudioOutputState) -> None:
        if self.sender() is not self._output or not self._usable_output(self._output):
            return
        intent = self._desired
        if intent is not None and output.endpoint_id.casefold() != intent.output.endpoint_id.casefold():
            self._finish(intent, "idle", "Output changed; test stopped")

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._generation += 1
        self._desired = None
        self._retire()
        self._pcm = None
        self._state = StereoTestState()
        self._disconnect_output()
        self.changed.emit()
