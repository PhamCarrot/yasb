# pyright: reportPrivateUsage=false

from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, cast

import PyQt6.sip as sip
import pytest
from PyQt6.QtCore import (
    QAbstractAnimation,
    QDeadlineTimer,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPalette, QPixmap, QTextLayout
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
from core.widgets.yasb.media_v2_lyrics_view import CURRENT, LyricsPlayhead, LyricsView
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
        assert view._scroll_motion is not None and view._scroll_motion.duration() == 320
        assert view._line_motion.state().name == "Stopped"
        assert view.line_appearance(25) == (1, 1, 1)
        motion = view._scroll_motion
        motion.setCurrentTime(80)
        view.follow()
        assert view._scroll_motion is motion and motion.currentTime() == 80
        view._scroll_motion.setCurrentTime(320)
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
        target = view.rows.index(4999)
        trailing_spacer = view.rows.index(view.rows.rowCount() - 1)
        deadline = QDeadlineTimer(2000)
        while view.visualRect(trailing_spacer).isEmpty() or view._layout_follow.isActive():
            assert not deadline.hasExpired(), "Batched lyric layout and queued follow did not complete"
            qapp.processEvents()
        assert not view.visualRect(target).isEmpty()
        assert view._scroll_motion is not None
        view._scroll_motion.setCurrentTime(320)
        rect = view.visualRect(target)
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


def record_update(updates: list[object], *args: object) -> None:
    updates.append(args)


def styled_view(
    qapp: QApplication, document: LyricsDocument, width: int = 590, css: str = "", **lyrics: object
) -> LyricsView:
    parent = QWidget()
    view = LyricsView(1, parent, MediaLyricsConfig.model_validate(lyrics))
    if css:
        view.setStyleSheet(f".media-lyrics-view {{ {css} }}")
    view.resize(width, 235)
    view.set_document(document)
    view.accept_input = True
    parent.show()
    view.show()
    qapp.processEvents()
    cast(Any, view).doItemsLayout()  # Public runtime QListView method absent from installed stubs.
    setattr(view, "owned_parent", parent)
    return view


def test_stylesheet_colors_drive_lyrics_and_backgrounds_resize_rows(qapp: QApplication, tmp_path: Path) -> None:
    from core.utils.css_processor import CSSProcessor

    sheet = tmp_path / "styles.css"
    sheet.write_text(
        ".media-lyrics-view { color: #112233; selection-background-color: #ff00aa; -qproperty-afterColor: #00ff00; "
        "-qproperty-currentBackground: #ffffff40; -qproperty-glowColor: #ffffff; }",
        encoding="utf-8",
    )
    processed = CSSProcessor(str(sheet)).process()
    assert "-qproperty-" not in processed
    view = styled_view(qapp, numbered(8), css=processed[processed.index("{") + 1 : processed.rindex("}")])
    try:
        view.set_position(3100, ("session", 1))
        view.finish_line_motion()
        assert (view.inactive_color, view.active_color) == (QColor("#112233"), QColor("#ff00aa"))
        assert view.delegate.state_colors() == (QColor("#112233"), QColor("#ff00aa"), QColor("#00ff00"))
        assert view.glowColor == QColor("#ffffff") and view.side_background(CURRENT) == QColor("#40ffffff")
        assert view._styled_geometry[2] > 0
        view.currentBackground = QColor()
        assert view._styled_geometry[2] == 0 and view.side_background(CURRENT) is None
    finally:
        dispose_view(view)


def numbered(count: int) -> LyricsDocument:
    return parse_lyrics("\n".join(f"[{index * 1000},900]Line {index}" for index in range(count)))


def test_state_styles_apply_per_side_and_keep_existing_precedence(qapp: QApplication) -> None:
    view = styled_view(
        qapp,
        numbered(8),
        inactive_opacity=0.25,
        css="qproperty-beforeColor: #112233; qproperty-currentColor: #ff00aa; qproperty-afterColor: #00ff00;",
        style={
            "before": {"opacity": 0.5},
            "current": {"scale": 1.2},
        },
    )
    try:
        view.set_position(3100, ("session", 1))
        view.finish_line_motion()
        assert view.current_line == 3
        assert [view.line_appearance(row)[1] for row in (0, 2)] == [0.5, 0.5]
        assert [view.line_appearance(row)[1] for row in (4, 7)] == [0.25, 0.25]
        assert view.line_appearance(3) == (1.2, 1.0, 1.0)
        assert view.line_appearance(4)[0] == 0.88 and view.line_appearance(2)[0] == 0.88
        assert view.delegate._line_color(2, 0.0) == QColor("#112233")
        assert view.delegate._line_color(5, 0.0) == QColor("#00ff00")
        assert view.delegate._line_color(3, 1.0) == QColor("#ff00aa")
    finally:
        dispose_view(view)
    flat = styled_view(qapp, numbered(8), style={"after": {"opacity": 0.7, "scale": 0.6}})
    try:
        flat.set_position(3100, ("session", 1))
        flat.finish_line_motion()
        assert [flat.line_appearance(row) for row in (4, 7)] == [(0.6, 0.7, 0.0), (0.6, 0.7, 0.0)]
        assert flat.line_appearance(2) == (0.88, 0.6, 0.0) and flat.line_appearance(1) == (0.8, 0.38, 0.0)
    finally:
        dispose_view(flat)


def test_font_variants_decorations_and_backgrounds_follow_the_state(qapp: QApplication) -> None:
    view = styled_view(
        qapp,
        numbered(6),
        font_weight=400,
        css="qproperty-currentBackground: #ff0000; qproperty-currentColor: #ffffff;",
        style={
            "before": {"italic": True, "strikethrough": True},
            "current": {"bold": True},
            "after": {"bold": False, "underline": True},
        },
    )
    try:
        view.set_position(2100, ("session", 1))
        view.finish_line_motion()
        before, current, after = view.looks
        fonts = [
            view.delegate.layout_for(row, look.variant).font() for row, look in ((1, before), (2, current), (3, after))
        ]
        assert [font.italic() for font in fonts] == [True, False, False]
        assert [font.weight() for font in fonts] == [400, 700, 400]
        assert [
            (part.format.fontStrikeOut(), part.format.fontUnderline()) for part in view.delegate.formats(1, 0, 0)
        ] == [(True, False)]
        assert [part.format.fontUnderline() for part in view.delegate.formats(3, 0, 2)] == [True]
        image = view.grab().toImage()
        red = [
            (x, y)
            for y in range(0, image.height(), 2)
            for x in range(0, image.width(), 2)
            if image.pixelColor(x, y).red() > 200 and image.pixelColor(x, y).green() < 60
        ]
        row = view.visualRect(view.rows.index(3))
        assert red and all(row.top() <= y <= row.bottom() for _, y in red)
    finally:
        dispose_view(view)


def test_rows_keep_their_height_when_a_bold_current_line_wraps_differently(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = "wide words keep wrapping " * 4
    document = parse_lyrics(f"[00:01]intro\n[00:03]{text}\n[00:09]outro")
    view = styled_view(qapp, document, font_family="Segoe UI", font_weight=400, style={"current": {"bold": True}})
    try:
        regular, bold = view.looks[0].variant, view.looks[1].variant
        original = view.delegate.font_for
        sample = "wide words keep wrapping "
        regular_width = QFontMetricsF(original(regular)).horizontalAdvance(sample)
        if QFontMetricsF(original(bold)).horizontalAdvance(sample) == regular_width:
            # Font-less offscreen platforms render bold with regular advances.
            def wider(variant: int) -> QFont:
                font = original(variant)
                if variant == bold:
                    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
                return font

            monkeypatch.setattr(view.delegate, "font_for", wider)
            view.delegate.reset()
        for width in range(220, 590, 7):
            view.resize(width, 235)
            qapp.processEvents()
            if view.delegate.layout_for(1, regular).lineCount() != view.delegate.layout_for(1, bold).lineCount():
                break
        else:
            pytest.fail("No width wraps bold and regular text differently")
        cast(Any, view).doItemsLayout()
        view.set_position(1500, ("session", 1))
        view.finish_line_motion()
        before = view.visualRect(view.rows.index(2)).height()
        view.set_position(3500, ("session", 1))
        view.finish_line_motion()
        qapp.processEvents()
        assert view.current_line == 1
        assert view.visualRect(view.rows.index(2)).height() == before
        tallest = max(view.delegate.layout_for(1, variant).lineCount() for variant in (regular, bold))
        line = view.delegate.layout_for(1, bold).lineAt(0).height()
        assert before >= round(tallest * line)
    finally:
        dispose_view(view)


def test_line_transition_blends_colour_opacity_scale_and_crossfades_variants(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = styled_view(
        qapp,
        numbered(8),
        font_weight=400,
        animation_duration_ms=400,
        css="qproperty-beforeColor: #000000; qproperty-currentColor: #ff0000; qproperty-afterColor: #0000ff;",
        style={"current": {"bold": True}},
    )
    try:
        view.set_position(2100, ("session", 1))
        view.finish_line_motion()
        view.browse()
        view.set_position(3100, ("session", 1))
        view._line_motion.setCurrentTime(200)
        look = view.row_look(3)
        assert (look.source, look.target) == (2, 1) and 0 < look.mix < 1
        assert 0.88 < look.scale < 1 and 0.6 < look.opacity < 1 and 0 < look.tint < 1
        color = view.delegate._line_color(3, look.tint)
        assert 0 < color.red() < 255 and 0 < color.blue() < 255
        outgoing = view.delegate._line_color(2, view.row_look(2).tint)
        assert outgoing.blue() == 0 and 0 < outgoing.red() < 255
        used: list[tuple[int, int]] = []
        original = view.delegate.layout_for

        def spy(row: int, variant: int = 0) -> QTextLayout:
            used.append((row, variant))
            return original(row, variant)

        monkeypatch.setattr(view.delegate, "layout_for", spy)
        view.grab()
        assert {(3, view.looks[2].variant), (3, view.looks[1].variant)} <= set(used)
        view._line_motion.setCurrentTime(400)
        used.clear()
        view.grab()
        assert (3, view.looks[2].variant) not in used
    finally:
        dispose_view(view)


def test_riced_options_stay_bounded_and_add_no_timers(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    view = styled_view(
        qapp,
        numbered(5000),
        css="qproperty-beforeColor: #6c7086; qproperty-currentBackground: #33cba6f7;",
        style={
            "before": {"italic": True, "opacity": 0.55},
            "current": {"bold": True, "scale": 1.1},
            "after": {"bold": False, "underline": True},
        },
        glow={"enabled": True, "radius": 10, "strength": 0.7},
    )
    try:
        assert len(view._styled_geometry[0]) == 3
        for row in range(200):
            view.delegate.row_height(row)
        assert len(view.delegate.layouts) <= 64
        for position in range(0, 12000, 1000):
            view.set_position(position + 100, ("session", 1))
            view.finish_line_motion()
            assert not view.grab().isNull()
        assert 0 < len(view.delegate.glows) <= 3
        deadline = QDeadlineTimer(2000)
        while view._layout_follow.isActive() or (
            view._scroll_motion is not None and view._scroll_motion.state() == QPropertyAnimation.State.Running
        ):
            assert not deadline.hasExpired()
            qapp.processEvents()
        updates: list[object] = []
        with monkeypatch.context() as patch:
            patch.setattr(view.canvas, "update", partial(record_update, updates))
            view.set_position(11300, ("session", 1))
            view.set_position(11500, ("session", 1))
        assert updates == []
        assert not [timer for timer in view.findChildren(QTimer) if timer.isActive()]
        assert all(
            motion.state() != QAbstractAnimation.State.Running for motion in view.findChildren(QAbstractAnimation)
        )
    finally:
        dispose_view(view)


def test_word_timed_position_ticks_repaint_only_the_current_row(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = tuple(
        LyricLine(
            index * 3000,
            index * 3000 + 2900,
            "one two",
            (LyricWord(index * 3000, None, "one "), LyricWord(index * 3000 + 900, None, "two")),
        )
        for index in range(20)
    )
    view = styled_view(qapp, LyricsDocument(lines), glow={"enabled": True, "radius": 6})
    try:
        view.set_position(6100, ("session", 1))
        view.finish_line_motion()
        updates: list[object] = []
        with monkeypatch.context() as patch:
            patch.setattr(view.canvas, "update", partial(record_update, updates))
            view.set_position(6400, ("session", 1))
        row = view.visualRect(view.rows.index(3))
        extent = view.glow_extent()
        assert extent > 0 and updates == [(row.adjusted(-extent, -extent, extent, extent),)]
    finally:
        dispose_view(view)


def test_upgraded_document_replaces_in_place_while_following_and_browsing(qapp: QApplication) -> None:
    timed = parse_lyrics("\n".join(f"[00:{index:02}]Line {index}" for index in range(40)))
    words = LyricsDocument(
        tuple(
            LyricLine(line.start_ms, None, line.text, (LyricWord(line.start_ms, None, line.text),))
            for line in timed.lines
        ),
        source="word-timed",
    )
    owner = Owner(timed)
    parent, panel = make_panel(qapp, owner)
    seeks: list[tuple[float, object]] = []

    def seek(position: float, identity: object) -> None:
        seeks.append((position, identity))

    panel.seek_requested.connect(seek)
    view = panel.view
    try:
        panel.set_state(replace(snapshot(), timeline=Timeline(position=20, duration=100, known=True)))
        cast(Any, view).doItemsLayout()
        deadline = QDeadlineTimer(2000)
        while view._layout_follow.isActive() or (
            view._scroll_motion is not None and view._scroll_motion.state() == QPropertyAnimation.State.Running
        ):
            assert not deadline.hasExpired()
            qapp.processEvents()
        if view._scroll_motion is not None:
            view._scroll_motion.setCurrentTime(view._scroll_motion.duration())
        current, value = view.current_line, view.scroll_bar.value()
        assert current == 20 and value > 0
        owner.current = LyricsState("ready", words)
        owner.changed.emit(next(iter(owner.interests.values())))
        assert view.document is words and view.current_line == current and not view.browsing
        assert view.scroll_bar.value() == value
        assert view._scroll_motion is None or view._scroll_motion.state() != QPropertyAnimation.State.Running
        assert view._line_motion.state() != QVariantAnimation.State.Running
        view.browse()
        view.scroll_bar.setValue(value // 2)
        third = LyricsDocument(words.lines, source="third")
        owner.current = LyricsState("ready", third)
        owner.changed.emit(next(iter(owner.interests.values())))
        assert view.document is third and view.browsing and view._return.isActive()
        assert view.scroll_bar.value() == value // 2
        assert not seeks
    finally:
        sip.delete(parent)


@pytest.mark.parametrize(
    "lines",
    [
        ("雨の日も風の日も歌い続ける", "ｶﾀｶﾅ 한국어 中文歌词"),
        ("😀🎵 emoji line 🎶", "👩\u200d👩\u200d👧 family"),
        ("مرحبا بالعالم", "שלום עולם and English"),
        ("long wrapped words " * 12, "short"),
    ],
)
def test_riced_rows_render_mixed_scripts_with_stable_heights(qapp: QApplication, lines: tuple[str, str]) -> None:
    text = lines[0]
    count = len(text.encode("utf-16-le")) // 2
    words = tuple(LyricWord(1000 + index * 100, None, character) for index, character in enumerate(text))
    document = LyricsDocument(
        (LyricLine(1000, 5000, text, words), LyricLine(6000, 9000, lines[1]), LyricLine(10000, None, "end"))
    )
    view = styled_view(
        qapp,
        document,
        font_weight=400,
        css="qproperty-currentBackground: #40ffffff;",
        style={"current": {"bold": True}, "before": {"italic": True}},
        glow={"enabled": True},
    )
    try:
        view.set_position(500, ("session", 1))
        view.finish_line_motion()
        heights = [view.visualRect(view.rows.index(row + 1)).height() for row in range(3)]
        for position in (1500, 6500, 11000):
            view.set_position(position, ("session", 1))
            view.finish_line_motion()
            assert not view.grab().isNull()
            assert [view.visualRect(view.rows.index(row + 1)).height() for row in range(3)] == heights
        view.set_position(1450, ("session", 1))
        ranges = view.delegate.formats(0, 1.0, 1)
        assert sum(part.length for part in ranges) == count
        assert view.delegate.glows
    finally:
        dispose_view(view)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_playhead_absorbs_small_differences_and_snaps_otherwise() -> None:
    clock = FakeClock()
    head = LyricsPlayhead(clock)
    head.sample(1000, ("session", 1), True, 1.0)
    clock.now += 0.5
    assert head.position() == pytest.approx(1500)
    head.sample(1450, ("session", 1), True, 1.0)
    readings: list[float] = []
    for _ in range(10):
        value = head.position()
        assert value is not None
        readings.append(value)
        clock.now += 0.05
    assert readings[0] == pytest.approx(1500) and readings == sorted(readings)
    clock.now += 2
    assert head.position() == pytest.approx(1450 + 2.5 * 1000, abs=1)
    head.sample(9000, ("session", 1), True, 1.0)
    assert head.position() == pytest.approx(9000)
    head.sample(2000, ("session", 1), True, 1.0)
    assert head.position() == pytest.approx(2000), "a backward seek snaps"
    head.sample(2100, ("session", 2), True, 1.0)
    assert head.position() == pytest.approx(2100), "a new identity snaps"
    head.sample(2200, ("session", 2), False, 1.0)
    clock.now += 3
    assert head.position() == pytest.approx(2200), "paused playheads hold"
    head.sample(1000, ("session", 2), True, 1.25)
    clock.now += 0.4
    assert head.position() == pytest.approx(1500)
    head.sample(None, None, False, 1.0)
    assert head.position() is None


def sweep_view(
    qapp: QApplication, document: LyricsDocument, width: int = 590, css: str = "", **lyrics: object
) -> LyricsView:
    view = styled_view(qapp, document, width, css, word_highlight="sweep", **lyrics)
    view.playhead = LyricsPlayhead(FakeClock())
    return view


def fractions(view: LyricsView, position: int, playing: bool = False) -> list[float]:
    view.set_position(position, ("session", 1), playing=playing)
    segments = view.sweep_segments(view.current_line)
    assert segments is not None
    return [round(fraction, 3) for _, fraction in segments]


def test_word_sweep_fills_each_word_by_its_own_progress(qapp: QApplication) -> None:
    words = (LyricWord(1000, 2000, "alpha "), LyricWord(2000, 3000, "beta "), LyricWord(4000, 4400, "😀"))
    document = LyricsDocument((LyricLine(1000, 5000, "alpha beta 😀", words), LyricLine(6000, None, "next")))
    view = sweep_view(qapp, document)
    try:
        assert fractions(view, 1000) == [0.0, 0.0, 0.0]
        assert fractions(view, 1500) == [0.5, 0.0, 0.0]
        assert fractions(view, 2000) == [1.0, 0.0, 0.0]
        assert fractions(view, 2500) == [1.0, 0.5, 0.0]
        assert fractions(view, 4200) == [1.0, 1.0, 0.5]
        rects = [rect for rect, _ in view.sweep_segments(0) or []]
        assert rects[0].right() <= rects[1].left() + 0.5 and rects[2].width() > 0
        view.set_position(5200, ("session", 1))
        assert view.sweep_segments(0) is None, "past the line end the step colours return"
        assert fractions(view, 1500) == [0.5, 0.0, 0.0], "a backward seek redraws the earlier fill"
    finally:
        dispose_view(view)
    reverse = LyricsDocument(
        (LyricLine(1000, 5000, "first second", (LyricWord(3000, 4000, "first "), LyricWord(1000, 2000, "second"))),)
    )
    view = sweep_view(qapp, reverse)
    try:
        assert fractions(view, 1500) == [0.0, 0.5], "timing order may differ from text order"
    finally:
        dispose_view(view)


def test_sweep_crosses_wrapped_lines_and_right_to_left_fills_whole_words(qapp: QApplication) -> None:
    long_word = "x" * 60
    document = LyricsDocument((LyricLine(1000, 9000, long_word, (LyricWord(1000, 3000, long_word),)),))
    view = sweep_view(qapp, document, width=240)
    try:
        view.set_position(2000, ("session", 1))
        segments = view.sweep_segments(0) or []
        assert len(segments) >= 2, "the word wraps across layout lines"
        total = sum(rect.width() for rect, _ in segments)
        filled = sum(rect.width() * fraction for rect, fraction in segments)
        assert filled == pytest.approx(total / 2, rel=0.02)
        assert segments[0][1] == 1.0 and segments[-1][1] == 0.0
    finally:
        dispose_view(view)
    hebrew = LyricsDocument((LyricLine(1000, 9000, "שלום", (LyricWord(1000, 3000, "שלום"),)),))
    view = sweep_view(qapp, hebrew)
    try:
        assert set(fractions(view, 1900)) == {0.0} and set(fractions(view, 2000)) == {1.0}
    finally:
        dispose_view(view)


def test_line_sweep_is_presentation_only_and_capped(qapp: QApplication) -> None:
    document = parse_lyrics("[00:01.00]plain line\n[00:30.00]later")
    view = styled_view(qapp, document, line_sweep=True, line_sweep_max_ms=2000)
    view.playhead = LyricsPlayhead(FakeClock())
    try:
        assert fractions(view, 2000) == [0.5]
        assert fractions(view, 3500) == [1.0]
        assert view.document is not None and view.document.lines[0].words == ()
    finally:
        dispose_view(view)


def test_sweep_subscribes_only_while_visible_playing_and_on_screen(qapp: QApplication) -> None:
    timed = parse_lyrics("\n".join(f"[{index * 1000},900]Line {index}" for index in range(60)))
    plain = styled_view(qapp, timed)
    try:
        plain.set_position(5100, ("session", 1), playing=True)
        assert not plain._sweep_frames.isActive()
    finally:
        dispose_view(plain)
    view = styled_view(qapp, timed, line_sweep=True)
    try:
        view.set_position(5100, ("session", 1), playing=True)
        assert not view._sweep_frames.isActive(), "the active row is still below the viewport"
        view.follow(instant=True)
        view.finish_line_motion()
        assert view._sweep_frames.isActive()
        view.set_position(5200, ("session", 1), playing=False)
        assert not view._sweep_frames.isActive()
        view.set_position(5300, ("session", 1), playing=True)
        view.accept_input = False
        assert not view._sweep_frames.isActive()
        view.accept_input = True
        assert view._sweep_frames.isActive()
        view.browse()
        view.scroll_bar.setValue(view.scroll_bar.maximum())
        assert not view.visualRect(view.rows.index(6)).intersects(view.canvas.rect())
        assert not view._sweep_frames.isActive()
        view.follow(instant=True)
        assert view._sweep_frames.isActive()
        view.hide()
        assert not view._sweep_frames.isActive()
    finally:
        dispose_view(view)


def test_sweep_frame_shows_an_intermediate_fill(qapp: QApplication) -> None:
    text = "MMMMMMMMMMMMMMMM"
    document = LyricsDocument((LyricLine(1000, 9000, text, (LyricWord(1000, 3000, text),)),))
    view = sweep_view(qapp, document, sweep_softness=0, css="color: #0000ff; qproperty-currentColor: #ff0000;")
    try:
        redness: list[tuple[int, int]] = []
        for position in (1000, 2000, 3000):
            view.set_position(position, ("session", 1))
            view.finish_line_motion()
            image = view.grab().toImage()
            rect = view.visualRect(view.rows.index(1))
            segment = (view.sweep_segments(0) or [(QRectF(), 0.0)])[0][0]
            row_y = rect.center().y()
            counts: list[int] = []
            for low, high in ((0.05, 0.4), (0.6, 0.95)):
                left, right = (
                    round(segment.left() + segment.width() * low) + 4,
                    round(segment.left() + segment.width() * high) + 4,
                )
                counts.append(
                    sum(
                        1
                        for x in range(left, right)
                        for y in range(rect.top(), rect.bottom())
                        if image.pixelColor(x, y).red() > 200 and image.pixelColor(x, y).green() < 80
                    )
                )
            redness.append((counts[0], counts[1]))
            assert row_y > 0
        assert redness[0][0] == 0 and redness[1][0] > 0 and redness[1][1] == 0 and redness[2][1] > 0
    finally:
        dispose_view(view)


def test_glow_halo_covers_the_text_plus_its_spread(qapp: QApplication) -> None:
    from core.widgets.yasb.media_v2_lyrics_view import ink_rect, render_glow

    view = styled_view(qapp, numbered(4), glow={"enabled": True, "radius": 10})
    try:
        layout = view.delegate.layout_for(0, 0)
        for dpr in (1.0, 2.0):
            image, area = render_glow(layout, QColor("#cba6f7"), 10, dpr)
            ink = ink_rect(layout)
            assert not image.isNull() and image.width() < area.width() * dpr
            assert area == ink.adjusted(-15, -15, 15, 15)
    finally:
        dispose_view(view)


def row_color(view: LyricsView, row: int) -> QColor:
    look = view.row_look(row)
    return view.delegate.formats(row, look.tint, look.target)[0].format.foreground().color()


@pytest.mark.parametrize("words", [True, False])
def test_finished_sweep_fades_to_the_before_colour(qapp: QApplication, words: bool) -> None:
    def line(start: int, end: int, text: str) -> LyricLine:
        return LyricLine(start, end, text, (LyricWord(start, end, text),) if words else ())

    document = LyricsDocument((line(1000, 5000, "first"), line(6000, 8000, "second"), line(8000, 9000, "third")))
    css = "color: #0000ff; qproperty-currentColor: #ff0000; qproperty-beforeColor: #00ff00;"
    view = sweep_view(qapp, document, css=css, line_sweep=True, animation_duration_ms=400)
    try:
        view.set_position(4900, ("session", 1))
        view.finish_line_motion()
        assert row_color(view, 0).name() == "#ff0000"
        view.set_position(5200, ("session", 1))
        halfway = row_color(view, 0)
        assert 100 < halfway.red() < 160 and 100 < halfway.green() < 160 and halfway.blue() == 0
        view.set_position(5600, ("session", 1))
        assert row_color(view, 0).name() == "#00ff00"
        view.set_position(6000, ("session", 1))
        assert view.current_line == 1
        assert row_color(view, 0).name() == "#00ff00", "a faded line does not flash back"
        view.set_position(8000, ("session", 1))
        assert view.current_line == 2
        assert row_color(view, 1).name() == "#ff0000", "without a gap the outgoing line fades from the sung colour"
        view.set_position(8200, ("session", 1))
        middle = row_color(view, 1)
        assert 100 < middle.red() < 160 and 100 < middle.green() < 160
        view.set_position(8400, ("session", 1))
        assert row_color(view, 1).name() == "#00ff00"
        view.finish_line_motion()
        assert row_color(view, 1).name() == "#00ff00"
    finally:
        dispose_view(view)
