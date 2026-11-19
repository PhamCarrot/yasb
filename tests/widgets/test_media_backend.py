# pyright: reportPrivateUsage=false

import asyncio
import threading
from collections.abc import Callable
from typing import Any

import PyQt6.sip as sip
import pytest
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication

from core.widgets.services.media import windows
from core.widgets.services.media.audio_device import DefaultAudioOutputService
from core.widgets.services.media.backend import MediaBackend
from core.widgets.services.media.model import Capabilities, Metadata, Playback, PlaybackState, Player, Timeline


class Source:
    def __init__(self, *, failure: str = "", gate: asyncio.Event | None = None) -> None:
        self.failure = failure
        self.gate = gate
        self.entered = asyncio.Event()
        self.emit: Callable[[str, str | None, Any], None] = self.ignore_event
        self.starts = 0
        self.closes = 0
        self.reads: list[str] = []
        self.refreshes: list[str] = []
        self.actions: list[tuple[str, str, Any]] = []

    @staticmethod
    def ignore_event(kind: str, session_id: str | None, payload: Any) -> None:
        pass

    async def start(self, emit: Callable[[str, str | None, Any], None]) -> None:
        self.starts += 1
        self.emit = emit
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.failure:
            raise RuntimeError(self.failure)

    def populate(self) -> None:
        self.emit("sessions", None, (Player("same-id", "test.app", "Test player"),))
        self.emit(
            "playback", "same-id", Playback(PlaybackState.PLAYING, capabilities=Capabilities(can_play_pause=True))
        )
        self.emit("timeline", "same-id", Timeline(position=5, duration=100, known=True))
        self.emit("metadata", "same-id", None)

    async def metadata(self, session_id: str) -> Metadata:
        self.reads.append(session_id)
        return Metadata(title="Current track")

    async def invoke(self, session_id: str, action: str, value: Any = None) -> bool:
        self.actions.append((session_id, action, value))
        return True

    def refresh(self, session_id: str) -> None:
        self.refreshes.append(session_id)

    def close(self) -> None:
        self.closes += 1


@pytest.mark.parametrize("retry", ["refresh", "start"])
def test_default_source_is_replaced_after_startup_failure(monkeypatch: pytest.MonkeyPatch, retry: str) -> None:
    async def run() -> None:
        failed, replacement = Source(failure="manager unavailable"), Source()
        sources = iter((failed, replacement))
        monkeypatch.setattr(windows, "WindowsMediaSource", lambda: next(sources))
        backend = MediaBackend(autostart=False)
        try:
            await backend.start()
            assert not backend.state.ready
            assert backend.state.error == "manager unavailable"
            assert failed.closes == 1

            if retry == "refresh":
                backend.refresh()
            await backend.start()
            assert backend.state.ready
            assert backend.state.error == ""
            assert failed.starts == replacement.starts == 1
        finally:
            await backend.aclose()
        assert failed.closes == replacement.closes == 1

    asyncio.run(run())


