"""Event-driven media state and actions; use shared() on YASB's qasync thread."""

import asyncio
import logging
import math
import time
from dataclasses import dataclass, replace
from typing import Protocol

from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal

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

    async def start(self, emit): ...
    async def metadata(self, session_id: str) -> Metadata: ...
    async def invoke(self, session_id: str, action: str, value=None) -> bool: ...
    def refresh(self, session_id: str): ...
    def close(self): ...


@dataclass
class _Record:
    state: MediaSessionState
    anchor: float = 0.0
    revision: int = 0
    timeline_sample: tuple | None = None
    metadata_task: asyncio.Task | None = None


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
    _shared = None

    @classmethod
    def shared(cls):
        if cls._shared is None or cls._shared._closed:
            cls._shared = cls()
        return cls._shared

    @classmethod
    async def aclose_shared(cls):
        """Release the shared native source while the owning qasync loop is alive."""
        backend = cls._shared
        if backend is None:
            return
        await backend.aclose()
        if cls._shared is backend:
            cls._shared = None

    def __init__(
        self,
        source: MediaSource | None = None,
        *,
        autostart=True,
        clock=time.monotonic,
        wall_clock=time.time,
        tick_interval=0.25,
        parent=None,
    ):
        super().__init__(parent)
        if source is None:
            from core.widgets.services.media.windows import WindowsMediaSource

            source = WindowsMediaSource()
        if tick_interval <= 0 or not math.isfinite(tick_interval):
            raise ValueError("tick_interval must be positive and finite")
        self._source = source
        self._loop = asyncio.get_running_loop()
        self._clock = clock
        self._wall_clock = wall_clock
        self._interval = tick_interval
        self._records = {}
        self._tasks = set()
        self._timer = None
        self._closed = False
        self._started = False
        self._manual_id = None
        self._auto_id = None
        self._ready = False
        self._error = ""
        self._state = MediaState()
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.close)
        if autostart:
            self._spawn(self.start())

    @property
    def state(self) -> MediaState:
        return self._state

    def _spawn(self, coroutine):
        task = self._loop.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def start(self):
        if self._started or self._closed:
            return
        self._started = True
        try:
            await self._source.start(self._on_event)
            if not self._closed:
                self._ready = True
                self._publish()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._source.close()
            self._records.clear()
            self._report_error("", str(error))
            self._publish()

    def _report_error(self, session_id, message):
        self._error = message
        logger.warning("Media backend: %s", message)
        self.error_occurred.emit(session_id or "", message)

    def _on_event(self, kind, session_id, payload):
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
        record = self._records.get(session_id)
        if record is None:
            return  # Late event from a removed/replaced native session.
        if kind == "metadata":
            record.revision += 1
            if record.metadata_task:
                record.metadata_task.cancel()
            # Keep the current presentation while the newest native metadata read
            # is pending. The revision gate below prevents an older result from
            # winning, and the completed read decides whether the track changed.
            record.state = replace(record.state, artwork_pending=True)
            record.metadata_task = self._spawn(self._load_metadata(session_id, record, record.revision))
        elif kind == "playback":
            self._advance(record, self._clock())
            record.state = replace(record.state, playback=payload)
            if payload.state == PlaybackState.CLOSED:
                record.revision += 1
                if record.metadata_task:
                    record.metadata_task.cancel()
                record.state = replace(
                    record.state, metadata=Metadata(), timeline=Timeline(), metadata_ready=False, artwork_pending=False
                )
                record.timeline_sample = None
                if self._manual_id == session_id:
                    self._manual_id = None
        elif kind == "timeline":
            self._apply_timeline(record, payload)
        self._publish()

    async def _load_metadata(self, session_id, record, revision):
        try:
            metadata = await self._source.metadata(session_id)
            if not self._is_current_read(session_id, record, revision):
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
            )
            if track_changed:
                record.timeline_sample = None
                record.anchor = self._clock()
            if metadata.artwork_error:
                self._report_error(session_id, metadata.artwork_error)
            self._source.refresh(session_id)
            self._publish()
        except asyncio.CancelledError:
            pass
        except Exception as error:
            if self._is_current_read(session_id, record, revision):
                # A transient progressive refresh failure must not erase a valid
                # track already on screen. First-load failures still remain empty.
                metadata = record.state.metadata if record.state.metadata_ready else Metadata()
                record.state = replace(record.state, metadata=metadata, artwork_pending=False)
                self._report_error(session_id, str(error))
                self._publish()

    def _is_current_read(self, session_id, record, revision):
        return not self._closed and self._records.get(session_id) is record and record.revision == revision

    def _apply_timeline(self, record, sample):
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
    def _advance(record, now):
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
            record = self._records.get(session_id)
            if record is None or record.state.playback.state == PlaybackState.CLOSED:
                return False
        self._manual_id = session_id
        self._publish()
        return True

    def switch_session(self, direction: int = 1) -> bool:
        ids = [s.session_id for s in self.state.usable_sessions]
        if not ids:
            return False
        index = ids.index(self.state.active_session_id) if self.state.active_session_id in ids else 0
        return self.select_session(ids[(index + direction) % len(ids)])

    def refresh(self):
        """Explicit retry/resync, not a periodic poll."""
        if self._closed:
            return
        self._error = ""
        for sid in tuple(self._records):
            self._source.refresh(sid)
            self._on_event("metadata", sid, None)
        self._publish()

    def _request(self, action, value=None):
        sid = self.state.active_session_id
        record = self._records.get(sid)
        revision = record.revision if record else -1
        return self._spawn(self._execute(sid, revision, action, value))

    async def _execute(self, sid, revision, action, value):
        accepted = False
        try:
            record = self._records.get(sid)
            if self._closed or record is None:
                return False
            if not getattr(record.state.capabilities, "can_" + action):
                return False
            if action == "seek" and (
                record.revision != revision or not record.state.is_seekable or not math.isfinite(value)
            ):
                return False
            if action == "repeat" and value not in (0, 1, 2):
                return False
            accepted = await self._source.invoke(sid, action, value)
            if accepted and not self._closed and self._records.get(sid) is record:
                self._source.refresh(sid)
            return accepted
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if not self._closed:
                self._report_error(sid, str(error))
                self._publish()
            return False
        finally:
            if not self._closed:
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

    def seek(self, position: float):
        return self._request("seek", position)

    def set_shuffle(self, enabled: bool):
        return self._request("shuffle", enabled)

    def set_repeat(self, mode: int):
        return self._request("repeat", mode)

    def close(self):
        """Synchronous aboutToQuit cleanup; aclose() additionally drains cancellation."""
        if self._closed:
            return
        self._closed = True
        for task in tuple(self._tasks):
            task.cancel()
        self._source.close()
        self._records.clear()
        self._manual_id = None
        self._auto_id = None
        self._ready = False
        self._publish()

    async def aclose(self):
        self.close()
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
