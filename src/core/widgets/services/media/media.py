"""Compatibility boundary for existing YASB widgets; new consumers use MediaBackend.

This adapter owns no Windows session, timer, selection policy or media logic.
The mutable SessionState shape and Pillow decoding exist only for old consumers.
"""

from __future__ import annotations

import asyncio
import io
import logging
import threading
from typing import Any

import PyQt6.sip as sip
from PIL import Image
from PyQt6.QtCore import QObject, pyqtSignal
from winrt.windows.media.control import GlobalSystemMediaTransportControlsSession

from core.utils.qobject import is_valid_qobject
from core.widgets.services.media.backend import MediaBackend
from core.widgets.services.media.model import MediaSessionState, MediaState, PlaybackState

# Retain the legacy import used in widget annotations.
type MediaSession = GlobalSystemMediaTransportControlsSession

logger = logging.getLogger("WindowsMedia")


class SessionState:
    def __init__(self, snapshot: MediaSessionState, is_current: bool, thumbnail: Image.Image | None) -> None:
        self.session_id = snapshot.session_id
        self.app_id = snapshot.player.app_id
        self.title = snapshot.title
        self.artist = snapshot.artist
        self.album = snapshot.album
        self.current_pos = snapshot.position
        self.duration = snapshot.duration or 0.0
        self.last_snapshot_pos = snapshot.position
        self.last_update_time = snapshot.timeline.updated_at or 0.0
        self.is_playing = snapshot.is_playing
        self.is_current = is_current
        self.playback_rate = snapshot.playback.rate
        self.playback_status = {
            PlaybackState.CLOSED: 0,
            PlaybackState.OPENED: 1,
            PlaybackState.CHANGING: 2,
            PlaybackState.STOPPED: 3,
            PlaybackState.PLAYING: 4,
            PlaybackState.PAUSED: 5,
        }.get(snapshot.playback.state, 0)
        self.playback_ready = snapshot.playback.state != PlaybackState.UNKNOWN
        caps = snapshot.capabilities
        self.controls_prev_enabled = caps.can_previous
        self.controls_play_enabled = caps.can_play_pause
        self.controls_next_enabled = caps.can_next
        self.timeline_enabled = caps.can_seek
        self.seek_revision = snapshot.seek_revision
        self.is_seekable = snapshot.is_seekable
        self.controls_shuffle_enabled = caps.can_shuffle
        self.controls_repeat_enabled = caps.can_repeat
        self.is_shuffle_active = snapshot.playback.shuffle or False
        self.auto_repeat_mode = snapshot.playback.repeat or 0
        self.thumbnail = thumbnail


class QSingleton(type(QObject)):
    """Singleton metaclass for Qt classes"""

    _instances: dict[Any, Any] = {}
    _lock = threading.Lock()

    def __call__(cls, *args: Any, **kwargs: Any):
        with cls._lock:
            if cls not in cls._instances or sip.isdeleted(cls._instances[cls]):
                cls._instances[cls] = super().__call__(*args, **kwargs)
            return cls._instances[cls]


class WindowsMedia(QObject, metaclass=QSingleton):
    media_data_changed = pyqtSignal(dict)
    current_session_changed = pyqtSignal()
    media_properties_changed = pyqtSignal()
    timeline_info_changed = pyqtSignal()
    playback_info_changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.backend = MediaBackend.shared()
        self._trackers: dict[str, SessionState] = {}
        self._art: dict[str, tuple[str, Image.Image | None]] = {}
        self._last_state: MediaState | None = None
        self.backend.state_changed.connect(self._on_state)
        # Defer initial publication until the constructing widget connects its slots.
        asyncio.get_running_loop().call_soon(self.force_update)

    def _disconnect_backend(self, backend: MediaBackend) -> None:
        if not is_valid_qobject(backend):
            return
        try:
            backend.state_changed.disconnect(self._on_state)
        except RuntimeError, TypeError:
            pass

    def _ensure_backend(self, *, publish: bool = False) -> MediaBackend:
        backend = self.backend
        if is_valid_qobject(backend) and not backend.closed:
            return backend
        shared = MediaBackend.shared_instance()
        if shared is None or shared is backend:
            return backend
        self._disconnect_backend(backend)
        backend = MediaBackend.shared()
        self.backend = backend
        backend.state_changed.connect(self._on_state)
        self._last_state = None
        if publish:
            self._on_state(backend.state, force=True)
        return backend

    @property
    def current_session(self) -> SessionState | None:
        backend = self._ensure_backend(publish=True)
        return self._trackers.get(backend.state.active_session_id or "")

    def _on_state(self, state: MediaState, force: bool = False):
        old = self._last_state
        self._last_state = state
        live = {s.session_id for s in state.sessions}
        self._art = {sid: cached for sid, cached in self._art.items() if sid in live}
        trackers: dict[str, SessionState] = {}
        for snapshot in state.sessions:
            art = snapshot.artwork
            cached = self._art.get(snapshot.session_id)
            if cached is None or cached[0] != art.content_hash:
                image = None
                if art.data:
                    try:
                        with Image.open(io.BytesIO(art.data)) as source:
                            image = source.copy()
                    except Exception:
                        logger.warning("Unable to decode media thumbnail", exc_info=True)
                cached = (art.content_hash, image)
                self._art[snapshot.session_id] = cached
            trackers[snapshot.session_id] = SessionState(
                snapshot, snapshot.session_id == state.active_session_id, cached[1]
            )
        self._trackers = trackers
        self.media_data_changed.emit(dict(trackers))
        active = state.active
        previous = old.active if old else None
        changed = old is None or state.active_session_id != old.active_session_id
        if force or changed or (active.metadata if active else None) != (previous.metadata if previous else None):
            self.media_properties_changed.emit()
        if force or changed or (active.playback if active else None) != (previous.playback if previous else None):
            self.playback_info_changed.emit()
        if force or changed or (active.timeline if active else None) != (previous.timeline if previous else None):
            self.timeline_info_changed.emit()
        if force or changed:
            self.current_session_changed.emit()

    def force_update(self):
        backend = self._ensure_backend()
        self._on_state(backend.state, force=True)

    def switch_current_session(self, direction: int):
        return self._ensure_backend().switch_session(direction)

    def play_pause(self):
        return self._ensure_backend().play_pause()

    def prev(self):
        return self._ensure_backend().previous()

    def next(self):
        return self._ensure_backend().next()

    def toggle_shuffle(self):
        backend = self._ensure_backend()
        active = backend.state.active
        return backend.set_shuffle(not active.playback.shuffle if active else False)

    def cycle_repeat(self):
        backend = self._ensure_backend()
        active = backend.state.active
        current = active.playback.repeat if active else 0
        return backend.set_repeat(0 if current is None else {0: 2, 2: 1, 1: 0}.get(current, 0))

    def seek_to_position(self, position: float, *, expected_revision: int | None = None):
        return self._ensure_backend().seek(position, expected_revision=expected_revision)

    def _on_quit(self):
        backend = self.backend
        if is_valid_qobject(backend):
            backend.close()
