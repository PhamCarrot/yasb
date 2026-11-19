# pyright: reportPrivateUsage=false

from dataclasses import replace
from typing import Any, cast

import PyQt6.sip as sip
import pytest
from PyQt6.QtCore import QObject, QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

from core.validation.widgets.yasb.media_v2 import MediaLyricsConfig, MediaLyricsMarginsConfig
from core.widgets.services.media.lyrics import LyricsService, LyricsState
from core.widgets.services.media.lyrics_model import LyricLine, LyricsDocument, LyricWord, parse_lyrics
from core.widgets.services.media.lyrics_provider import LyricsQuery
from core.widgets.services.media.model import (
    Capabilities,
    MediaSessionState,
    MediaState,
    Metadata,
    Playback,
    PlaybackState,
    Player,
    Timeline,
)
from core.widgets.yasb.media_v2_lyrics import MediaLyricsPanel
from core.widgets.yasb.media_v2_lyrics_view import LyricsView
from tests.widgets.test_media_lyrics_owner import run_loop as run_loop
from tests.widgets.test_media_popup_geometry import make_popup

qt_test = cast(Any, QTest)  # Installed namespace stub lacks the runtime test functions.


def test_lyrics_service_recreates_after_direct_shutdown(qapp: QApplication) -> None:
    previous = LyricsService._shared
    service = LyricsService()
    LyricsService._shared = service
    try:
        service.shutdown()
        replacement = LyricsService.shared()
        assert replacement is not service
        assert not replacement.closed
        replacement.shutdown()
    finally:
        LyricsService._shared = previous
        LyricsService._closing = False


def test_lyrics_panel_reacquires_closed_service(qapp: QApplication) -> None:
    previous = LyricsService._shared
    service = LyricsService()
    LyricsService._shared = service
    parent = QWidget()
    panel = MediaLyricsPanel(1, parent, service=service)
    try:
        service.shutdown()
        replacement = panel._owner()
        assert replacement is not service
        assert not replacement.closed
        replacement.shutdown()
    finally:
        sip.delete(parent)
        LyricsService._shared = previous
        LyricsService._closing = False


class Owner(QObject):
    changed = pyqtSignal(object)

    def __init__(self, document: LyricsDocument | None = None) -> None:
        super().__init__()
        self.current = LyricsState("ready", document) if document else LyricsState("loading")
        self.interests: dict[object, LyricsQuery] = {}
        self.watches: list[LyricsQuery] = []
        self.retries: list[LyricsQuery] = []

    def watch(self, token: object, query: LyricsQuery) -> None:
        self.interests[token] = query
        self.watches.append(query)
        self.changed.emit(query)

    def unwatch(self, token: object) -> None:
        self.interests.pop(token, None)

    def state(self, query: LyricsQuery) -> LyricsState:
        return self.current

    def retry(self, query: LyricsQuery) -> None:
        self.retries.append(query)


def snapshot(revision: int | None = 1) -> MediaSessionState:
    return MediaSessionState(
        Player("session", "fixture.app", "Fixture"),
        metadata=Metadata(title="Song", artist="Artist", album="Playlist"),
        playback=Playback(PlaybackState.PAUSED, capabilities=Capabilities(can_seek=True)),
        timeline=Timeline(position=10, duration=100, known=True),
        metadata_ready=True,
        seek_revision=revision,
    )


def make_panel(qapp: QApplication, owner: Owner) -> tuple[QWidget, MediaLyricsPanel]:
    parent = QWidget()
    parent.resize(600, 235)
    panel = MediaLyricsPanel(1, parent, service=cast(LyricsService, owner))
    panel.setGeometry(parent.rect())
    panel.set_state(snapshot())
    parent.show()
    panel.set_active(True)
    qapp.processEvents()
    return parent, panel


def make_view(qapp: QApplication, document: LyricsDocument) -> LyricsView:
    parent = QWidget()
    view = LyricsView(1, parent)
    view.resize(590, 235)
    view.set_document(document)
    view.accept_input = True
    view.set_position(10000, ("session", 1))
    parent.show()
    view.show()
    qapp.processEvents()
    cast(Any, view).doItemsLayout()  # Public runtime QListView method absent from installed stubs.
    # Explicit ownership retained on the Python wrapper for the small fixture.
    setattr(view, "owned_parent", parent)
    return view


