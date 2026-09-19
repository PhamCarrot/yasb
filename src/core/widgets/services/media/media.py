"""Compatibility boundary for existing YASB widgets; new consumers use MediaBackend.

This adapter owns no Windows session, timer, selection policy or media logic.
The mutable SessionState shape and Pillow decoding exist only for old consumers.
"""

import asyncio
import io
import logging

from PIL import Image
from PyQt6.QtCore import QObject, pyqtSignal
from winrt.windows.media.control import GlobalSystemMediaTransportControlsSession

from core.utils.singleton import QSingleton
from core.widgets.services.media.backend import MediaBackend
from core.widgets.services.media.model import PlaybackState

# Retain the legacy import used in widget annotations.
type MediaSession = GlobalSystemMediaTransportControlsSession

logger = logging.getLogger("WindowsMedia")


class SessionState:
    def __init__(self, snapshot, is_current, thumbnail):
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
        self.controls_shuffle_enabled = caps.can_shuffle
        self.controls_repeat_enabled = caps.can_repeat
        self.is_shuffle_active = snapshot.playback.shuffle or False
        self.auto_repeat_mode = snapshot.playback.repeat or 0
        self.thumbnail = thumbnail


class WindowsMedia(QObject, metaclass=QSingleton):
    media_data_changed = pyqtSignal(dict)
    current_session_changed = pyqtSignal()
    media_properties_changed = pyqtSignal()
    timeline_info_changed = pyqtSignal()
    playback_info_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.backend = MediaBackend.shared()
        self._trackers = {}
        self._art = {}
        self._last_state = None
        self.backend.state_changed.connect(self._on_state)
        # Defer initial publication until the constructing widget connects its slots.
        asyncio.get_running_loop().call_soon(self.force_update)

    @property
    def current_session(self):
        return self._trackers.get(self.backend.state.active_session_id)

    def _on_state(self, state, force=False):
        old = self._last_state
        self._last_state = state
        live = {s.session_id for s in state.sessions}
        self._art = {sid: cached for sid, cached in self._art.items() if sid in live}
        trackers = {}
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
        self._on_state(self.backend.state, force=True)

    def switch_current_session(self, direction):
        return self.backend.switch_session(direction)

    def play_pause(self):
        return self.backend.play_pause()

    def prev(self):
        return self.backend.previous()

    def next(self):
        return self.backend.next()

    def toggle_shuffle(self):
        active = self.backend.state.active
        return self.backend.set_shuffle(not active.playback.shuffle if active else False)

    def cycle_repeat(self):
        active = self.backend.state.active
        current = active.playback.repeat if active else 0
        return self.backend.set_repeat({0: 2, 2: 1, 1: 0}.get(current, 0))

    async def seek_to_position(self, position):
        return await self.backend.seek(position)

    def _on_quit(self):
        self.backend.close()
