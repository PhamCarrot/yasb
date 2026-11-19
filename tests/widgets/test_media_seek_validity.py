# pyright: reportPrivateUsage=false

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

import PyQt6.sip as sip
import pytest
from PyQt6.QtCore import QEvent, QPoint, QRect, Qt
from PyQt6.QtGui import QKeyEvent, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QSlider, QWidget

from core.utils.utilities import PopupWidget
from core.widgets.services.media.backend import MediaBackend
from core.widgets.services.media.media import SessionState
from core.widgets.services.media.model import (
    Capabilities,
    MediaState,
    Metadata,
    Playback,
    PlaybackState,
    Player,
    Timeline,
)
from core.widgets.yasb import media, media_lite
from core.widgets.yasb.media_v2_components import InfoButton
from tests.widgets.test_media_backend import Source
from tests.widgets.test_media_popup_geometry import make_popup

# PyQt6 6.10.2 stubs incorrectly describe this non-instantiable C++ namespace
# as instance methods. Keep the compatibility cast local to the test driver.
qt_test = cast(Any, QTest)


class SeekSource(Source):
    def __init__(self) -> None:
        super().__init__()
        self.value = Metadata(title="Same title")
        self.pending: asyncio.Future[Metadata] | None = None

    async def metadata(self, session_id: str) -> Metadata:
        return await self.pending if self.pending is not None else self.value

    def populate(self) -> None:
        super().populate()
        self.emit("playback", "same-id", Playback(PlaybackState.PAUSED, capabilities=Capabilities(can_seek=True)))


def test_pending_and_failed_metadata_disable_seek_without_erasing_presentation() -> None:
    async def run() -> None:
        source = SeekSource()
        backend = MediaBackend(source, autostart=False)
        try:
            await backend.start()
            source.populate()
            await asyncio.sleep(0)
            original = backend.state.active
            assert original is not None and original.is_seekable
            assert await backend.seek(20)
            source.actions.clear()
            source.pending = asyncio.get_running_loop().create_future()
            source.emit("metadata", "same-id", None)
            pending = backend.state.active
            assert pending is not None and pending.metadata == original.metadata
            assert not pending.is_seekable
            assert not await backend.seek(30)
            source.pending.set_exception(RuntimeError("metadata unavailable"))
            await asyncio.sleep(0)
            source.emit("timeline", "same-id", Timeline(position=7, duration=100, known=True))
            source.emit("playback", "same-id", Playback(PlaybackState.PAUSED, capabilities=Capabilities(can_seek=True)))
            failed = backend.state.active
            assert failed is not None and failed.metadata_ready and not failed.artwork_pending
            assert failed.metadata == original.metadata and not failed.is_seekable
            assert not await backend.seek(40)
            assert source.actions == []
        finally:
            await backend.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("replacement", ["progressive", "album", "artwork-error", "readd", "closed", "source"])
def test_seek_tokens_retire_queued_and_captured_gestures(replacement: str) -> None:
    async def run() -> None:
        source = SeekSource()
        if replacement == "album":
            source.value = replace(source.value, album="Original album")
        backend = MediaBackend(source, source_factory=lambda: source, autostart=False, clock=lambda: 0)
        try:
            await backend.start()
            source.populate()
            await asyncio.sleep(0)
            old = backend.state.active
            assert old is not None and old.seek_revision is not None
            queued = backend.seek(12)
            if replacement == "readd":
                source.emit("sessions", None, ())
                source.populate()
            elif replacement == "closed":
                source.emit("playback", "same-id", Playback(PlaybackState.CLOSED))
                source.populate()
            elif replacement == "source":
                backend._retire_source()
                await backend.start()
                source.populate()
            else:
                source.value = replace(
                    old.metadata,
                    track_number=1 if replacement == "progressive" else 0,
                    album="New album" if replacement == "album" else "",
                    artwork_error="thumbnail failed" if replacement == "artwork-error" else "",
                )
                source.emit("metadata", "same-id", None)
            await asyncio.sleep(0)
            assert queued.cancelled() if replacement == "source" else not await queued
            new = backend.state.active
            assert new is not None and new.seek_revision is not None and new.seek_revision != old.seek_revision
            if replacement == "album":
                assert new.duration is None  # Known album A -> B still resets the timeline.
            elif replacement in ("progressive", "artwork-error"):
                assert new.timeline == old.timeline
            assert not await backend.seek(20, expected_revision=old.seek_revision)
            source.emit("timeline", "same-id", Timeline(position=7, duration=100, known=True))
            assert await backend.seek(30, expected_revision=new.seek_revision)
            assert source.actions == [("same-id", "seek", 30)]
        finally:
            await backend.aclose()

    asyncio.run(run())


def test_failed_read_recovery_revalidates_only_new_gestures() -> None:
    async def run() -> None:
        source = SeekSource()
        backend = MediaBackend(source, autostart=False)
        try:
            await backend.start()
            source.populate()
            await asyncio.sleep(0)
            old = backend.state.active
            assert old is not None and old.seek_revision is not None
            source.pending = asyncio.get_running_loop().create_future()
            source.emit("metadata", "same-id", None)
            await asyncio.sleep(0)
            source.pending.set_exception(RuntimeError("read failed"))
            await asyncio.sleep(0)
            source.pending = None
            source.emit("metadata", "same-id", None)
            await asyncio.sleep(0)
            fresh = backend.state.active
            assert fresh is not None and fresh.is_seekable
            assert fresh.metadata == old.metadata and fresh.seek_revision != old.seek_revision
            assert not await backend.seek(60, expected_revision=old.seek_revision)
            assert await backend.seek(40)
            assert source.actions == [("same-id", "seek", 40)]
        finally:
            await backend.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("change", ["pending", "same-text-success", "album", "removed"])
