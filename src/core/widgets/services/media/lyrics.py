"""Application-owned, demand-bound lyric requests and immutable documents.

One actual reply or parse job at a time. Views own only interest tokens and
captured media identities; they never own network managers or overwrite intent.
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import ClassVar, Literal, cast

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import QApplication

from core.utils.qobject import is_valid_qobject
from core.widgets.services.media.lyrics_model import MAX_BYTES, LyricsDocument
from core.widgets.services.media.lyrics_provider import (
    LyricsQuery,
    LyricsRequest,
    Provider,
    Stage,
    interpret_response,
)
from settings import BUILD_VERSION


@dataclass(frozen=True)
class LyricsState:
    status: Literal["idle", "loading", "ready", "missing", "error"] = "idle"
    document: LyricsDocument | None = None
    detail: str = ""


@dataclass(frozen=True)
class _Job:
    request: LyricsRequest
    generation: int
    attempt: int = 0
    ready_at: float = 0
    # "search" looks for a word-timed replacement after publishing a result;
    # "resumed" continues an interrupted search once and records no resume point.
    upgrade: Literal["", "search", "resumed"] = ""


@dataclass(frozen=True)
class _Cached:
    state: LyricsState
    expires: float
    weight: int
    resume: LyricsRequest | None = None


def retry_delay(value: bytes, now: datetime | None = None) -> float:
    text = value.decode("ascii", errors="replace").strip()
    try:
        delay = float(text)
        if delay < 0 or not math.isfinite(delay):
            raise ValueError("Invalid retry interval")
        return delay
    except ValueError:
        try:
            date = parsedate_to_datetime(text)
            if date.tzinfo is None:
                date = date.replace(tzinfo=UTC)
            return max(0.0, (date - (now or datetime.now(UTC))).total_seconds())
        except ValueError, TypeError, OverflowError:
            return 2.0


class LyricsService(QObject):
    changed = pyqtSignal(object)
    _shared: ClassVar[LyricsService | None] = None
    _closing: ClassVar[bool] = False
    _drain_task: ClassVar[asyncio.Task[None] | None] = None
    MAX_INTERESTS = 64
    MAX_CACHE = 32
    MAX_CACHE_BYTES = 16 * 1024 * 1024

    @classmethod
    def shared(cls) -> LyricsService:
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
    async def _drain_shared(cls, service: LyricsService) -> None:
        if service._reply is not None:
            if service._reply_drained is None:
                service._reply_drained = asyncio.get_running_loop().create_future()
            await asyncio.shield(service._reply_drained)
        task = service._parse_task
        if task is not None:
            await asyncio.shield(task)
        if cls._shared is service:
            cls._shared = None
        if cls._drain_task is asyncio.current_task():
            cls._drain_task = None
        cls._closing = False

    def __init__(
        self,
        *,
        manager: QNetworkAccessManager | None = None,
        spacing_ms: int = 250,
        timeout_ms: int = 10000,
        providers: tuple[Provider, ...] = ("lrclib", "netease", "better_lyrics"),
        credentials: dict[str, str] | None = None,
        prefer_word_timed: bool = False,
    ) -> None:
        super().__init__(QApplication.instance())
        self._manager = manager or QNetworkAccessManager(self)
        self._spacing = max(200, spacing_ms) / 1000
        self._providers = self._normalize_providers(providers)
        self._credentials = dict(credentials or {})
        self._prefer_word_timed = prefer_word_timed
        self._interests: dict[object, LyricsQuery] = {}
        self._generations: dict[LyricsQuery, int] = {}
        self._states: dict[LyricsQuery, LyricsState] = {}
        self._cache: OrderedDict[LyricsQuery, _Cached] = OrderedDict()
        self._cache_bytes = 0
        self._counter = 0
        self._queue: OrderedDict[LyricsQuery, _Job] = OrderedDict()
        self._reply: QNetworkReply | None = None
        self._reply_drained: asyncio.Future[None] | None = None
        self._job: _Job | None = None
        self._buffer = bytearray()
        self._reply_failure = ""
        self._parse_task: asyncio.Task[None] | None = None
        self._last_finished = float("-inf")
        self._blocked_until: dict[str, float] = {}
        self._closed = False
        self._wake = QTimer(self)
        self._wake.setSingleShot(True)
        self._wake.timeout.connect(self._pump)
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.setInterval(max(1000, timeout_ms))
        self._timeout.timeout.connect(self._timed_out)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    @property
    def closed(self) -> bool:
        return self._closed

    @staticmethod
    def _normalize_providers(providers: tuple[Provider, ...] | list[Provider]) -> tuple[Provider, ...]:
        normalized = tuple(
            provider for provider in providers if provider in ("lrclib", "netease", "better_lyrics", "musixmatch")
        )
        if not normalized or len(set(normalized)) != len(normalized):
            return ("lrclib", "netease", "better_lyrics")
        return cast(tuple[Provider, ...], normalized)

    def configure(
        self,
        *,
        providers: tuple[Provider, ...] | list[Provider],
        spacing_ms: int,
        timeout_ms: int,
        credentials: dict[str, str] | None = None,
        prefer_word_timed: bool = False,
    ) -> None:
        """Apply lookup options before a new demand is watched."""
        if self._reply is not None or (self._parse_task is not None and not self._parse_task.done()):
            return
        self._providers = self._normalize_providers(providers)
        self._spacing = max(200, spacing_ms) / 1000
        self._timeout.setInterval(max(1000, timeout_ms))
        self._credentials = dict(credentials or {})
        self._prefer_word_timed = prefer_word_timed

    def _request_for(self, query: LyricsQuery) -> LyricsRequest:
        provider = self._providers[0]
        stage = cast(
            Stage,
            {
                "lrclib": "lrclib-search",
                "netease": "netease-cloud",
                "better_lyrics": "better-lyrics",
                "musixmatch": "musixmatch-search",
            }[provider],
        )
        credentials = tuple((name, value) for name, value in self._credentials.items() if value)
        return LyricsRequest(
            query,
            stage=stage,
            providers=self._providers,
            credentials=cast(tuple[tuple[Provider, str], ...], credentials),
        )

    def state(self, query: LyricsQuery) -> LyricsState:
        key = query.normalized()
        return self._states.get(key, self._cached(key) or LyricsState())

    def _cached(self, query: LyricsQuery) -> LyricsState | None:
        entry = self._cached_entry(query)
        return entry.state if entry is not None else None

    def _cached_entry(self, query: LyricsQuery) -> _Cached | None:
        cached = self._cache.get(query)
        if cached is None:
            return None
        if cached.expires <= time.monotonic():
            self._cache_bytes -= self._cache.pop(query).weight
            return None
        self._cache.move_to_end(query)
        return cached

    def _remember(self, query: LyricsQuery, request: LyricsRequest | None) -> None:
        cached = self._cache.get(query)
        if cached is not None and cached.resume != request:
            self._cache[query] = replace(cached, resume=request)

    def watch(self, token: object, query: LyricsQuery) -> None:
        if self._closed:
            return
        query = query.normalized()
        if self._interests.get(token) == query:
            return
        self.unwatch(token)
        if len(self._interests) >= self.MAX_INTERESTS:
            raise ValueError("Too many lyric views")
        self._interests[token] = query
        if query not in self._generations:
            self._counter += 1
            self._generations[query] = self._counter
            cached = self._cached_entry(query)
            self._states[query] = cached.state if cached is not None else self._initial_state(query)
            if cached is None and query.artist:
                self._queue[query] = _Job(self._request_for(query), self._counter)
            elif cached is not None and cached.resume is not None and query.artist and self._prefer_word_timed:
                # The last view left during a word-timed search; finish it once.
                self._queue[query] = _Job(cached.resume, self._counter, upgrade="resumed")
                self._remember(query, None)
        self.changed.emit(query)
        self._pump()

    def unwatch(self, token: object) -> None:
        query = self._interests.pop(token, None)
        if query is None or query in self._interests.values():
            return
        self._generations.pop(query, None)
        self._states.pop(query, None)
        self._queue.pop(query, None)
        if self._job is not None and self._job.request.query == query and self._reply is not None:
            # Keep the reply slot until finished acknowledges abort. A late A
            # completion cannot publish after a later A has acquired a new tag.
            self._reply.abort()
        if not self._interests:
            self._wake.stop()
            self._timeout.stop()
        self._pump()

    def retry(self, query: LyricsQuery) -> None:
        query = query.normalized()
        if query not in self._generations or self._closed:
            return
        self._counter += 1
        self._generations[query] = self._counter
        self._states[query] = self._initial_state(query)
        if query.artist:
            self._queue[query] = _Job(self._request_for(query), self._counter)
        if self._job is not None and self._job.request.query == query and self._reply is not None:
            self._reply.abort()
        self.changed.emit(query)
        self._pump()

    @staticmethod
    def _initial_state(query: LyricsQuery) -> LyricsState:
        if not query.artist:
            return LyricsState("missing", detail="Artist metadata is unavailable")
        return LyricsState("loading")

    def _wanted(self, job: _Job) -> bool:
        return not self._closed and self._generations.get(job.request.query) == job.generation

    def _pump(self) -> None:
        if self._closed or self._reply is not None or (self._parse_task is not None and not self._parse_task.done()):
            return
        now = time.monotonic()
        selected: _Job | None = None
        earliest = float("inf")
        for query, job in tuple(self._queue.items()):
            if not self._wanted(job):
                self._queue.pop(query)
                continue
            ready = max(
                job.ready_at, self._last_finished + self._spacing, self._blocked_until.get(job.request.provider, 0)
            )
            if ready <= now:
                selected = self._queue.pop(query)
                break
            earliest = min(earliest, ready)
        if selected is None:
            if earliest < float("inf"):
                self._wake.start(max(1, min(60000, round((earliest - now) * 1000))))
            return
        self._start(selected)

    def _start(self, job: _Job) -> None:
        self._wake.stop()
        request = QNetworkRequest(QUrl(job.request.url))
        request.setRawHeader(
            b"User-Agent", f"YASB-MediaV2 v{BUILD_VERSION} (https://github.com/PhamCarrot/yasb)".encode("ascii")
        )
        request.setRawHeader(b"Accept", b"application/json")
        if job.request.provider == "netease":
            request.setRawHeader(b"Referer", b"https://music.163.com")
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.SameOriginRedirectPolicy
        )
        request.setTransferTimeout(8000)
        self._job = job
        self._buffer.clear()
        self._reply_failure = ""
        reply = self._manager.get(request)
        if reply is None:
            self._job = None
            self._last_finished = time.monotonic()
            self._publish(job, LyricsState("error", detail="Could not start lyric request"))
            self._pump()
            return
        self._reply = reply
        reply.setReadBufferSize(MAX_BYTES + 1)
        reply.readyRead.connect(lambda: self._read(reply))
        reply.finished.connect(lambda: self._finished(reply, job))
        self._timeout.start()

    def _read(self, reply: QNetworkReply) -> None:
        if reply is not self._reply:
            return
        remaining = MAX_BYTES + 1 - len(self._buffer)
        if remaining > 0:
            chunk = reply.read(remaining)
            # PyQt6 returns None after an aborted QIODevice despite its bytes
            # stub. Never let a transport error escape a Qt signal callback.
            if chunk:
                self._buffer.extend(chunk)
        if len(self._buffer) > MAX_BYTES:
            self._reply_failure = "Lyric response exceeds one MiB"
            if not reply.isFinished():
                reply.abort()

    def _timed_out(self) -> None:
        if self._reply is not None:
            self._reply_failure = "Lyric request timed out"
            self._reply.abort()

    def _finished(self, reply: QNetworkReply, job: _Job) -> None:
        if reply is not self._reply:
            reply.deleteLater()
            return
        self._timeout.stop()
        self._read(reply)
        self._reply = None
        self._job = None
        if self._reply_drained is not None:
            if not self._reply_drained.done():
                self._reply_drained.set_result(None)
            self._reply_drained = None
        self._last_finished = time.monotonic()
        data = bytes(self._buffer)
        self._buffer.clear()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        status = status if isinstance(status, int) else 0
        content_type = reply.rawHeader(b"Content-Type").data().decode("ascii", errors="replace").lower()
        media_type = content_type.split(";", 1)[0].strip()
        retry = reply.rawHeader(b"Retry-After").data()
        error = self._reply_failure or (
            reply.errorString() if reply.error() != QNetworkReply.NetworkError.NoError else ""
        )
        reply.deleteLater()
        if not self._wanted(job):
            self._pump()
            return
        if status in (429, 503):
            delay = retry_delay(retry)
            ready = time.monotonic() + delay + random.uniform(0, delay * 0.3)
            self._blocked_until[job.request.provider] = ready
            if job.attempt < 2 and math.isfinite(delay) and delay <= 60:
                self._queue[job.request.query] = replace(job, attempt=job.attempt + 1, ready_at=ready)
            else:
                self._publish(job, LyricsState("error", detail="Provider is rate limited; try later"))
        elif (
            status == 200
            and not error
            and (
                media_type == "application/json"
                or media_type.startswith("application/")
                and media_type.endswith("+json")
                or job.request.provider == "netease"
                and media_type == "text/plain"
            )
        ):
            try:
                self._parse_task = asyncio.get_running_loop().create_task(self._parse(job, data))
            except RuntimeError:
                self._publish(job, LyricsState("error", detail="Lyric parsing needs the application event loop"))
        else:
            fallback = job.request.fallback()
            if fallback is not None:
                self._enqueue(job, fallback)
            else:
                self._publish(job, LyricsState("error", detail=error or f"Lyric provider returned HTTP{status}"))
        self._pump()

    async def _parse(self, job: _Job, data: bytes) -> None:
        try:
            result = await asyncio.to_thread(interpret_response, job.request, data)
            if not self._wanted(job):
                return
            if result.document is not None:
                self._found(job, result.document)
            elif result.next_request is not None:
                self._enqueue(job, result.next_request)
            else:
                self._publish(job, LyricsState("missing", detail=result.detail))
        except (ValueError, OSError) as error:
            if self._wanted(job):
                fallback = job.request.fallback()
                if fallback is not None:
                    self._enqueue(job, fallback)
                else:
                    self._publish(job, LyricsState("error", detail=str(error)))
        finally:
            self._parse_task = None
            self._pump()

    def _enqueue(self, job: _Job, request: LyricsRequest) -> None:
        self._queue[request.query] = replace(job, request=request, attempt=0, ready_at=0)
        if job.upgrade == "search":
            self._remember(request.query, request)

    def _found(self, job: _Job, document: LyricsDocument) -> None:
        if job.upgrade:
            # Only a word-timed document may replace the published one.
            following = None if document.word_synced else job.request.fallback()
            if following is not None:
                self._enqueue(job, following)
            else:
                self._publish(job, LyricsState("ready", document))
            return
        if not (document.lines or document.plain or document.instrumental):
            self._publish(job, LyricsState("missing", detail="The file contains no lyrics"))
            return
        following = (
            job.request.fallback()
            if self._prefer_word_timed and not document.word_synced and not document.instrumental
            else None
        )
        self._publish(job, LyricsState("ready", document), resume=following)
        if following is not None:
            self._queue[job.request.query] = _Job(following, job.generation, upgrade="search")

    def _publish(self, job: _Job, state: LyricsState, *, resume: LyricsRequest | None = None) -> None:
        if not self._wanted(job):
            return
        query = job.request.query
        if job.upgrade and not (state.status == "ready" and state.document is not None and state.document.word_synced):
            # A miss, error or plain result ends the search; the published result stays.
            self._remember(query, None)
            return
        self._states[query] = state
        old = self._cache.pop(query, None)
        if old is not None:
            self._cache_bytes -= old.weight
        weight = (
            (state.document.retained_bytes if state.document is not None else 0)
            + len(query.title.encode())
            + len(query.artist.encode())
            + len(query.album.encode())
            + len(state.detail.encode())
            + 256
        )
        if weight <= self.MAX_CACHE_BYTES:
            while self._cache and (
                len(self._cache) >= self.MAX_CACHE or self._cache_bytes + weight > self.MAX_CACHE_BYTES
            ):
                _, removed = self._cache.popitem(last=False)
                self._cache_bytes -= removed.weight
            ttl = 1800 if state.status == "ready" else 30
            self._cache[query] = _Cached(state, time.monotonic() + ttl, weight, resume)
            self._cache_bytes += weight
        self.changed.emit(query)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._wake.stop()
        self._timeout.stop()
        self._interests.clear()
        self._generations.clear()
        self._states.clear()
        self._queue.clear()
        if self._reply is not None:
            self._reply.abort()
        # An executing parser keeps the slot until it actually returns. Its
        # invalidated generation can no longer publish; aclose_shared drains it.