def test_lyrics_view_uses_configured_rendering_and_visibility(qapp: QApplication) -> None:
    options = MediaLyricsConfig(
        alignment="center",
        center_position=0.5,
        lines_before=1,
        lines_after=2,
        inactive_opacity=0.25,
        active_color="#ff00aa",
        inactive_color="#112233",
        font_family="Consolas",
        font_size=20,
        font_weight=500,
        margins=MediaLyricsMarginsConfig(horizontal=10, vertical=2, placeholder=12),
        line_height=40,
        line_spacing=8,
        animation_duration_ms=300,
        browse_return_ms=900,
        drag_threshold=7,
    )
    parent = QWidget()
    view = LyricsView(1, parent, options)
    view.resize(590, 235)
    view.set_document(parse_lyrics("\n".join(f"[00:{index:02}]Line {index}" for index in range(6))))
    view.accept_input = True
    parent.show()
    view.show()
    qapp.processEvents()
    view.set_position(2000, ("session", 1))
    qapp.processEvents()
    try:
        assert view.font().family() == "Consolas"
        assert view.font().pixelSize() == 20
        assert view.font().weight() == 500
        assert view._return.interval() == 900
        assert view._line_motion.duration() == 300
        assert view.delegate.layout_for(0).textOption().alignment() == Qt.AlignmentFlag.AlignHCenter
        assert view.line_appearance(0)[1] == 0.0
        assert view.line_appearance(1)[1] == 0.25
        assert view.line_appearance(5)[1] == 0.0
    finally:
        sip.delete(parent)


def dispose_view(view: LyricsView) -> None:
    parent = view.parentWidget()
    assert parent is not None
    sip.delete(parent)


def test_demand_waits_for_visibility_and_selection_and_stops_before_fade(qapp: QApplication) -> None:
    owner = Owner(parse_lyrics("[00:01]one"))
    parent = QWidget()
    panel = MediaLyricsPanel(1, parent, service=cast(LyricsService, owner))
    try:
        panel.set_state(snapshot())
        panel.set_active(True)
        assert not owner.interests
        parent.show()
        qapp.processEvents()
        assert len(owner.interests) == 1 and len(owner.watches) == 1
        panel.set_active(False)
        assert panel.isVisible() and not owner.interests and not panel.view.accept_input
        panel.set_active(True)
        assert len(owner.interests) == 1
        parent.hide()
        assert not owner.interests and not panel.view.accept_input
    finally:
        sip.delete(parent)
    assert not owner.interests


def test_metadata_refresh_invalidates_retained_title_and_late_notifications(qapp: QApplication) -> None:
    owner = Owner(parse_lyrics("[00:01]old"))
    parent, panel = make_panel(qapp, owner)
    try:
        old_query = panel._query
        assert old_query is not None
        panel.set_state(snapshot(None))
        assert not owner.interests and panel._query is None and panel.view.identity is None
        assert panel.view.document is None
        owner.changed.emit(old_query)
        assert panel.view.document is None
        panel.set_state(replace(snapshot(2), metadata=Metadata(title="Other", artist="Singer")))
        assert panel._query is not None and panel._query.title == "other" and panel._query.artist == "singer"
    finally:
        sip.delete(parent)


@pytest.mark.parametrize("status", ["loading", "missing", "error", "plain", "instrumental"])
def test_distinct_truthful_states_and_plain_unicode(qapp: QApplication, status: str) -> None:
    owner = Owner()
    if status == "plain":
        owner.current = LyricsState("ready", parse_lyrics("Plain 😀 text\nNext line"))
    elif status == "instrumental":
        owner.current = LyricsState("ready", LyricsDocument(instrumental=True, source="Fixture"))
    else:
        owner.current = LyricsState(cast(Any, status), detail="Fixture detail")
    parent, panel = make_panel(qapp, owner)
    try:
        if status == "plain":
            assert panel.view.isVisible() and panel.view.rows.texts == ("Plain 😀 text", "Next line")
            assert not panel.view.document.lines if panel.view.document else False
        else:
            assert panel.message.isVisible() and not panel.view.isVisible()
            expected = {
                "loading": "Searching",
                "missing": "No lyrics",
                "error": "Could not",
                "instrumental": "Instrumental",
            }
            assert expected[status] in panel.message.text()
        panel.retry()
        assert owner.retries
    finally:
        sip.delete(parent)


