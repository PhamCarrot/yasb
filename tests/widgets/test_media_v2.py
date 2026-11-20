# pyright: reportPrivateUsage=false

import asyncio
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import PyQt6.sip as sip
import pytest
from pydantic import ValidationError
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


def test_closed_backend_is_rebound_by_legacy_adapter_and_v2_widget(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        monkeypatch.setattr(QSingleton, "_instances", {})
        install_capture(monkeypatch)
        previous = MediaBackend._shared
        old = MediaBackend(FakeSource(), autostart=False)
        replacement = MediaBackend(FakeSource(), autostart=False)
        MediaBackend._shared = old
        legacy = WindowsMedia()
        widget = MediaWidgetV2(MediaV2Config(hide_empty=False), backend=old)
        visualizer = AudioVisualizerWidget(AudioVisualizerConfig(show_label=True, source="test-output"))
        try:
            qapp.processEvents()
            await old.aclose()
            MediaBackend._shared = replacement
            assert legacy.current_session is None
            assert legacy.backend is replacement
            assert widget._ensure_backend() is replacement
            assert widget.backend is replacement
            assert visualizer._ensure_media() is replacement
            assert visualizer._media is replacement
        finally:
            widget.deleteLater()
            legacy.deleteLater()
            visualizer.deleteLater()
            await old.aclose()
            await replacement.aclose()
            MediaBackend._shared = previous
            qapp.processEvents()

    asyncio.run(run())


def test_queued_legacy_refresh_does_not_recreate_backend_after_shared_close(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        monkeypatch.setattr(QSingleton, "_instances", {})
        previous = MediaBackend._shared
        old = MediaBackend(FakeSource(), autostart=False)
        MediaBackend._shared = old
        legacy = WindowsMedia()
        try:
            await MediaBackend.aclose_shared()
            await asyncio.sleep(0)
            assert MediaBackend._shared is None
            assert legacy.backend is old
        finally:
            legacy.deleteLater()
            await old.aclose()
            MediaBackend._shared = previous
            qapp.processEvents()

    asyncio.run(run())


@pytest.mark.parametrize("cancel_first", [False, True])
def test_shared_backend_drain_waits_for_start_cleanup_after_waiter_cancellation(
    cancel_first: bool, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        loop = asyncio.get_running_loop()
        started, cleaning, release, acknowledged, refreshed = (asyncio.Event() for _ in range(5))

        class HeldStart(FakeSource):
            starts = 0
            interrupted = 0

            async def start(self, emit: Callable[..., None]) -> None:
                self.starts += 1
                self.emit = emit
                started.set()
                try:
                    await loop.create_future()
                except asyncio.CancelledError:
                    cleaning.set()
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        self.interrupted += 1
                        raise
                    acknowledged.set()
                    raise

        source = HeldStart()
        backend = MediaBackend(source, autostart=False)
        monkeypatch.setattr(MediaBackend, "_shared", backend)
        monkeypatch.setattr(QSingleton, "_instances", {})
        legacy = WindowsMedia()
        constructors = 0

        def forbidden_constructor(*_args: Any, **_kwargs: Any) -> None:
            nonlocal constructors
            constructors += 1
            raise AssertionError("A queued refresh attempted to create a real backend")

        def queued_refresh() -> None:
            legacy.force_update()
            refreshed.set()

        monkeypatch.setattr(MediaBackend, "__init__", forbidden_constructor)
        waiters: list[asyncio.Task[None]] = []
        startup = loop.create_task(backend.start())
        try:
            async with asyncio.timeout(3):
                await started.wait()
                first = loop.create_task(MediaBackend.aclose_shared())
                waiters.append(first)
                await cleaning.wait()
                second = loop.create_task(MediaBackend.aclose_shared())
                waiters.append(second)
                loop.call_soon(queued_refresh)
                await refreshed.wait()
                if cancel_first:
                    first.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await first
                assert (second.done(), MediaBackend.shared_instance(), source.interrupted) == (False, backend, 0)
                assert backend.closed and MediaBackend.shared() is backend and not acknowledged.is_set()
                source.emit("sessions", None, (Player("late", "app", "Late"),))
                assert backend.state.sessions == ()
                release.set()
                await second
                if not cancel_first:
                    await first
                with pytest.raises(asyncio.CancelledError):
                    await startup
                await MediaBackend.aclose_shared()
                assert acknowledged.is_set() and source.interrupted == 0
                assert MediaBackend.shared_instance() is None and legacy.backend is backend
                assert (source.starts, source.closed, constructors) == (1, 1, 0)
                assert not backend._tasks and backend._timer is None
        finally:
            release.set()
            await asyncio.gather(startup, *waiters, return_exceptions=True)
            await backend.aclose()
            legacy.deleteLater()
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


@pytest.mark.parametrize("canonical", [False, True])
def test_media_v2_migrates_legacy_options_without_mutating_input(canonical: bool) -> None:
    popup: dict[str, object] = {
        "scrolling": {"speed": 65, "delay": 300},
        "placement": "screen",
        "direction": "auto",
        "edge_offset": 9,
        "bar_offset": 61,
        "background": {"native_blur": "false", "mode": "qss"},
        "equalizer": {"preset_effect": "blur_slide"},
    }
    raw: dict[str, object] = {"bar_scrolling": {"enabled": False, "speed": 55, "delay": 200}, "popup": popup}
    if canonical:
        raw["scrolling_label"] = {"enabled": True, "speed": 40, "delay": 500}
        popup.update(scrolling_label={"speed": 42, "delay": 600}, blur=True, offset_left=2, offset_top=3)
        popup["widget_offset"] = 77
    original = deepcopy(raw)
    config = MediaV2Config.model_validate(raw)

    assert raw == original
    assert config.scrolling_label.model_dump() == (
        {"enabled": True, "speed": 40, "delay": 500} if canonical else {"enabled": False, "speed": 55, "delay": 200}
    )
    assert config.popup.scrolling_label.model_dump() == (
        {"speed": 42, "delay": 600} if canonical else {"speed": 65, "delay": 300}
    )
    assert (config.popup.direction, config.popup.offset_left, config.popup.offset_top, config.popup.blur) == (
        ("down", 2, 3, True) if canonical else ("down", 9, 61, False)
    )
    assert config.popup.background.mode == "color"
    assert config.popup.equalizer.preset_effect == "none"
    dumped = config.model_dump()
    assert "bar_scrolling" not in dumped
    assert {"scrolling", "placement", "edge_offset", "bar_offset", "widget_offset"}.isdisjoint(dumped["popup"])
    assert "native_blur" not in dumped["popup"]["background"]


def test_media_v2_migrates_widget_offset_and_rejects_invalid_booleans() -> None:
    config = MediaV2Config.model_validate({"popup": {"widget_offset": 18, "bar_offset": 61}})
    assert config.popup.offset_top == 18
    with pytest.raises(ValidationError, match=r"popup\.background\.native_blur must be a recognized boolean"):
        MediaV2Config.model_validate({"popup": {"blur": True, "background": {"native_blur": "perhaps"}}})
    with pytest.raises(ValidationError, match="valid boolean"):
        MediaV2Config.model_validate({"bar_scrolling": {"enabled": "perhaps"}})


def test_media_v2_registers_compatible_callbacks_and_bar_identities(qapp: QApplication) -> None:
    actions = (
        "toggle_media_menu",
        "play_pause",
        "previous",
        "next",
        "automatic_selection",
        "toggle_compact",
        "do_nothing",
        "default",
        "exec unused",
    )
    callbacks = {"on_left": "toggle_media_menu", "on_middle": "default", "on_right": "exec unused"}
    keybindings = [{"keys": f"ctrl+{i + 1}", "action": action, "screen": "active"} for i, action in enumerate(actions)]
    config = MediaV2Config.model_validate({"callbacks": callbacks, "keybindings": keybindings, "class_name": "themed"})
    assert config.callbacks.model_dump() == callbacks
    assert [binding.model_dump() for binding in config.keybindings] == keybindings

    async def run() -> None:
        backend = MediaBackend(FakeSource(), autostart=False)
        widget = MediaWidgetV2(config, backend=backend)
        try:
            qapp.processEvents()
            assert all(callable(widget.callbacks[action.split()[0]]) for action in actions)
            assert (widget.callback_left, widget.callback_middle, widget.callback_right) == tuple(callbacks.values())
            assert widget.objectName() == "media-v2"
            assert {"widget", "media-v2-widget", "themed"} <= set(str(widget._widget_frame.property("class")).split())
            assert "widget-container" in str(widget._widget_container.property("class")).split()
            assert widget.bar_surface.objectName() == widget.bar_surface.property("class") == "media-v2-bar"
            assert widget.info.objectName() == "media-info"
            assert {"btn", "media-info"} <= set(str(widget.info.property("class")).split())
            assert widget.art.objectName() == "media-art"
            assert {"media-art", "artwork"} <= set(str(widget.art.property("class")).split())
            assert widget.text_column.objectName() == "media-v2-text"
            assert widget.title.objectName() == "media-v2-title"
            assert {"media-title", "title"} <= set(str(widget.title.property("class")).split())
            assert widget.time.objectName() == "media-v2-time"
            assert {"media-time"} <= set(str(widget.time.property("class")).split())
            assert widget.controls.objectName() == widget.controls.property("class") == "media-controls"
            assert widget.controls.play.objectName() == "media-play"
            assert {"btn", "transport", "play"} <= set(str(widget.controls.play.property("class")).split())
            assert widget.controls.previous.objectName() == "media-previous"
            assert {"btn", "transport", "previous"} <= set(str(widget.controls.previous.property("class")).split())
            assert widget.controls.next.objectName() == "media-next"
            assert {"btn", "transport", "next"} <= set(str(widget.controls.next.property("class")).split())
            for child in (widget.info, widget.art, widget.text_column, widget.controls):
                assert widget.bar_surface.isAncestorOf(child)
        finally:
            sip.delete(widget)
            await backend.aclose()

    asyncio.run(run())


def test_media_v2_schema_retains_full_custom_options() -> None:
    config = MediaV2Config.model_validate({"popup": {"show_equalizer": True, "disc": {"visualizer": True}}})
    assert config.popup.show_equalizer
    assert config.popup.disc.visualizer


def test_media_v2_lyrics_defaults_and_validation() -> None:
    defaults = MediaV2Config().popup.lyrics
    assert defaults.model_dump() == {
        "alignment": "left",
        "center_position": 0.44,
        "lines_before": -1,
        "lines_after": -1,
        "inactive_opacity": -1.0,
        "active_color": None,
        "inactive_color": None,
        "font_family": "",
        "font_size": 18,
        "font_weight": 700,
        "margins": {"horizontal": 4, "vertical": 0, "placeholder": 8},
        "line_height": 30,
        "line_spacing": 6,
        "animation_duration_ms": 320,
        "browse_return_ms": 4000,
        "drag_threshold": 4,
        "auto_lookup": True,
        "better_lyrics_enabled": True,
        "musixmatch_enabled": False,
        "musixmatch_api_key": "",
        "provider_order": ["lrclib", "netease", "better_lyrics"],
        "request_spacing_ms": 250,
        "request_timeout_ms": 10000,
    }
    custom = MediaV2Config.model_validate(
        {
            "popup": {
                "lyrics": {
                    "alignment": "center",
                    "visible_lines_before": 2,
                    "visible_lines_after": 3,
                    "activeLineColor": "#ff00aa",
                    "inactive_color": "#112233",
                    "provider_order": ["netease"],
                }
            }
        }
    ).popup.lyrics
    assert custom.alignment == "center"
    assert (custom.lines_before, custom.lines_after) == (2, 3)
    assert custom.active_color == "#ff00aa"
    assert custom.provider_order == ["netease"]
    private = MediaV2Config.model_validate(
        {
            "popup": {
                "lyrics": {
                    "provider_order": [
                        "musixmatch",
                        "better_lyrics",
                        "lrclib",
                        "netease",
                    ],
                    "musixmatch_enabled": True,
                    "musixmatch_api_key": "fixture-key",
                }
            }
        }
    ).popup.lyrics
    assert private.active_provider_order() == [
        "musixmatch",
        "better_lyrics",
        "lrclib",
        "netease",
    ]
    disabled = MediaV2Config.model_validate({"popup": {"lyrics": {"provider_order": ["musixmatch"]}}}).popup.lyrics
    assert disabled.active_provider_order() == ["lrclib", "netease", "better_lyrics"]
    with pytest.raises(ValidationError):
        MediaV2Config.model_validate({"popup": {"lyrics": {"provider_order": ["lyrics_ovh"]}}})
    with pytest.raises(ValidationError):
        MediaV2Config.model_validate({"popup": {"lyrics": {"provider_order": ["youtube_music"]}}})
    with pytest.raises(ValidationError, match="valid Qt color"):
        MediaV2Config.model_validate({"popup": {"lyrics": {"active_color": "not-a-color"}}})
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        MediaV2Config.model_validate({"popup": {"lyrics": {"provider_order": ["lrclib", "lrclib"]}}})


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
        try:
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
        finally:
            popup.equalizer.apo.shutdown()
            sip.delete(widget)
            await backend.aclose()

    asyncio.run(run())
