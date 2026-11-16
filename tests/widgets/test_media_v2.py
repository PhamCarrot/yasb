# pyright: reportPrivateUsage=false

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from core.validation.widgets.yasb.audio_visualizer import AudioVisualizerConfig
from core.validation.widgets.yasb.media_v2 import MediaV2Config
from core.widgets.services.media.audio_device import AudioOutputState, DefaultAudioOutputService
from core.widgets.services.media.backend import MediaBackend
from core.widgets.services.media.media import QSingleton, WindowsMedia
from core.widgets.services.media.model import (
    Capabilities,
    MediaSessionState,
    Metadata,
    Playback,
    PlaybackState,
    Player,
    Timeline,
)
from core.widgets.yasb import audio_visualizer
from core.widgets.yasb.audio_visualizer import AudioVisualizerWidget, format_media_label
from core.widgets.yasb.media_v2 import MediaWidgetV2
from core.widgets.yasb.media_v2_disc import _CaptureLease
from core.widgets.yasb.media_v2_popup import MediaPopup


class FakeSource:
    def __init__(self) -> None:
        self.emit: Callable[..., None] = lambda *_: None
        self.metadata_values = {"one": Metadata(title="First", artist="Artist"), "two": Metadata(title="Second")}
        self.calls: list[tuple[str, str, Any]] = []
        self.closed = 0

    async def start(self, emit: Callable[..., None]) -> None:
        self.emit = emit

    async def metadata(self, session_id: str) -> Metadata:
        return self.metadata_values[session_id]

    async def invoke(self, session_id: str, action: str, value: Any = None) -> bool:
        self.calls.append((session_id, action, value))
        return True

    def refresh(self, session_id: str) -> None:
        pass

    def close(self) -> None:
        self.closed += 1


class FakeCapture(QObject):
    frame_ready = pyqtSignal()
    audio_started = pyqtSignal()
    audio_stopped = pyqtSignal()
    idle_timeout = pyqtSignal(str)
    format_changed = pyqtSignal(int)
    sample_rate = 48000
    is_active = False

    def __init__(self) -> None:
        super().__init__()
        self.readers: list[tuple[int, frozenset[str]]] = []
        self.sources: list[str] = []

    def attach(self, framerate: int, channels: frozenset[str]) -> None:
        self.readers.append((framerate, channels))

    def detach(self, framerate: int, channels: frozenset[str], visible: bool) -> None:
        self.readers.remove((framerate, channels))

    def set_reader_visible(self, visible: bool) -> None:
        pass

    def watch_idle(self, widget_name: str, delay_ms: int) -> None:
        pass

    def magnitudes(self, channel: str) -> list[float]:
        return [0.0] * 1025


def install_capture(monkeypatch: pytest.MonkeyPatch) -> FakeCapture:
    capture = FakeCapture()

    def instance(source: str = "auto") -> FakeCapture:
        capture.sources.append(source)
        return capture

    monkeypatch.setattr(audio_visualizer.AudioVisualizerCaptureService, "instance", staticmethod(instance))
    return capture


async def populate(backend: MediaBackend, source: FakeSource) -> None:
    await backend.start()
    # Same application, two distinct native sessions: do not collapse by AUMID.
    source.emit("sessions", None, (Player("one", "same.app", "Player"), Player("two", "same.app", "Player")))
    for sid in ("one", "two"):
        source.emit(
            "playback",
            sid,
            Playback(PlaybackState.PAUSED, capabilities=Capabilities(can_play_pause=True, can_repeat=True)),
        )
        source.emit("metadata", sid, None)
    await asyncio.sleep(0)