def test_mouse_and_keyboard_seek_capture_revision_document_and_drag(qapp: QApplication) -> None:
    document = parse_lyrics("[00:01]one\n[00:10]two\n[00:20]three")
    view = make_view(qapp, document)
    seeks: list[tuple[float, object]] = []

    def on_seek(seconds: float, identity: object) -> None:
        seeks.append((seconds, identity))

    view.seek_requested.connect(on_seek)
    try:
        point = view.visualRect(view.rows.index(2)).center()
        qt_test.mousePress(view.canvas, Qt.MouseButton.LeftButton, pos=point)
        view.set_position(10000, ("session", 2))
        qt_test.mouseRelease(view.canvas, Qt.MouseButton.LeftButton, pos=point)
        assert not seeks
        qt_test.mouseClick(view.canvas, Qt.MouseButton.LeftButton, pos=point)
        assert seeks == [(10.0, ("session", 2))]
        seeks.clear()
        qt_test.mousePress(view.canvas, Qt.MouseButton.LeftButton, pos=point)
        qt_test.mouseMove(view.canvas, point + QPoint(0, 20))
        qt_test.mouseRelease(view.canvas, Qt.MouseButton.LeftButton, pos=point + QPoint(0, 20))
        assert not seeks and view.browsing
        view.setCurrentIndex(view.rows.index(2))
        qt_test.keyPress(view, Qt.Key.Key_Return)
        view.set_document(parse_lyrics("[00:10]replacement"))
        qt_test.keyRelease(view, Qt.Key.Key_Return)
        assert not seeks
        view.setCurrentIndex(view.rows.index(1))
        qt_test.keyClick(view, Qt.Key.Key_Enter)
        assert seeks == [(10.0, ("session", 2))]
        seeks.clear()
        qt_test.keyPress(view, Qt.Key.Key_Return)
        view.cancel_interaction()
        view.accept_input = False
        qt_test.keyRelease(view, Qt.Key.Key_Return)
        assert not seeks
    finally:
        dispose_view(view)


def test_follow_browse_timeout_and_right_click(qapp: QApplication) -> None:
    document = parse_lyrics("\n".join(f"[00:{index:02}]Line {index}" for index in range(50)))
    view = make_view(qapp, document)
    try:
        assert view._return.interval() == 4000
        view.set_position(25000, ("session", 1))
        assert view._scroll_motion is not None and view._scroll_motion.duration() == 650
        view._scroll_motion.setCurrentTime(650)
        rect = view.visualRect(view.rows.index(26))
        assert abs(rect.center().y() - view.canvas.height() * 0.44) <= 2
        view.browse()
        assert view.browsing and view._return.isActive()
        view.set_position(30000, ("session", 1))
        assert view.browsing
        view._return.setInterval(20)
        view._return.start()
        qt_test.qWait(40)
        assert not view.browsing
        view.browse()
        qt_test.mouseClick(view.canvas, Qt.MouseButton.RightButton, pos=QPoint(20, 30))
        assert not view.browsing and not view._return.isActive()
    finally:
        dispose_view(view)


def test_keyboard_capture_is_cancelled_when_release_goes_to_another_control(qapp: QApplication) -> None:
    view = make_view(qapp, parse_lyrics("[00:01]one\n[00:10]two"))
    parent = view.parentWidget()
    assert parent is not None
    button = QPushButton("Other control", parent)
    button.move(0, 250)
    button.show()
    seeks: list[float] = []

    def on_seek(seconds: float, identity: object) -> None:
        seeks.append(seconds)

    view.seek_requested.connect(on_seek)
    try:
        view.setCurrentIndex(view.rows.index(2))
        view.setFocus()
        qapp.processEvents()
        qt_test.keyPress(view, Qt.Key.Key_Return)
        assert view._gesture_start is not None
        button.setFocus()
        qapp.processEvents()
        qt_test.keyRelease(button, Qt.Key.Key_Return)
        assert not seeks and view._gesture_start is None and view._pressed is None
        view.follow()
        assert not view._return.isActive()
    finally:
        dispose_view(view)