def test_popup_cancels_seek_on_validity_change(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    from core.widgets.services.media.model import MediaSessionState

    active = MediaSessionState(
        Player("owned", "app", "Player"),
        metadata=Metadata(title="Song"),
        playback=Playback(PlaybackState.PAUSED, capabilities=Capabilities(can_seek=True)),
        timeline=Timeline(position=10, duration=100, known=True),
        metadata_ready=True,
        seek_revision=1,
    )
    sent: list[tuple[float, Any]] = []

    def on_seek(seconds: float, identity: Any) -> None:
        sent.append((seconds, identity))

    popup.seek_requested.connect(on_seek)
    try:
        popup.set_state(MediaState((active,), "owned"), QPixmap())
        popup.open_at_parent()
        qt_test.mousePress(popup.progress, Qt.MouseButton.LeftButton, pos=QPoint(50, 7))
        assert popup.progress.interacting
        newer = replace(active, seek_revision=None if change == "pending" else 2)
        if change == "album":
            newer = replace(newer, metadata=replace(active.metadata, album="Other"))
        popup.set_state(MediaState(() if change == "removed" else (newer,), "owned"), QPixmap())
        assert not popup.progress.interacting and popup.progress._pending is None
        qt_test.mouseRelease(popup.progress, Qt.MouseButton.LeftButton, pos=QPoint(90, 7))
        assert sent == []
        popup.set_state(MediaState((replace(active, seek_revision=3),), "owned"), QPixmap())
        qt_test.keyClick(popup.progress, Qt.Key.Key_Right)
        assert len(sent) == 1 and sent[0][1] == ("owned", 3)
    finally:
        popup.hide()
        popup.equalizer.apo.shutdown()
        sip.delete(parent)


@pytest.mark.parametrize("module", [media, media_lite], ids=["full", "lite"])
@pytest.mark.parametrize("change", ["normal", "pending", "recovered", "session", "hidden", "closing", "old-slider"])
def test_legacy_seek_capture_is_synchronous_and_bound_to_origin(qapp: QApplication, module: Any, change: str) -> None:
    from core.widgets.services.media.model import MediaSessionState

    parent = QWidget()
    dialog = PopupWidget(parent, False, False, "normal", "None")
    slider = QSlider(dialog)
    slider.setRange(0, 1000)
    slider.setValue(500)
    dialog.show()
    snapshot = MediaSessionState(
        Player("one", "same.app", "Player"),
        metadata=Metadata(title="Song"),
        playback=Playback(PlaybackState.PAUSED, capabilities=Capabilities(can_seek=True)),
        timeline=Timeline(position=10, duration=100, known=True),
        metadata_ready=True,
        seek_revision=10,
    )
    sent: list[tuple[float, int]] = []

    def submit(seconds: float, *, expected_revision: int) -> None:
        sent.append((seconds, expected_revision))

    owner = SimpleNamespace(
        current_session=SessionState(snapshot, True, None),
        dialog=dialog,
        _progress_slider=slider,
        _seek_identity=None,
        _seeking=False,
        media=SimpleNamespace(seek_to_position=submit),
        _update_interpolated_position=lambda: None,
        _on_media_properties_changed=lambda: None,
        _on_playback_info_changed=lambda: None,
        _popup_open=lambda: False,
    )
    cls = module.MediaWidget
    owner._cancel_seek = lambda: cls._cancel_seek(owner)
    try:
        cls._on_slider_pressed(owner, slider)
        assert owner._seeking
        if change in ("pending", "recovered", "session"):
            newer = replace(snapshot, seek_revision=None if change == "pending" else 11)
            if change == "session":
                newer = replace(newer, player=Player("two", "same.app", "Player"))
            cls._on_media_data_changed(owner, {newer.session_id: SessionState(newer, True, None)})
        elif change == "hidden":
            dialog.hide()
        elif change == "closing":
            dialog._is_closing = True
        elif change == "old-slider":
            newer_slider = QSlider(dialog)
            owner._progress_slider = newer_slider
            cls._on_slider_pressed(owner, newer_slider)
            gesture = owner._seek_identity
            cls._on_slider_pressed(owner, slider)
            assert owner._seek_identity is gesture and owner._seeking
            cls._on_slider_released(owner, slider)
            assert owner._seek_identity is gesture and owner._seeking
            newer_slider.setValue(500)
            cls._on_slider_released(owner, newer_slider)
            assert len(sent) == 1
            return
        cls._on_slider_released(owner, slider)
        assert sent == ([(50, 10)] if change == "normal" else [])
        assert not owner._seeking
    finally:
        sip.delete(parent)


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space])
def test_info_keyboard_activation_once(qapp: QApplication, key: Qt.Key) -> None:
    button = InfoButton()
    modes: list[str] = []
    button.clicked.connect(lambda: modes.append(button.take_activation_mode()))
    try:
        button.show()
        button.setFocus()
        qt_test.keyClick(button, key)
        assert modes == ["keyboard"]
        if key != Qt.Key.Key_Space:
            qapp.sendEvent(button, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, "", True))
            assert modes == ["keyboard"]
        button.setEnabled(False)
        qt_test.keyClick(button, key)
        assert modes == ["keyboard"]
    finally:
        button.close()
        button.deleteLater()
