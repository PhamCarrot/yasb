# pyright: reportPrivateUsage=false

from dataclasses import replace
from typing import Any, cast

import PyQt6.sip as sip
import pytest
from PyQt6.QtCore import QElapsedTimer, QRect, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from core.widgets.services.media.model import MediaSessionState, MediaState, Metadata, Playback, PlaybackState, Player
from tests.widgets.test_media_popup_geometry import make_popup

# PyQt6 6.10.2 stubs incorrectly describe this non-instantiable C++ namespace
# as instance methods. Keep the compatibility cast local to the test driver.
qt_test = cast(Any, QTest)


@pytest.mark.parametrize("change", ["playback", "reorder", "removed", "rename"])
def test_open_player_menu_retains_highlight_by_session(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    first, second = (
        MediaSessionState(Player(sid, "same.app", "Player"), metadata=Metadata(title=title))
        for sid, title in (("one", "One"), ("two", "Two"))
    )
    selected: list[str | None] = []
    popup.session_selected.connect(selected.append)
    try:
        popup.set_state(MediaState((first, second), "one"), QPixmap())
        popup.open_at_parent()
        popup._open_session_menu()
        menu = popup.selector.popup_menu
        highlighted = next(a for a in menu.actions() if a.data() == "two")
        menu.setActiveAction(highlighted)
        if change == "playback":
            sessions = (replace(first, playback=Playback(PlaybackState.PLAYING)), second)
        elif change == "reorder":
            sessions = (second, first)
        elif change == "rename":
            sessions = (first, replace(second, metadata=Metadata(title="Renamed")))
        else:
            sessions = (first,)
        popup.set_state(MediaState(sessions, "one"), QPixmap())
        active = menu.activeAction()
        if change == "removed":
            assert active is None or active.data() != "two"
            assert all(a.data() != "two" for a in menu.actions())
        else:
            assert active is not None and active.data() == "two"
            if change == "playback":
                assert active is highlighted
            qt_test.keyClick(menu, Qt.Key.Key_Return)
            assert selected == ["two"]
    finally:
        popup.hide()
        popup.equalizer.apo.shutdown()
        sip.delete(parent)


@pytest.mark.parametrize("animated", [False, True])
def test_popup_close_retires_owned_menu(qapp: QApplication, monkeypatch: pytest.MonkeyPatch, animated: bool) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    session = MediaSessionState(Player("owned", "app", "Player"))
    try:
        other = MediaSessionState(Player("other", "second.app", "Second player"))
        popup.set_state(MediaState((session, other), "owned"), QPixmap())
        popup.open_at_parent()
        popup._open_session_menu()
        assert popup.selector.popup_menu.isVisible() and popup.selector.menu_active
        if animated:
            popup.hide_animated(restore_focus=True)
        else:
            popup.hide()
        assert not popup.selector.popup_menu.isVisible() and not popup.selector.menu_active
        if animated:
            assert popup._fade_animation.duration() == 500
            deadline = QElapsedTimer()
            deadline.start()
            while popup.isVisible() and deadline.elapsed() < 2000:
                qt_test.qWait(10)
        assert not popup.isVisible()
    finally:
        popup.hide()
        popup.equalizer.apo.shutdown()
        sip.delete(parent)


def test_nested_escape_and_interrupted_close_reopen(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    session = MediaSessionState(Player("owned", "app", "Player"))
    try:
        other = MediaSessionState(Player("other", "second.app", "Second player"))
        popup.set_state(MediaState((session, other), "owned"), QPixmap())
        popup.open_at_parent(focus_first=True)
        popup._open_session_menu()
        qt_test.keyClick(popup.selector.popup_menu, Qt.Key.Key_Escape)
        assert popup.isVisible() and not popup.selector.menu_active
        popup.hide_animated()
        qt_test.qWait(30)
        popup.open_at_parent(focus_first=True)
        qt_test.qWait(850)
        assert popup.isVisible() and not popup._is_closing
        assert popup.windowOpacity() > 0.99
        assert popup._seek_identity is None
    finally:
        popup.hide()
        popup.equalizer.apo.shutdown()
        sip.delete(parent)