def test_word_ranges_use_utf16_and_individual_intervals(qapp: QApplication) -> None:
    document = LyricsDocument(
        lines=(
            LyricLine(
                1000,
                5000,
                "😀 a",
                (
                    LyricWord(2000, None, "😀"),
                    LyricWord(1000, 1800, " "),
                    LyricWord(2500, 3000, "a"),
                ),
            ),
            LyricLine(6000, None, "next"),
        )
    )
    view = make_view(qapp, document)
    try:
        palette = view.palette()
        palette.setColor(QPalette.ColorRole.Text, QColor("#cdd6f4"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#cba6f7"))
        view.setPalette(palette)
        view.set_position(1600, ("session", 1))
        ranges = view.delegate.formats(0)
        assert [(part.start, part.length) for part in ranges] == [(0, 2), (2, 1), (3, 1)]
        assert ranges[1].format.foreground().color() == QColor("#cba6f7")
        assert ranges[0].format.foreground().color().alphaF() == pytest.approx(0.4, abs=0.01)
        view.set_position(7000, ("session", 1))
        assert all(part.format.foreground().color() == QColor("#cdd6f4") for part in view.delegate.formats(0))
        assert all(part.format.foreground().color() == QColor("#cdd6f4") for part in view.delegate.formats(0, tint=1))
    finally:
        dispose_view(view)


def test_timed_row_motion_preserves_layout_and_visible_fade_on_long_seeks(qapp: QApplication) -> None:
    view = make_view(qapp, parse_lyrics("\n".join(f"[{index * 1000},900]Row {index}" for index in range(48))))
    try:
        view.set_position(100, ("session", 1))
        view._line_motion.setCurrentTime(650)
        assert view.line_appearance(0) == (1, 1, 1)
        assert view.line_appearance(1) == (0.88, 0.6, 0)
        assert view.line_appearance(2) == (0.8, 0.38, 0)
        assert view.line_appearance(9) == (0.8, 0.2, 0)
        view.browse()
        before = view.visualRect(view.rows.index(1))
        assert before.intersects(view.canvas.rect())
        view.set_position(20100, ("session", 1))
        view._line_motion.setCurrentTime(160)
        style = view.line_appearance(0)
        assert 0.8 < style[0] < 1 and 0.2 < style[1] < 1 and 0 < style[2] < 1
        assert view.visualRect(view.rows.index(1)) == before
        view.set_position(40100, ("session", 1))
        assert view.browsing and view.line_appearance(0) == style
        view._line_motion.setCurrentTime(650)
        assert view.line_appearance(0) == (0.8, 0.2, 0)
        view.set_position(41100, ("session", 1))
        view.hide()
        assert view._line_motion.state().name == "Stopped"
        assert not view._return.isActive() and not view._layout_follow.isActive()
    finally:
        dispose_view(view)


def test_layout_cache_tracks_viewport_gutter_and_font_changes(qapp: QApplication) -> None:
    view = make_view(qapp, parse_lyrics("[00:01]" + "Wrapped lyric words " * 12))
    try:
        view.delegate.layout_for(0)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        qapp.processEvents()
        layout = view.delegate.layout_for(0)
        assert layout.lineAt(0).width() == max(1, view.canvas.width() - 8)
        font = view.font()
        font.setPixelSize(24)
        view.setFont(font)
        qapp.processEvents()
        assert view.delegate.layout_for(0).font().pixelSize() == 24
    finally:
        dispose_view(view)


def test_large_document_retains_bounded_layouts_and_native_children(qapp: QApplication) -> None:
    document = parse_lyrics("\n".join(f"[{index * 1000},900]Line {index}" for index in range(5000)))
    view = make_view(qapp, document)
    try:
        assert view.rows.rowCount() == 5002
        for row in range(100):
            view.delegate.layout_for(row)
        assert len(view.delegate.layouts) == 64 and len(view.delegate.heights) <= 5000
        assert len(view.findChildren(QWidget)) < 30
        assert not view.grab().isNull()
        view.set_position(4998000, ("session", 1))
        # Batched Qt layout deliberately spans event-loop turns. Wait for the
        # target's geometry, then check the exact650ms follow result.
        for _ in range(100):
            if not view.visualRect(view.rows.index(4999)).isEmpty():
                break
            qt_test.qWait(20)
        assert not view.visualRect(view.rows.index(4999)).isEmpty()
        assert view._scroll_motion is not None
        view._scroll_motion.setCurrentTime(650)
        rect = view.visualRect(view.rows.index(4999))
        assert abs(rect.center().y() - view.canvas.height() * 0.44) <= 2
    finally:
        dispose_view(view)


def test_popup_timeline_updates_lyrics_without_replacing_common_objects(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = Owner(parse_lyrics("[00:01]one\n[00:10]two"))

    def shared(cls: type[LyricsService]) -> LyricsService:
        return cast(LyricsService, owner)

    monkeypatch.setattr(LyricsService, "shared", classmethod(shared))
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        active = snapshot()
        state = MediaState((active,), active.session_id)
        popup.set_state(state, QPixmap())
        popup.open_at_parent()
        common = (popup.art, popup.title, popup.controls, popup.progress)
        popup.sections.tabs.setCurrentIndex(2)
        popup.sections.finish()
        qapp.processEvents()
        assert popup.sections.tabs.count() == 3 and owner.interests
        assert popup.sections.lyrics.view.current_line == 1
        updated = replace(active, timeline=replace(active.timeline, position=2))
        popup.set_state(replace(state, sessions=(updated,)), QPixmap())
        assert popup.sections.lyrics.view.current_line == 0
        assert common == (popup.art, popup.title, popup.controls, popup.progress)
        view = popup.sections.lyrics.view
        qt_test.mouseClick(view.canvas, Qt.MouseButton.LeftButton, pos=view.visualRect(view.rows.index(1)).center())
        assert qapp.focusWidget() is view, (
            type(qapp.focusWidget()).__name__,
            view.focusPolicy(),
            view.focusProxy(),
            view.canvas.focusPolicy(),
            popup.sections._policies[2].get(view),
        )
        popup.sections.tabs.setCurrentIndex(1)
        assert not owner.interests
        popup.hide()
        assert not popup.sections.lyrics.view._return.isActive()
    finally:
        popup.hide()
        popup.equalizer.apo.shutdown()
        sip.delete(parent)
