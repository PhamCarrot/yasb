# pyright: reportPrivateUsage=false

import asyncio
import json
import sys
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
import qasync  # pyright: ignore[reportMissingTypeStubs]
from PyQt6.QtCore import QIODevice, QUrl
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import QApplication

from core.widgets.services.media import lyrics
from core.widgets.services.media.lyrics import LyricsService, retry_delay
from core.widgets.services.media.lyrics_model import MAX_BYTES
from core.widgets.services.media.lyrics_provider import LyricsQuery


@dataclass
class Response:
    status: int = 200
    body: bytes | None = None
    content_type: str = "application/json"
    headers: dict[str, str] = field(default_factory=dict[str, str])
    gate: threading.Event | None = None


class LocalProvider:
    """Real HTTP transport, synthetic metadata, and no external network access."""

    def __init__(self) -> None:
        self.responses: deque[Response] = deque()
        self.requests: list[tuple[str, float]] = []
        self.gates: list[threading.Event] = []
        self.errors: list[BaseException] = []
        owner = self

        class Server(ThreadingHTTPServer):
            def handle_error(self, request: Any, client_address: Any) -> None:
                error = sys.exception()
                if isinstance(error, (ConnectionResetError, BrokenPipeError)):
                    return  # Expected when the Qt reply aborts before headers.
                if error is not None:
                    owner.errors.append(error)
                super().handle_error(request, client_address)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                owner.requests.append((self.path, time.monotonic()))
                response = owner.responses.popleft() if owner.responses else Response()
                if response.gate is not None:
                    owner.gates.append(response.gate)
                    response.gate.wait(5)
                query = parse_qs(urlsplit(self.path).query)
                title = query.get("track_name", ["song"])[0]
                body = response.body
                if body is None:
                    body = json.dumps(
                        [{"trackName": title, "artistName": "artist", "syncedLyrics": "[00:01]" + title}]
                    ).encode()
                try:
                    self.send_response(response.status)
                    self.send_header("Content-Type", response.content_type)
                    self.send_header("Content-Length", str(len(body)))
                    for name, value in response.headers.items():
                        self.send_header(name, value)
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    pass  # The demand owner deliberately aborted this connection.

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.server = Server(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        for response in self.responses:
            if response.gate is not None:
                response.gate.set()
        for gate in self.gates:
            gate.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        assert not self.thread.is_alive()
        assert not self.errors


class RoutingManager(QNetworkAccessManager):
    def __init__(self, server: LocalProvider) -> None:
        super().__init__()
        self.server = server
        self.originals: list[QNetworkRequest] = []
        self.active = 0
        self.peak = 0

    def createRequest(
        self, op: QNetworkAccessManager.Operation, request: QNetworkRequest, device: QIODevice | None = None
    ) -> QNetworkReply:
        self.originals.append(QNetworkRequest(request))
        routed = QNetworkRequest(request)
        url = QUrl(request.url())
        url.setScheme("http")
        url.setHost("127.0.0.1")
        url.setPort(self.server.server.server_port)
        routed.setUrl(url)
        reply = super().createRequest(op, routed, device)
        assert reply is not None
        self.active += 1
        self.peak = max(self.peak, self.active)
        reply.finished.connect(self._retire)
        return reply

    def _retire(self) -> None:
        self.active -= 1


class DeferredAbortReply(QNetworkReply):
    """An abort request need not synchronously acknowledge finished."""

    def __init__(self, request: QNetworkRequest, parent: QNetworkAccessManager) -> None:
        super().__init__(parent)
        self.aborted = False
        self.setRequest(request)
        self.setUrl(request.url())
        self.open(QIODevice.OpenModeFlag.ReadOnly)

    def abort(self) -> None:
        self.aborted = True

    def acknowledge(self) -> None:
        self.setError(QNetworkReply.NetworkError.OperationCanceledError, "Owned test abort")
        self.setFinished(True)
        self.finished.emit()

    def readData(self, maxlen: int) -> bytes:
        return b""


class DeferredAbortManager(QNetworkAccessManager):
    reply: DeferredAbortReply | None = None

    def createRequest(
        self, op: QNetworkAccessManager.Operation, request: QNetworkRequest, device: QIODevice | None = None
    ) -> QNetworkReply:
        self.reply = DeferredAbortReply(request, self)
        return self.reply


@pytest.fixture
def provider() -> Iterator[LocalProvider]:
    server = LocalProvider()
    try:
        yield server
    finally:
        server.close()


@pytest.fixture
def run_loop(qapp: QApplication) -> Iterator[Callable[[Awaitable[None]], None]]:
    loop = cast(Any, qasync.QEventLoop(qapp))
    with loop:
        yield loop.run_until_complete


async def until(predicate: Callable[[], bool], timeout: float = 4) -> None:
    end = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < end, "Timed out waiting for lyric owner state"
        await asyncio.sleep(0.005)


async def close(service: LyricsService) -> None:
    service.shutdown()
    if service._parse_task is not None:
        await asyncio.shield(service._parse_task)
    await asyncio.sleep(0)


def test_two_views_share_actual_request_and_last_leave_aborts(
    provider: LocalProvider, run_loop: Callable[[Awaitable[None]], None]
) -> None:
    async def run() -> None:
        gate = threading.Event()
        provider.responses.append(Response(gate=gate))
        manager = RoutingManager(provider)
        service = LyricsService(manager=manager)
        query = LyricsQuery("song", "artist")
        try:
            service.watch("one", query)
            service.watch("two", query)
            await until(lambda: len(provider.requests) == 1)
            assert manager.active == manager.peak == 1
            service.unwatch("one")
            assert manager.active == 1 and service._reply is not None
            service.unwatch("two")
            await until(lambda: manager.active == 0)
            gate.set()
            await asyncio.sleep(0.3)
            assert service.state(query).status == "idle"
            assert not service._queue and not service._wake.isActive() and not service._timeout.isActive()
            assert len(provider.requests) == 1
        finally:
            gate.set()
            await close(service)

    run_loop(run())


def test_a_b_a_and_late_old_reply_cannot_publish(
    provider: LocalProvider, run_loop: Callable[[Awaitable[None]], None]
) -> None:
    async def run() -> None:
        gate = threading.Event()
        provider.responses.append(Response(gate=gate))
        manager = RoutingManager(provider)
        service = LyricsService(manager=manager)
        query = LyricsQuery("song", "artist")
        try:
            service.watch("view", query)
            await until(lambda: len(provider.requests) == 1)
            old_generation = service._generations[query]
            service.watch("view", LyricsQuery("other", "artist"))
            service.watch("view", query)
            assert service._generations[query] != old_generation
            gate.set()
            await until(lambda: service.state(query).status == "ready")
            document = service.state(query).document
            assert document is not None and document.lines[0].text == "song"
            assert len(manager.originals) == 2 and manager.peak == 1
        finally:
            gate.set()
            await close(service)

    run_loop(run())


def test_rate_limit_spacing_headers_and_last_demand_stops_retry(
    provider: LocalProvider, run_loop: Callable[[Awaitable[None]], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        def no_jitter(low: float, high: float) -> float:
            return 0

        monkeypatch.setattr(lyrics.random, "uniform", no_jitter)
        provider.responses.append(Response(status=429, headers={"Retry-After": "0.3"}))
        manager = RoutingManager(provider)
        service = LyricsService(manager=manager, spacing_ms=200)
        query = LyricsQuery("song", "artist")
        try:
            service.watch("view", query)
            await until(lambda: service.state(query).status == "ready")
            assert len(provider.requests) == 2 and manager.peak == 1
            assert provider.requests[1][1] - provider.requests[0][1] >= 0.29
            original = manager.originals[0]
            assert original.url().host() == "lrclib.net"
            assert b"YASB-MediaV2 v" in original.rawHeader(b"User-Agent").data()
            assert original.attribute(QNetworkRequest.Attribute.RedirectPolicyAttribute) == (
                QNetworkRequest.RedirectPolicy.SameOriginRedirectPolicy
            )
            provider.responses.append(Response(status=503, headers={"Retry-After": "0.3"}))
            service.retry(query)
            await until(lambda: len(provider.requests) == 3 and service._reply is None)
            service.unwatch("view")
            await asyncio.sleep(0.4)
            assert len(provider.requests) == 3 and not service._wake.isActive()
        finally:
            await close(service)

    run_loop(run())


@pytest.mark.parametrize("failure", ["html", "json-prefix", "oversize", "timeout"])
def test_transport_failures_are_bounded_and_fallback_stays_sequential(
    provider: LocalProvider, run_loop: Callable[[Awaitable[None]], None], failure: str
) -> None:
    async def run() -> None:
        gate = threading.Event()
        first = {
            "html": Response(body=b"<html>bad</html>", content_type="text/html"),
            "json-prefix": Response(body=b"[]", content_type="application/jsonp"),
            "oversize": Response(body=b"x" * (MAX_BYTES + 2)),
            "timeout": Response(gate=gate),
        }[failure]
        provider.responses.extend([first, Response(body=b"{}"), Response(body=b'{"result":{"songs":[]}}')])
        manager = RoutingManager(provider)
        service = LyricsService(manager=manager, spacing_ms=200, providers=("lrclib", "netease"))
        service._timeout.setInterval(80)
        query = LyricsQuery("song", "artist")
        try:
            service.watch("view", query)
            await until(lambda: service.state(query).status == "missing")
            assert len(manager.originals) == 3 and manager.peak == 1
            assert [request.url().host() for request in manager.originals] == [
                "lrclib.net",
                "music.163.com",
                "music.163.com",
            ]
            assert service._reply is None and service._parse_task is None and len(service._buffer) == 0
        finally:
            gate.set()
            await close(service)

    run_loop(run())


def test_shared_shutdown_waits_for_reply_acknowledgement_even_if_waiter_cancels(
    run_loop: Callable[[Awaitable[None]], None],
) -> None:
    async def run() -> None:
        manager = DeferredAbortManager()
        service = LyricsService(manager=manager)
        LyricsService._shared = service
        service.watch("view", LyricsQuery("song", "artist"))
        reply = manager.reply
        assert reply is not None
        try:
            drain = asyncio.create_task(LyricsService.aclose_shared())
            await asyncio.sleep(0)
            assert reply.aborted and not drain.done() and service._reply is reply
            assert LyricsService.shared() is service
            drain.cancel()
            with pytest.raises(asyncio.CancelledError):
                await drain
            assert LyricsService.shared() is service
            drain = asyncio.create_task(LyricsService.aclose_shared())
            await asyncio.sleep(0)
            assert not drain.done()
            reply.acknowledge()
            await drain
            assert service._reply is None and LyricsService._shared is None
        finally:
            await close(service)
            LyricsService._shared = None

    run_loop(run())


@pytest.mark.parametrize(
    ("value", "expected"),
    [(b"3", 3), (b"-1", 2), (b"nan", 2), (b"bad", 2), (b"inf", 2), (b"Tue, 17 Nov 2026 00:00:05 GMT", 5)],
)
def test_retry_after_numeric_date_and_invalid(value: bytes, expected: float) -> None:
    assert retry_delay(value, datetime(2026, 11, 17, tzinfo=UTC)) == expected
