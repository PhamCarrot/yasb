"""GSMTC transport. No Qt/UI objects or presentation policy live here."""

import asyncio
import hashlib
import logging
import math
import threading
from dataclasses import dataclass, field
from uuid import uuid4

from winrt.windows.media import MediaPlaybackAutoRepeatMode
from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as SessionManager
from winrt.windows.storage.streams import Buffer, InputStreamOptions

from core.widgets.services.media.model import (
    Artwork,
    Capabilities,
    Metadata,
    Playback,
    PlaybackState,
    Player,
    Timeline,
    normalize_timeline,
    seek_ticks,
)
from core.widgets.services.media.source_apps import resolve_source_app_name

logger = logging.getLogger("WindowsMediaSource")
MAX_ARTWORK_BYTES = 16 * 1024 * 1024
OPERATION_TIMEOUT = 10


@dataclass
class _Binding:
    session: object
    player: Player
    removers: list = field(default_factory=list)


class WindowsMediaSource:
    """Own all native references; deliver immutable samples on the asyncio/Qt loop.

    WinRT callback threads snapshot playback/timeline under one lock. IReference
    values are read once and immediately converted; no PlaybackInfo crosses threads.
    Session ids distinguish instances, including simultaneous sessions from one app.
    """

    def __init__(self):
        self._loop = None
        self._emit = None
        self._manager = None
        self._bindings = {}
        self._removers = []
        self._lock = threading.RLock()
        self._closed = False
        self._reconcile_queued = False
        self._sample_versions = {}

    async def start(self, emit):
        self._loop = asyncio.get_running_loop()
        self._emit = emit
        manager = await asyncio.wait_for(SessionManager.request_async(), OPERATION_TIMEOUT)
        if self._closed:
            return
        self._manager = manager
        try:
            for name in ("sessions_changed", "current_session_changed"):
                token = getattr(manager, "add_" + name)(self._manager_event)
                self._removers.append((manager, "remove_" + name, token))
            self._reconcile()
        except Exception:
            self.close()
            raise

    def _post(self, callback, *args):
        if self._closed or self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(callback, *args)
        except RuntimeError:
            logger.debug("Media event ignored during loop shutdown")

    def _deliver(self, kind, session_id, payload):
        if not self._closed:
            self._emit(kind, session_id, payload)

    def _manager_event(self, _sender, _args):
        self._post(self._queue_reconcile)

    def _queue_reconcile(self):
        if self._closed or self._reconcile_queued:
            return
        self._reconcile_queued = True
        self._loop.call_soon(self._reconcile)

    def _reconcile(self):
        self._reconcile_queued = False
        if self._closed:
            return
        new_bindings = []
        try:
            with self._lock:
                sessions = list(self._manager.get_sessions())
                remaining = dict(self._bindings)
                live = {}
                added = []
                for session in sessions:
                    # PyWinRT object equality uses native object identity, not AUMID.
                    sid = next((key for key, value in remaining.items() if value.session == session), None)
                    if sid is not None:
                        binding = remaining.pop(sid)
                    else:
                        sid = uuid4().hex
                        app_id = session.source_app_user_model_id or ""
                        try:
                            name = resolve_source_app_name(app_id) or app_id
                        except Exception:
                            logger.exception("Unable to resolve media application name")
                            name = app_id
                        binding = _Binding(session, Player(sid, app_id, name))
                        try:
                            for native, kind in (
                                ("media_properties_changed", "metadata"),
                                ("playback_info_changed", "playback"),
                                ("timeline_properties_changed", "timeline"),
                            ):
                                token = getattr(session, "add_" + native)(self._callback(sid, kind))
                                binding.removers.append((session, "remove_" + native, token))
                        except Exception:
                            self._unsubscribe(binding.removers)
                            raise
                        added.append(sid)
                        new_bindings.append(binding)
                    live[sid] = binding
                for binding in remaining.values():
                    self._unsubscribe(binding.removers)
                self._bindings = live
                self._sample_versions = {key: value for key, value in self._sample_versions.items() if key[0] in live}
                new_bindings.clear()
            # Inventory precedes every initial sample; removal invalidates in-flight reads.
            self._deliver("sessions", None, tuple(b.player for b in live.values()))
            for sid in added:
                self.refresh(sid)
                self._deliver("metadata", sid, None)
        except Exception as error:
            with self._lock:
                for binding in new_bindings:
                    self._unsubscribe(binding.removers)
            logger.exception("Unable to enumerate media sessions")
            self._deliver("error", None, str(error))

    def _deliver_sample(self, kind, session_id, sample, version):
        with self._lock:
            current = self._sample_versions.get((session_id, kind))
        if version == current and session_id in self._bindings:
            self._deliver(kind, session_id, sample)

    def _read_sample(self, kind, session_id, session, *, queued):
        error = None
        with self._lock:
            if self._closed or session_id not in self._bindings:
                return
            key = (session_id, kind)
            version = self._sample_versions.get(key, 0) + 1
            self._sample_versions[key] = version
            try:
                sample = self._playback(session) if kind == "playback" else self._timeline(session)
            except Exception as exc:
                sample = Playback() if kind == "playback" else Timeline()
                error = str(exc)
            if queued:
                self._post(self._deliver_sample, kind, session_id, sample, version)
        if not queued:
            self._deliver_sample(kind, session_id, sample, version)
        if error is not None:
            if queued:
                self._post(self._deliver, "error", session_id, error)
            else:
                self._deliver("error", session_id, error)

    def _callback(self, session_id, kind):
        def callback(sender, _args):
            if self._closed:
                return
            if kind == "metadata":
                self._post(self._deliver, kind, session_id, None)
                return
            self._read_sample(kind, session_id, sender, queued=True)

        return callback

    @staticmethod
    def _playback(session):
        info = session.get_playback_info()
        if info is None:
            return Playback()
        status = int(info.playback_status)
        states = (
            PlaybackState.CLOSED,
            PlaybackState.OPENED,
            PlaybackState.CHANGING,
            PlaybackState.STOPPED,
            PlaybackState.PLAYING,
            PlaybackState.PAUSED,
        )
        state = states[status] if 0 <= status < len(states) else PlaybackState.UNKNOWN
        raw_rate = info.playback_rate
        rate = float(raw_rate) if raw_rate is not None else 1.0
        del raw_rate
        if not math.isfinite(rate):
            rate = 1.0
        controls = info.controls
        caps = (
            Capabilities()
            if controls is None
            else Capabilities(
                can_play=bool(controls.is_play_enabled),
                can_pause=bool(controls.is_pause_enabled),
                can_play_pause=bool(controls.is_play_pause_toggle_enabled),
                can_next=bool(controls.is_next_enabled),
                can_previous=bool(controls.is_previous_enabled),
                can_seek=bool(controls.is_playback_position_enabled),
                can_shuffle=bool(controls.is_shuffle_enabled),
                can_repeat=bool(controls.is_repeat_enabled),
            )
        )
        del controls
        raw_shuffle = info.is_shuffle_active
        shuffle = bool(raw_shuffle) if raw_shuffle is not None else None
        del raw_shuffle
        raw_repeat = info.auto_repeat_mode
        repeat = int(raw_repeat) if raw_repeat is not None else None
        del raw_repeat
        del info
        return Playback(state, rate, caps, shuffle, repeat)

    @staticmethod
    def _timeline(session):
        info = session.get_timeline_properties()
        if info is None:
            return Timeline()

        def seconds(value):
            return float("nan") if value is None else value.total_seconds()

        def timestamp(value):
            return None if value is None else value.timestamp()

        sample = normalize_timeline(
            seconds(info.position),
            seconds(info.start_time),
            seconds(info.end_time),
            seconds(info.min_seek_time),
            seconds(info.max_seek_time),
            timestamp(info.last_updated_time),
        )
        del info
        return sample

    def refresh(self, session_id):
        binding = self._bindings.get(session_id)
        if binding is None or self._closed:
            return
        for kind in ("playback", "timeline"):
            self._read_sample(kind, session_id, binding.session, queued=False)

    async def metadata(self, session_id):
        binding = self._bindings[session_id]
        with self._lock:
            operation = binding.session.try_get_media_properties_async()
        props = await asyncio.wait_for(operation, OPERATION_TIMEOUT)
        if props is None:
            return Metadata()
        with self._lock:
            fields = dict(
                title=props.title or "",
                artist=props.artist or "",
                album=props.album_title or "",
                album_artist=props.album_artist or "",
                subtitle=props.subtitle or "",
                track_number=int(props.track_number),
                album_track_count=int(props.album_track_count),
                genres=tuple(props.genres),
            )
            thumbnail = props.thumbnail
        del props
        art = Artwork()
        art_error = ""
        if thumbnail is not None:
            try:
                art = await asyncio.wait_for(self._artwork(thumbnail), OPERATION_TIMEOUT)
            except Exception as error:
                logger.warning("Unable to read media artwork: %s", error)
                art_error = str(error)
        return Metadata(**fields, artwork=art, artwork_error=art_error)

    @staticmethod
    async def _artwork(reference):
        stream = await reference.open_read_async()
        try:
            size = int(stream.size)
            if not 0 < size <= MAX_ARTWORK_BYTES:
                raise ValueError("Media artwork is empty or exceeds 16 MiB")
            content_type = stream.content_type or ""
            data = bytearray()
            while len(data) < size:
                buffer = Buffer(min(64 * 1024, size - len(data)))
                result = await stream.read_async(buffer, buffer.capacity, InputStreamOptions.NONE)
                chunk = bytes(result)
                if not chunk:
                    raise ValueError("Incomplete media artwork stream")
                data.extend(chunk)
            payload = bytes(data)
            return Artwork(payload, content_type, hashlib.sha256(payload).hexdigest())
        finally:
            stream.close()

    async def invoke(self, session_id, action, value=None):
        methods = {
            "play": ("can_play", "try_play_async"),
            "pause": ("can_pause", "try_pause_async"),
            "play_pause": ("can_play_pause", "try_toggle_play_pause_async"),
            "next": ("can_next", "try_skip_next_async"),
            "previous": ("can_previous", "try_skip_previous_async"),
            "seek": ("can_seek", "try_change_playback_position_async"),
            "shuffle": ("can_shuffle", "try_change_shuffle_active_async"),
            "repeat": ("can_repeat", "try_change_auto_repeat_mode_async"),
        }
        binding = self._bindings.get(session_id)
        if binding is None or self._closed or action not in methods:
            return False
        capability, method = methods[action]
        with self._lock:
            # Recheck the actual Windows capability at dispatch, not only the cached UI flag.
            if not getattr(self._playback(binding.session).capabilities, capability):
                return False
            args = ()
            if action == "seek":
                args = (seek_ticks(value, self._timeline(binding.session)),)
            elif action == "shuffle":
                args = (bool(value),)
            elif action == "repeat":
                args = (MediaPlaybackAutoRepeatMode(value),)
            operation = getattr(binding.session, method)(*args)
        return bool(await asyncio.wait_for(operation, OPERATION_TIMEOUT))

    @staticmethod
    def _unsubscribe(removers):
        for owner, method, token in reversed(removers):
            try:
                getattr(owner, method)(token)
            except Exception:
                logger.debug("Unable to remove media event handler", exc_info=True)
        removers.clear()

    def close(self):
        if self._closed:
            return
        self._closed = True
        with self._lock:
            self._unsubscribe(self._removers)
            for binding in self._bindings.values():
                self._unsubscribe(binding.removers)
            self._bindings.clear()
            self._sample_versions.clear()
            self._manager = None
            self._emit = None
            self._loop = None
            self._reconcile_queued = False