def test_concurrent_start_and_refresh_share_startup_when_one_waiter_is_cancelled() -> None:
    async def run() -> None:
        gate = asyncio.Event()
        source = Source(gate=gate)
        backend = MediaBackend(source, autostart=False)
        waiters = [asyncio.create_task(backend.start()) for _ in range(10)]
        try:
            await asyncio.wait_for(source.entered.wait(), 2)
            waiters[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiters[0]
            for _ in range(20):
                backend.refresh()
            assert source.starts == 1
            assert not backend.state.ready
            gate.set()
            await asyncio.gather(*waiters[1:])
            assert backend.state.ready
        finally:
            await backend.aclose()
        assert source.closes == 1
        assert not backend._tasks

    asyncio.run(run())


def test_factory_failure_can_be_retried() -> None:
    async def run() -> None:
        source = Source()
        creations = 0

        def factory() -> Source:
            nonlocal creations
            creations += 1
            if creations == 1:
                raise RuntimeError("construction failed")
            return source

        backend = MediaBackend(source_factory=factory, autostart=False)
        try:
            await backend.start()
            assert backend.state.error == "construction failed"
            backend.refresh()
            await backend.start()
            assert backend.state.ready and not backend.state.error
            assert creations == 2
        finally:
            await backend.aclose()
        assert source.closes == 1

    asyncio.run(run())


def test_native_partial_subscription_failure_is_cleaned_before_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        class Manager:
            def __init__(self, fail: bool) -> None:
                self.fail = fail
                self.removed: list[tuple[str, int]] = []

            def add_sessions_changed(self, callback: Callable[..., Any]) -> int:
                return 1

            def add_current_session_changed(self, callback: Callable[..., Any]) -> int:
                if self.fail:
                    raise RuntimeError("subscription failed")
                return 2

            def remove_sessions_changed(self, token: int) -> None:
                self.removed.append(("sessions", token))

            def remove_current_session_changed(self, token: int) -> None:
                self.removed.append(("current", token))

            def get_sessions(self) -> tuple[()]:
                return ()

        failed, replacement = Manager(True), Manager(False)
        managers = iter((failed, replacement))

        class Request:
            @staticmethod
            async def request_async() -> Manager:
                return next(managers)

        monkeypatch.setattr(windows, "SessionManager", Request)
        backend = MediaBackend(autostart=False)
        try:
            await backend.start()
            assert backend.state.error == "subscription failed"
            assert failed.removed == [("sessions", 1)]
            backend.refresh()
            await backend.start()
            assert backend.state.ready
            assert not replacement.removed
        finally:
            await backend.aclose()
        assert failed.removed == [("sessions", 1)]
        assert replacement.removed == [("current", 2), ("sessions", 1)]
        assert not backend._tasks

    asyncio.run(run())


def test_injected_source_without_factory_preserves_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        def forbidden_factory() -> Source:
            pytest.fail("An injected source must not fall back to native Windows media")

        monkeypatch.setattr(windows, "WindowsMediaSource", forbidden_factory)
        source = Source(failure="injected failure")
        backend = MediaBackend(source, autostart=False)
        try:
            await backend.start()
            backend.refresh()
            await backend.start()
            assert not backend.state.ready
            assert backend.state.error == "injected failure"
            assert source.starts == source.closes == 1
        finally:
            await backend.aclose()
        assert source.closes == 1

    asyncio.run(run())


def test_retired_events_and_metadata_cannot_reach_reused_session_id() -> None:
    async def run() -> None:
        startup_gate, metadata_gate, reading = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class DelayedMetadata(Source):
            async def metadata(self, session_id: str) -> Metadata:
                self.reads.append(session_id)
                reading.set()
                try:
                    await metadata_gate.wait()
                except asyncio.CancelledError:
                    await metadata_gate.wait()  # Simulate a native operation completing after cancellation.
                return Metadata(title="Retired track")

        failed = DelayedMetadata(failure="partial startup failed", gate=startup_gate)
        replacement = Source()
        backend = MediaBackend(failed, source_factory=lambda: replacement, autostart=False, clock=lambda: 0.0)
        errors: list[str] = []

        def on_error(sid: str, message: str) -> None:
            errors.append(message)

        backend.error_occurred.connect(on_error)
        startup = asyncio.create_task(backend.start())
        try:
            await asyncio.wait_for(failed.entered.wait(), 2)
            failed.populate()
            await asyncio.wait_for(reading.wait(), 2)
            old_read = backend._records["same-id"].metadata_task
            assert old_read is not None
            assert backend.select_session("same-id")
            assert backend._timer is not None
            startup_gate.set()
            await startup
            assert not backend.state.sessions
            assert backend.state.manual_session_id is None
            assert backend._timer is None
            backend.refresh()
            await backend.start()
            replacement.populate()
            await asyncio.sleep(0)
            current = backend.state

            failed.emit("sessions", None, (Player("retired-id", "old.app", "Retired"),))
            failed.emit("error", "same-id", "late source error")
            failed.emit("timeline", "same-id", Timeline(position=99, duration=100, known=True))
            failed.emit("metadata", "same-id", None)
            metadata_gate.set()
            await old_read
            assert backend.state == current
            assert backend.state.active is not None
            assert backend.state.active.metadata.title == "Current track"
            assert errors == ["partial startup failed"]
            assert failed.refreshes == []
            assert replacement.reads == replacement.refreshes == ["same-id"]
        finally:
            startup_gate.set()
            metadata_gate.set()
            await backend.aclose()
        assert failed.closes == replacement.closes == 1
        assert not backend._tasks

    asyncio.run(run())


def test_queued_work_from_failed_startup_never_dispatches_to_replacement() -> None:
    async def run() -> None:
        queued: list[asyncio.Task[bool]] = []

        class PublishingFailure(Source):
            async def start(self, emit: Callable[[str, str | None, Any], None]) -> None:
                await super().start(emit)
                self.populate()
                queued.append(backend.play_pause())
                raise RuntimeError("failed after initial inventory")

        failed, replacement = PublishingFailure(), Source()
        backend = MediaBackend(failed, source_factory=lambda: replacement, autostart=False)
        try:
            await backend.start()
            await backend.start()
            replacement.populate()
            await asyncio.sleep(0)
            assert len(queued) == 1
            assert queued[0].cancelled()
            assert failed.reads == failed.actions == []
            assert replacement.actions == []
            assert replacement.reads == ["same-id"]
            assert backend.state.ready
        finally:
            await backend.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("action_fails", [False, True])
def test_late_action_result_or_error_does_not_notify_replacement(action_fails: bool) -> None:
    async def run() -> None:
        startup_gate, action_gate, invoked = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class DelayedAction(Source):
            async def invoke(self, session_id: str, action: str, value: Any = None) -> bool:
                self.actions.append((session_id, action, value))
                invoked.set()
                try:
                    await action_gate.wait()
                except asyncio.CancelledError:
                    await action_gate.wait()
                if action_fails:
                    raise RuntimeError("retired action error")
                return True

        failed = DelayedAction(failure="startup failed", gate=startup_gate)
        replacement = Source()
        backend = MediaBackend(failed, source_factory=lambda: replacement, autostart=False)
        finished: list[tuple[str, str, bool]] = []

        def on_finished(sid: str, action: str, accepted: bool) -> None:
            finished.append((sid, action, accepted))

        backend.action_finished.connect(on_finished)
        startup = asyncio.create_task(backend.start())
        try:
            await asyncio.wait_for(failed.entered.wait(), 2)
            failed.populate()
            action = backend.play_pause()
            await asyncio.wait_for(invoked.wait(), 2)
            startup_gate.set()
            await startup
            await backend.start()
            replacement.populate()
            await asyncio.sleep(0)
            refreshes = list(replacement.refreshes)
            action_gate.set()
            assert await action is not action_fails
            assert not finished
            assert not backend.state.error
            assert replacement.refreshes == refreshes
            assert not replacement.actions
        finally:
            startup_gate.set()
            action_gate.set()
            await backend.aclose()
        assert not backend._tasks

    asyncio.run(run())


@pytest.mark.parametrize("fail_after_cancel", [False, True])
def test_close_during_startup_cannot_resurrect_backend(fail_after_cancel: bool) -> None:
    async def run() -> None:
        gate = asyncio.Event()

        class LateStartup(Source):
            async def start(self, emit: Callable[[str, str | None, Any], None]) -> None:
                try:
                    await super().start(emit)
                except asyncio.CancelledError:
                    await gate.wait()
                self.populate()
                if fail_after_cancel:
                    raise RuntimeError("late startup failure")

        source = LateStartup(gate=gate)
        backend = MediaBackend(source, autostart=False)
        waiter = asyncio.create_task(backend.start())
        await asyncio.wait_for(source.entered.wait(), 2)
        backend.close()
        gate.set()
        await asyncio.gather(waiter, return_exceptions=True)
        await backend.aclose()
        backend.refresh()
        await backend.start()
        assert not backend.state.ready
        assert not backend.state.sessions
        assert not backend.state.error
        assert source.starts == source.closes == 1
        assert not backend._tasks
        assert backend._timer is None

    asyncio.run(run())


def test_close_before_autostart_does_not_construct_source() -> None:
    async def run() -> None:
        def forbidden_factory() -> Source:
            pytest.fail("Shutdown must cancel the pending autostart")

        backend = MediaBackend(source_factory=forbidden_factory)
        await backend.aclose()
        assert not backend._tasks
        assert not backend.state.ready

    asyncio.run(run())


def test_healthy_refresh_preserves_source_and_manual_selection() -> None:
    async def run() -> None:
        source = Source()
        backend = MediaBackend(source, autostart=False)
        try:
            await backend.start()
            source.populate()
            await asyncio.sleep(0)
            assert backend.select_session("same-id")
            source.emit("error", "same-id", "transient sample error")
            backend.refresh()
            await backend.start()
            await asyncio.sleep(0)
            assert backend.state.ready and not backend.state.error
            assert backend.state.manual_session_id == "same-id"
            assert source.starts == 1 and source.closes == 0
            assert source.reads == ["same-id", "same-id"]
        finally:
            await backend.aclose()
        assert source.closes == 1

    asyncio.run(run())


def test_duplicate_metadata_refresh_preserves_timeline_until_timeline_event() -> None:
    async def run() -> None:
        class DuplicateMetadataSource(Source):
            def __init__(self) -> None:
                super().__init__()
                self.metadata_values = iter(
                    (
                        Metadata(title="Same song", artist="First artist", album="Album", track_number=1),
                        Metadata(title="Same song", artist="Second artist", album="Album", track_number=1),
                    )
                )

            async def metadata(self, session_id: str) -> Metadata:
                self.reads.append(session_id)
                return next(self.metadata_values)

        source = DuplicateMetadataSource()
        backend = MediaBackend(source, autostart=False, clock=lambda: 0.0)
        try:
            await backend.start()
            source.emit("sessions", None, (Player("same-id", "test.app", "Test player"),))
            source.emit("playback", "same-id", Playback(PlaybackState.PLAYING))
            source.emit("timeline", "same-id", Timeline(position=42, duration=100, known=True))
            source.emit("metadata", "same-id", None)
            await asyncio.sleep(0)
            assert backend.state.active is not None and backend.state.active.metadata_ready

            first = backend.state.active
            assert first is not None
            assert first.artist == "First artist"
            assert first.position == 42
            first_revision = first.seek_revision

            source.emit("metadata", "same-id", None)
            await asyncio.sleep(0)
            second = backend.state.active
            assert second is not None
            assert second.artist == "Second artist"
            assert second.seek_revision != first_revision
            assert second.position == 42

            source.emit("timeline", "same-id", Timeline(position=7, duration=100, known=True))
            assert backend.state.active is not None and backend.state.active.position == 7
        finally:
            await backend.aclose()

    asyncio.run(run())


def test_default_output_instance_recreates_after_shutdown_without_device_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[DefaultAudioOutputService] = []

    def init(service: DefaultAudioOutputService) -> None:
        QObject.__init__(service)
        service._closed = False
        created.append(service)

    def shutdown(service: DefaultAudioOutputService) -> None:
        service._closed = True

    monkeypatch.setattr(DefaultAudioOutputService, "__init__", init)
    monkeypatch.setattr(DefaultAudioOutputService, "shutdown", shutdown)
    previous = DefaultAudioOutputService._instance
    DefaultAudioOutputService._instance = None
    try:
        first = DefaultAudioOutputService.instance()
        first.shutdown()
        second = DefaultAudioOutputService.instance()
        assert second is not first
        assert first._closed and not second._closed
        assert created == [first, second]
    finally:
        DefaultAudioOutputService._instance = previous


def test_default_output_instance_recreates_after_deleted_qobject(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[DefaultAudioOutputService] = []

    def init(service: DefaultAudioOutputService) -> None:
        QObject.__init__(service)
        service._closed = False
        created.append(service)

    monkeypatch.setattr(DefaultAudioOutputService, "__init__", init)
    previous = DefaultAudioOutputService._instance
    DefaultAudioOutputService._instance = None
    first: DefaultAudioOutputService | None = None
    second: DefaultAudioOutputService | None = None
    try:
        first = DefaultAudioOutputService.instance()
        sip.delete(first)
        second = DefaultAudioOutputService.instance()
        assert second is not first
        assert created == [first, second]
    finally:
        if second is not None:
            sip.delete(second)
        DefaultAudioOutputService._instance = previous


def test_media_backend_shared_recreates_after_deleted_qobject(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    def init(backend: MediaBackend) -> None:
        QObject.__init__(backend)
        backend._closed = False

    monkeypatch.setattr(MediaBackend, "__init__", init)
    previous = MediaBackend._shared
    MediaBackend._shared = None
    first: MediaBackend | None = None
    second: MediaBackend | None = None
    try:
        first = MediaBackend.shared()
        sip.delete(first)
        second = MediaBackend.shared()
        assert second is not first
    finally:
        if second is not None:
            sip.delete(second)
        MediaBackend._shared = previous


def test_windows_source_post_snapshots_loop_before_concurrent_close() -> None:
    class Loop:
        def call_soon_threadsafe(self, callback: Callable[..., Any], *args: Any) -> None:
            callback(*args)

    class RaceSource(windows.WindowsMediaSource):
        def __init__(self) -> None:
            self._block_first_loop_read = True
            self.loop_read = threading.Event()
            self.release_loop_read = threading.Event()
            self.close_started = threading.Event()
            self.close_finished = threading.Event()
            super().__init__()

        def __getattribute__(self, name: str) -> Any:
            if name == "_loop" and object.__getattribute__(self, "_block_first_loop_read"):
                object.__setattr__(self, "_block_first_loop_read", False)
                object.__getattribute__(self, "loop_read").set()
                object.__getattribute__(self, "release_loop_read").wait(1)
                return object.__getattribute__(self, name)
            return object.__getattribute__(self, name)

        def close(self) -> None:
            self.close_started.set()
            super().close()
            self.close_finished.set()

    source = RaceSource()
    source._loop = Loop()  # type: ignore[assignment]
    errors: list[BaseException] = []

    def post() -> None:
        try:
            source._post(lambda: None)
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=post)
    worker.start()
    assert source.loop_read.wait(1)
    closer = threading.Thread(target=source.close)
    closer.start()
    assert source.close_started.wait(1)
    assert not source.close_finished.wait(0.1)
    source.release_loop_read.set()
    worker.join(1)
    closer.join(1)
    assert not worker.is_alive()
    assert not closer.is_alive()
    assert errors == []
