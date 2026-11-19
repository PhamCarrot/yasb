"""Event-driven media state and actions; use shared() on YASB's qasync thread."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, replace
from typing import Any, ClassVar, Protocol

from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal

from core.utils.qobject import is_valid_qobject
from core.widgets.services.media.model import (
    MediaSessionState,
    MediaState,
    Metadata,
    PlaybackState,
    Timeline,
    select_active,
)

logger = logging.getLogger("MediaBackend")


def _same_track(old: Metadata, new: Metadata) -> bool:
    """Treat progressively completed metadata as one track when its stable fields agree."""
    old_title = old.title.strip().casefold()
    new_title = new.title.strip().casefold()
    if old_title and new_title:
        if old_title != new_title:
            return False
        if old.track_number and new.track_number and old.track_number != new.track_number:
            return False
        if old.album and new.album and old.album.strip().casefold() != new.album.strip().casefold():
            return False
        return True
    if old.track_number and new.track_number:
        return old.track_number == new.track_number and (
            not old.album or not new.album or old.album.strip().casefold() == new.album.strip().casefold()
        )
    return False


class MediaSource(Protocol):
    """Sources deliver sessions/metadata/playback/timeline/error events on the owning loop."""

    async def start(self, emit: Callable[[str, str | None, Any], None]): ...
    async def metadata(self, session_id: str) -> Metadata: ...
    async def invoke(self, session_id: str, action: str, value: Any = None) -> bool: ...
    def refresh(self, session_id: str): ...
    def close(self): ...


@dataclass
class _Record:
    state: MediaSessionState
    anchor: float = 0.0
    revision: int = 0
    timeline_sample: tuple[float, float, float | None, bool] | None = None
    metadata_task: asyncio.Task[None] | None = None


class MediaBackend(QObject):
    """Immutable state boundary for future widgets, with no QWidget dependencies.

    Public methods and construction belong to the qasync/Qt thread. Actions return
    awaitable Tasks, so both synchronous Qt callbacks and async consumers can use
    play(), pause(), play_pause(), next(), previous(), seek(seconds), set_shuffle()
    and set_repeat(). Their bool result means Windows accepted the request, not that
    playback has already changed. State only changes from events/native samples.
    """

    state_changed = pyqtSignal(object)  # MediaState; authoritative, atomic snapshot
    sessions_changed = pyqtSignal(object)  # tuple[MediaSessionState, ...], inventory changes
    active_session_changed = pyqtSignal(object)  # str | None
    position_changed = pyqtSignal(object)  # active MediaSessionState | None
    error_occurred = pyqtSignal(str, str)  # session id (or empty), message
    action_finished = pyqtSignal(str, str, bool)  # captured session id, action, accepted
    _shared: ClassVar[MediaBackend | None] = None
    _drain_task: ClassVar[asyncio.Task[None] | None] = None

    @classmethod
    def shared(cls) -> MediaBackend:
        if cls._shared is None or (
            cls._drain_task is None and (not is_valid_qobject(cls._shared) or cls._shared._closed)
        ):
            cls._shared = cls()
        return cls._shared

    @classmethod
    def shared_instance(cls) -> MediaBackend | None:
        return cls._shared

    @property
    def closed(self) -> bool:
        return self._closed

    @classmethod
    async def aclose_shared(cls) -> None:
        """Release the shared native source while the owning qasync loop is alive."""
        task = cls._drain_task
        if task is None:
            backend = cls._shared
            if backend is None:
                return
            task = cls._drain_task = asyncio.create_task(cls._drain_shared(backend))
            backend.close()
        await asyncio.shield(task)

    @classmethod
    async def _drain_shared(cls, backend: MediaBackend) -> None:
        try:
            await backend.aclose()
        finally:
            if cls._drain_task is asyncio.current_task():
                if cls._shared is backend:
                    cls._shared = None
                cls._drain_task = None

    def __init__(
        self,
        source: MediaSource | None = None,
        *,
        source_factory: Callable[[], MediaSource] | None = None,
        autostart: bool = True,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        tick_interval: float = 0.25,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if source is None and source_factory is None:
            from core.widgets.services.media.windows import WindowsMediaSource

            source_factory = WindowsMediaSource
        if tick_interval <= 0 or not math.isfinite(tick_interval):
            raise ValueError("tick_interval must be positive and finite")
        self._source = source
        self._source_factory = source_factory
        self._generation = 0
        self._read_revision = 0
        self._loop = asyncio.get_running_loop()
        self._clock = clock
        self._wall_clock = wall_clock
        self._interval = tick_interval
        self._records: dict[str, _Record] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._timer: asyncio.TimerHandle | None = None
        self._closed = False
        self._start_task: asyncio.Task[None] | None = None
        self._manual_id: str | None = None
        self._auto_id: str | None = None
        self._ready = False
        self._error = ""
        self._state = MediaState()
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.close)
        if autostart:
            self._ensure_start()

    @property
    def state(self) -> MediaState:
        return self._state

    def _spawn[T](self, coroutine: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
        task = self._loop.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def start(self):
        """Join startup/retry; cancelling a caller does not cancel shared startup.

        Closed sources are terminal. Injected sources need an explicit
        source_factory to support replacement after a failed attempt.
        """
        task = self._ensure_start()
        if task is not None:
            await asyncio.shield(task)

    def _ensure_start(self) -> asyncio.Task[None] | None:
        if self._closed or self._ready:
            return None
        if self._start_task is not None and not self._start_task.done():
            return self._start_task
        if self._source is None and self._source_factory is None:
            return None
        self._start_task = self._spawn(self._start_source())
        return self._start_task

    async def _start_source(self):
        generation = self._generation
        try:
            source = self._source
            if source is None:
                assert self._source_factory is not None
                source = self._source_factory()
                self._source = source
            self._error = ""

            def emit(kind: str, session_id: str | None, payload: Any):
                if self._is_current_source(source, generation):
                    self._on_event(kind, session_id, payload)

            await source.start(emit)
            if self._is_current_source(source, generation):
                self._ready = True
                self._publish()
        except asyncio.CancelledError:
            if not self._closed:
                self._retire_source()
                self._publish()
            raise
        except Exception as error:
            if not self._closed:
                self._retire_source()
                self._report_error("", str(error))
                self._publish()

    def _is_current_source(self, source: MediaSource | None, generation: int) -> bool:
        return not self._closed and self._source is source and self._generation == generation

    def _retire_source(self):
        # Invalidate callbacks before closing native subscriptions or cancelling work.
        self._generation += 1
        source, self._source = self._source, None
        current = asyncio.current_task(self._loop)
        for task in tuple(self._tasks):
            if task is not current:
                task.cancel()
        self._records.clear()
        self._manual_id = None
        self._auto_id = None
        self._ready = False
        if source is not None:
            source.close()

    def _report_error(self, session_id: str | None, message: str):
        self._error = message
        logger.warning("Media backend: %s", message)
        self.error_occurred.emit(session_id or "", message)

    def _on_event(self, kind: str, session_id: str | None, payload: Any):
        if self._closed:
            return
        if kind == "error":
            self._report_error(session_id, payload)
            self._publish()
            return
        if kind == "sessions":
            live = {player.session_id for player in payload}
            for sid in tuple(self._records):
                if sid not in live:
                    record = self._records.pop(sid)
                    if record.metadata_task:
                        record.metadata_task.cancel()
            for player in payload:
                if player.session_id not in self._records:
                    self._records[player.session_id] = _Record(MediaSessionState(player), self._clock())
                else:
                    record = self._records[player.session_id]
                    record.state = replace(record.state, player=player)
            if self._manual_id not in live:
                self._manual_id = None
            if self._auto_id not in live:
                self._auto_id = None
            self._publish()
            return
        if session_id is None:
            return
        record = self._records.get(session_id)
        if record is None:
            return  # Late event from a removed/replaced native session.
        if kind == "metadata":
            self._read_revision += 1
            record.revision = self._read_revision
            if record.metadata_task:
                record.metadata_task.cancel()
            # Keep the current presentation while the newest native metadata read
            # is pending. The revision gate below prevents an older result from
            # winning, and the completed read decides whether the track changed.
            record.state = replace(record.state, artwork_pending=True, seek_revision=None)
            record.metadata_task = self._spawn(
                self._load_metadata(session_id, record, record.revision, self._source, self._generation)
            )
        elif kind == "playback":
            self._advance(record, self._clock())
            record.state = replace(record.state, playback=payload)
            if payload.state == PlaybackState.CLOSED:
                self._read_revision += 1
                record.revision = self._read_revision
                if record.metadata_task:
                    record.metadata_task.cancel()
                record.state = replace(
                    record.state,
                    metadata=Metadata(),
                    timeline=Timeline(),
                    metadata_ready=False,
                    artwork_pending=False,
                    seek_revision=None,
                )
                record.timeline_sample = None
                if self._manual_id == session_id:
                    self._manual_id = None
        elif kind == "timeline":
            self._apply_timeline(record, payload)
        self._publish()

    async def _load_metadata(
        self, session_id: str, record: _Record, revision: int, source: MediaSource | None, generation: int
    ):
        try:
            if source is None or not self._is_current_read(session_id, record, revision):
                return
            metadata = await source.metadata(session_id)
            if not self._is_current_source(source, generation) or not self._is_current_read(
                session_id, record, revision
            ):
                return
            previous = record.state
            track_changed = previous.metadata_ready and not _same_track(previous.metadata, metadata)
            timeline = Timeline() if track_changed else previous.timeline
            record.state = replace(
                previous,
                metadata=metadata,
                timeline=timeline,
                metadata_ready=True,
                artwork_pending=False,
                seek_revision=revision,
            )
            if track_changed:
                record.timeline_sample = None
                record.anchor = self._clock()
            if metadata.artwork_error:
                self._report_error(session_id, metadata.artwork_error)
            source.refresh(session_id)
            self._publish()
        except asyncio.CancelledError:
            pass
        except Exception as error:
            if self._is_current_source(source, generation) and self._is_current_read(session_id, record, revision):
                # A transient progressive refresh failure must not erase a valid
                # track already on screen. First-load failures still remain empty.
                metadata = record.state.metadata if record.state.metadata_ready else Metadata()
                record.state = replace(record.state, metadata=metadata, artwork_pending=False)
                self._report_error(session_id, str(error))
                self._publish()

    def _is_current_read(self, session_id: str, record: _Record, revision: int):
        return not self._closed and self._records.get(session_id or "") is record and record.revision == revision

    def _apply_timeline(self, record: _Record, sample: Timeline):
        now = self._clock()
        self._advance(record, now)
        signature = (sample.position, sample.start, sample.updated_at, sample.known)
        if signature == record.timeline_sample:
            # Repeated native sample must not rewind an estimated position. Bounds
            # can nevertheless change without LastUpdatedTime or Position changing.
            position = record.state.position
        else:
            position = sample.position
            if sample.known and sample.updated_at is not None and record.state.is_playing:
                position += max(0.0, self._wall_clock() - sample.updated_at) * record.state.playback.rate
        position = max(0.0, position)
        if sample.duration is not None:
            position = min(position, sample.duration)
        record.state = replace(record.state, timeline=replace(sample, position=position))
        record.timeline_sample = signature
        record.anchor = now

    @staticmethod
    def _advance(record: _Record, now: float):
        state = record.state
        position = state.position
        if state.is_playing and state.timeline.known:
            position += max(0.0, now - record.anchor) * state.playback.rate
        position = max(0.0, position)
        if state.duration is not None:
            position = min(position, state.duration)
        record.state = replace(state, timeline=replace(state.timeline, position=position))
        record.anchor = now

    def _publish(self):
        now = self._clock()
        for record in self._records.values():
            self._advance(record, now)
        sessions = tuple(record.state for record in self._records.values())
        selected = select_active(sessions, self._manual_id, self._auto_id)
        if self._manual_id is None:
            self._auto_id = selected
        state = MediaState(sessions, selected, self._manual_id, self._ready, self._error)
        previous = self._state
        self._state = state
        self._schedule_tick()
        if state == previous:
            return
        self.state_changed.emit(state)
        if tuple(s.player for s in state.sessions) != tuple(s.player for s in previous.sessions):
            self.sessions_changed.emit(state.sessions)
        if state.active_session_id != previous.active_session_id:
            self.active_session_changed.emit(state.active_session_id)
        old = previous.active
        active = state.active
        if (old is None) != (active is None) or (
            active is not None
            and (old is None or active.session_id != old.session_id or active.timeline != old.timeline)
        ):
            self.position_changed.emit(active)

    def _schedule_tick(self):
        moving = any(
            s.is_playing
            and s.timeline.known
            and (
                (s.playback.rate > 0 and (s.duration is None or s.position < s.duration))
                or (s.playback.rate < 0 and s.position > 0)
            )
            for s in (r.state for r in self._records.values())
        )
        if moving and not self._closed and self._timer is None:
            self._timer = self._loop.call_later(self._interval, self._tick)
        elif (not moving or self._closed) and self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _tick(self):
        self._timer = None
        if not self._closed:
            self._publish()  # Arithmetic only: never polls Windows.

    def select_session(self, session_id: str | None) -> bool:
        """Pin a live session; None restores automatic selection."""
        if self._closed:
            return False
        if session_id is not None:
            record = self._records.get(session_id or "")
            if record is None or record.state.playback.state == PlaybackState.CLOSED:
                return False
        self._manual_id = session_id
        self._publish()
        return True

    def switch_session(self, direction: int = 1) -> bool:
        ids = [s.session_id for s in self.state.usable_sessions]
        if not ids:
            return False
        index = ids.index(self.state.active_session_id or "") if self.state.active_session_id in ids else 0
        return self.select_session(ids[(index + direction) % len(ids)])

    def refresh(self):
        """Explicit retry/resync, not a periodic poll."""
        if self._closed:
            return
        if not self._ready:
            self._ensure_start()
            return
        assert self._source is not None
        self._error = ""
        for sid in tuple(self._records):
            self._source.refresh(sid)
            self._on_event("metadata", sid, None)
        self._publish()

    def _request(self, action: str, value: Any = None, *, expected_revision: int | None = None):
        sid = self.state.active_session_id
        record = self._records.get(sid or "")
        revision = (
            expected_revision if expected_revision is not None else record.state.seek_revision if record else None
        )
        return self._spawn(self._execute(sid, revision, action, value, self._source, self._generation))

    async def _execute(
        self,
        sid: str | None,
        revision: int | None,
        action: str,
        value: Any,
        source: MediaSource | None,
        generation: int,
    ):
        accepted = False
        try:
            record = self._records.get(sid or "")
            if source is None or not self._is_current_source(source, generation) or record is None or sid is None:
                return False
            if not getattr(record.state.capabilities, "can_" + action):
                return False
            if action == "seek" and (
                record.revision != revision
                or record.state.seek_revision != revision
                or not record.state.is_seekable
                or not math.isfinite(value)
            ):
                return False
            if action == "repeat" and value not in (0, 1, 2):
                return False
            accepted = await source.invoke(sid, action, value)
            if accepted and self._is_current_source(source, generation) and self._records.get(sid or "") is record:
                source.refresh(sid)
            return accepted
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if self._is_current_source(source, generation):
                self._report_error(sid, str(error))
                self._publish()
            return False
        finally:
            if self._is_current_source(source, generation):
                self.action_finished.emit(sid or "", action, accepted)

    def play(self):
        return self._request("play")

    def pause(self):
        return self._request("pause")

    def play_pause(self):
        return self._request("play_pause")

    def next(self):
        return self._request("next")

    def previous(self):
        return self._request("previous")

    def seek(self, position: float, *, expected_revision: int | None = None):
        """Seek only against a current successful metadata read, captured by the UI."""
        return self._request("seek", position, expected_revision=expected_revision)

    def set_shuffle(self, enabled: bool):
        return self._request("shuffle", enabled)

    def set_repeat(self, mode: int):
        return self._request("repeat", mode)

    def close(self):
        """Synchronous aboutToQuit cleanup; aclose() additionally drains cancellation."""
        if self._closed:
            return
        self._closed = True
        self._retire_source()
        self._publish()

    async def aclose(self):
        self.close()
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
