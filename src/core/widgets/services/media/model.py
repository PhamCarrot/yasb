"""UI-independent media snapshots. Public timeline values are seconds from track start."""

import math
from dataclasses import dataclass, field
from enum import StrEnum

MAX_TIMELINE_DURATION = 7 * 24 * 60 * 60


class PlaybackState(StrEnum):
    UNKNOWN = "unknown"
    CLOSED = "closed"
    OPENED = "opened"
    CHANGING = "changing"
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


@dataclass(frozen=True)
class Capabilities:
    can_play: bool = False
    can_pause: bool = False
    can_play_pause: bool = False
    can_next: bool = False
    can_previous: bool = False
    can_seek: bool = False
    can_shuffle: bool = False
    can_repeat: bool = False

    @property
    def can_control(self) -> bool:
        return any(
            (
                self.can_play,
                self.can_pause,
                self.can_play_pause,
                self.can_next,
                self.can_previous,
                self.can_seek,
                self.can_shuffle,
                self.can_repeat,
            )
        )


@dataclass(frozen=True)
class Player:
    # Opaque, lifetime-scoped session identity, NOT an application id.
    session_id: str
    app_id: str
    application_name: str


@dataclass(frozen=True)
class Artwork:
    data: bytes = b""
    content_type: str = ""
    content_hash: str = ""


@dataclass(frozen=True)
class Metadata:
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    subtitle: str = ""
    track_number: int = 0
    album_track_count: int = 0
    genres: tuple[str, ...] = ()
    artwork: Artwork = field(default_factory=Artwork)
    artwork_error: str = ""


@dataclass(frozen=True)
class Playback:
    state: PlaybackState = PlaybackState.UNKNOWN
    rate: float = 1.0
    capabilities: Capabilities = field(default_factory=Capabilities)
    shuffle: bool | None = None
    repeat: int | None = None  # GSMTC: 0=none, 1=track, 2=list; None=unknown


@dataclass(frozen=True)
class Timeline:
    position: float = 0.0
    duration: float | None = None
    start: float = 0.0
    seek_min: float | None = None
    seek_max: float | None = None
    updated_at: float | None = None  # Windows wall-clock sample timestamp, not a UI clock
    known: bool = False


def normalize_timeline(position, start, end, minimum, maximum, updated_at) -> Timeline:
    """Normalize GSMTC's absolute timeline and explicitly represent unknown bounds."""
    values = (position, start, end, minimum, maximum)
    if not all(math.isfinite(value) for value in values):
        return Timeline()
    start = max(0.0, start)
    span = end - start
    duration = span if 0 < span <= MAX_TIMELINE_DURATION else None
    position = max(0.0, position - start)
    if duration is not None:
        position = min(position, duration)
    seek_span = maximum - minimum
    has_range = maximum > minimum and maximum >= start and seek_span <= MAX_TIMELINE_DURATION
    lower = max(0.0, minimum - start) if has_range else None
    upper = max(0.0, maximum - start) if has_range else None
    stamp = updated_at if updated_at is not None and math.isfinite(updated_at) and updated_at > 0 else None
    known = stamp is not None or position > 0 or duration is not None or has_range
    return Timeline(position, duration, start, lower, upper, stamp, known)


def seek_ticks(position: float, timeline: Timeline) -> int:
    """Clamp a track-relative seek and convert to Windows absolute 100 ns ticks."""
    if not math.isfinite(position):
        raise ValueError("Seek position must be finite")
    lower = timeline.seek_min if timeline.seek_min is not None else 0.0
    upper = timeline.seek_max if timeline.seek_max is not None else timeline.duration
    if timeline.duration is not None:
        upper = min(upper, timeline.duration) if upper is not None else timeline.duration
    if upper is not None and lower > upper:
        raise ValueError("Invalid Windows seek range")
    position = max(lower, position)
    if upper is not None:
        position = min(upper, position)
    absolute = timeline.start + position
    if not math.isfinite(absolute) or absolute > (2**63 - 1) / 10_000_000:
        raise ValueError("Seek position exceeds Windows TimeSpan range")
    ticks = round(absolute * 10_000_000)
    if not 0 <= ticks <= 2**63 - 1:
        raise ValueError("Seek position exceeds Windows TimeSpan range")
    return ticks


@dataclass(frozen=True)
class MediaSessionState:
    player: Player
    metadata: Metadata = field(default_factory=Metadata)
    playback: Playback = field(default_factory=Playback)
    timeline: Timeline = field(default_factory=Timeline)
    metadata_ready: bool = False
    artwork_pending: bool = False

    @property
    def session_id(self) -> str:
        return self.player.session_id

    @property
    def title(self) -> str:
        return self.metadata.title

    @property
    def artist(self) -> str:
        return self.metadata.artist

    @property
    def album(self) -> str:
        return self.metadata.album

    @property
    def artwork(self) -> Artwork:
        return self.metadata.artwork

    @property
    def capabilities(self) -> Capabilities:
        return self.playback.capabilities

    @property
    def is_playing(self) -> bool:
        return self.playback.state == PlaybackState.PLAYING

    @property
    def is_paused(self) -> bool:
        return self.playback.state == PlaybackState.PAUSED

    @property
    def is_stopped(self) -> bool:
        return self.playback.state == PlaybackState.STOPPED

    @property
    def position(self) -> float:
        return self.timeline.position

    @property
    def duration(self) -> float | None:
        return self.timeline.duration

    @property
    def progress(self) -> float | None:
        if (
            self.duration is None
            or self.duration <= 0
            or self.duration > MAX_TIMELINE_DURATION
            or not self.timeline.known
        ):
            return None
        return min(1.0, max(0.0, self.position / self.duration))

    @property
    def is_seekable(self) -> bool:
        return self.capabilities.can_seek and self.progress is not None


@dataclass(frozen=True)
class MediaState:
    sessions: tuple[MediaSessionState, ...] = ()
    active_session_id: str | None = None
    manual_session_id: str | None = None
    ready: bool = False
    error: str = ""

    @property
    def active(self) -> MediaSessionState | None:
        return next((s for s in self.sessions if s.session_id == self.active_session_id), None)

    @property
    def usable_sessions(self) -> tuple[MediaSessionState, ...]:
        return tuple(s for s in self.sessions if s.playback.state != PlaybackState.CLOSED)


def select_active(
    sessions: tuple[MediaSessionState, ...],
    manual_id: str | None,
    preferred_id: str | None = None,
) -> str | None:
    """Selection policy: manual, playing, previous automatic, controllable, first."""
    usable = tuple(s for s in sessions if s.playback.state != PlaybackState.CLOSED)
    if any(s.session_id == manual_id for s in usable):
        return manual_id
    playing = next((s for s in usable if s.is_playing), None)
    if playing:
        return playing.session_id
    if any(s.session_id == preferred_id for s in usable):
        return preferred_id
    controllable = next((s for s in usable if s.capabilities.can_control), None)
    return (controllable or (usable[0] if usable else None)).session_id if (controllable or usable) else None