def test_custom_widgets_and_legacy_adapter_share_selection(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    capture = install_capture(monkeypatch)
    monkeypatch.setattr(QSingleton, "_instances", {})

    async def run() -> None:
        source = FakeSource()
        backend = MediaBackend(source, autostart=False)
        monkeypatch.setattr(MediaBackend, "_shared", backend)
        await populate(backend, source)
        legacy = WindowsMedia()
        widget = MediaWidgetV2(MediaV2Config(hide_empty=False))
        visualizer = AudioVisualizerWidget(AudioVisualizerConfig(show_label=True, source="test-output"))
        qapp.processEvents()
        assert legacy.backend is widget.backend is visualizer._media is backend
        assert len(backend.state.sessions) == 2
        assert capture.sources == ["test-output"]
        assert backend.select_session("two")
        assert legacy.current_session is not None
        assert legacy.current_session.session_id == "two"
        assert widget._state.active_session_id == "two"
        assert visualizer._label is not None
        assert visualizer._label.text() == "Second"
        assert await legacy.cycle_repeat()
        assert source.calls == [("two", "repeat", 0)]
        assert backend.select_session(None)
        widget.close()
        visualizer.close()
        widget.deleteLater()
        visualizer.deleteLater()
        legacy.deleteLater()
        await backend.aclose()
        qapp.processEvents()

    asyncio.run(run())


def test_commands_keep_original_target_and_wait_for_observed_state(qapp: QApplication) -> None:
    async def run() -> None:
        source = FakeSource()
        backend = MediaBackend(source, autostart=False)
        await populate(backend, source)
        assert backend.select_session("one")
        action = backend.play_pause()
        assert backend.select_session("two")
        assert await action
        assert source.calls == [("one", "play_pause", None)]
        assert all(not session.is_playing for session in backend.state.sessions)
        source.emit("timeline", "two", Timeline(position=1.0, duration=10.0, known=True))
        source.emit("playback", "two", Playback(PlaybackState.PLAYING))
        assert backend.state.active is not None and backend.state.active.is_playing
        await backend.aclose()
        await backend.aclose()
        assert source.closed == 1
        assert not backend._tasks
        assert backend._timer is None
        source.emit("sessions", None, (Player("late", "app", "Late"),))
        assert backend.state.sessions == ()

    asyncio.run(run())


def test_removed_session_cannot_publish_delayed_metadata(qapp: QApplication) -> None:
    async def run() -> None:
        pending: asyncio.Future[Metadata] = asyncio.get_running_loop().create_future()

        class DelayedSource(FakeSource):
            async def metadata(self, session_id: str) -> Metadata:
                return await pending

        source = DelayedSource()
        backend = MediaBackend(source, autostart=False)
        await backend.start()
        source.emit("sessions", None, (Player("one", "app", "Player"),))
        source.emit("metadata", "one", None)
        await asyncio.sleep(0)
        source.emit("sessions", None, ())
        await asyncio.sleep(0)
        assert pending.cancelled()
        assert backend.state.sessions == ()
        await backend.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("title", "artist", "length", "scrolling", "expected"),
    [
        ("Song", "Artist", 0, False, "Song - Artist"),
        ("Song", "", 0, False, "Song"),
        ("", "Artist", 0, False, "Artist"),
        ("Long song", "", 6, False, "Lon..."),
        ("Long song", "", 6, True, "Long song"),
    ],
)
def test_media_label_format(title: str, artist: str, length: int, scrolling: bool, expected: str) -> None:
    session = MediaSessionState(Player("one", "app", "Player"), metadata=Metadata(title=title, artist=artist))
    assert format_media_label(session, "{title}{s}{artist}", " - ", max_length=length, scrolling=scrolling) == expected


def test_visualizer_idle_wakes_and_disc_capture_lease_balances(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = install_capture(monkeypatch)
    widget = AudioVisualizerWidget(AudioVisualizerConfig(hide_idle=True))
    assert widget._idle_hidden
    capture.is_active = True
    capture.audio_started.emit()
    qapp.processEvents()
    assert not widget._idle_hidden
    assert not widget.isHidden()
    lease = _CaptureLease(30)
    lease.attach()
    lease.attach()
    assert len(capture.readers) == 2
    lease.detach()
    lease.detach()
    widget._token.detach()
    assert capture.readers == []
    widget.close()
    widget.deleteLater()


def test_media_v2_schema_retains_full_custom_options() -> None:
    config = MediaV2Config.model_validate({"popup": {"show_equalizer": True, "disc": {"visualizer": True}}})
    assert config.popup.show_equalizer
    assert config.popup.disc.visualizer


@pytest.mark.parametrize("position", ["left", "right", "top", "hidden"])
def test_media_popup_renders_custom_layouts(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, position: str
) -> None:
    install_capture(monkeypatch)

    class Output(QObject):
        default_output_changed = pyqtSignal(object)
        default_output_refreshed = pyqtSignal(object)
        state = AudioOutputState("test-output", "", "Isolated test output")

        def request_refresh(self, force: bool = False) -> None:
            pass

    output = Output()
    monkeypatch.setattr(DefaultAudioOutputService, "instance", staticmethod(lambda: output))

    async def run() -> None:
        source = FakeSource()
        backend = MediaBackend(source, autostart=False)
        await populate(backend, source)
        config = MediaV2Config.model_validate(
            {"popup": {"artwork_position": position, "blur": False, "show_equalizer": True}}
        )
        widget = MediaWidgetV2(config, backend)
        popup = MediaPopup(widget, config)
        popup.set_state(backend.state, widget._pixmap)
        qapp.processEvents()
        assert popup.title.text() == "First"
        assert popup.device.text() == "Isolated test output"
        assert not popup.equalizer.apo.enabled
        popup.equalizer.select_preset("Bass", motion=False)
        assert popup.equalizer.preset == "Bass"
        image = popup.border.grab()
        assert not image.isNull()
        assert image.width() >= 625
        assert image.save(str(tmp_path / f"media-v2-{position}.png"))
        popup.equalizer.apo.shutdown()
        popup.close()
        popup.deleteLater()
        widget.close()
        widget.deleteLater()
        await backend.aclose()
        qapp.processEvents()

    asyncio.run(run())
