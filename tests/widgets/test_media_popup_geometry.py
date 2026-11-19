# pyright: reportPrivateUsage=false

import PyQt6.sip as sip
import pytest
from PyQt6.QtCore import QObject, QPoint, QRect, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QWidget

from core.validation.widgets.yasb.media_v2 import MediaV2Config
from core.widgets.services.media.audio_device import AudioOutputState, DefaultAudioOutputService
from core.widgets.services.media.model import (
    Capabilities,
    MediaSessionState,
    MediaState,
    Playback,
    PlaybackState,
    Player,
)
from core.widgets.yasb.media_v2_popup import MediaPopup
from tests.widgets.test_media_v2 import install_capture


class Screen:
    def __init__(self, available: QRect) -> None:
        self.available = available

    def availableGeometry(self) -> QRect:
        return QRect(self.available)

    def geometry(self) -> QRect:
        return self.available.adjusted(0, 0, 0, 40)


class Output(QObject):
    default_output_changed = pyqtSignal(object)
    default_output_refreshed = pyqtSignal(object)
    state = AudioOutputState("owned", "", "Owned output")
    closed = False

    def request_refresh(self, force: bool = False) -> None:
        pass


def make_popup(
    monkeypatch: pytest.MonkeyPatch,
    area: QRect,
    *,
    scale: float = 2,
    artwork_position: str = "left",
    show_equalizer: bool = True,
    use_default_styles: bool = True,
    offset_left: int = 0,
    offset_top: int = 0,
) -> tuple[QWidget, MediaPopup]:
    install_capture(monkeypatch)
    output = Output()
    monkeypatch.setattr(DefaultAudioOutputService, "instance", staticmethod(lambda: output))

    def screen_at(point: QPoint) -> Screen:
        return Screen(area)

    monkeypatch.setattr(QApplication, "screenAt", staticmethod(screen_at))
    parent = QWidget()
    parent.setGeometry(area.left() + 10, area.top() + 20, 300, 30)
    config = MediaV2Config.model_validate(
        {
            "scale": scale,
            "use_default_styles": use_default_styles,
            "popup": {
                "blur": False,
                "background": {"mode": "color"},
                "show_equalizer": show_equalizer,
                "artwork_position": artwork_position,
                "offset_left": offset_left,
                "offset_top": offset_top,
            },
        }
    )
    return parent, MediaPopup(parent, config)


def test_large_popup_is_bounded_to_available_work_area(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    area = QRect(0, 0, 640, 480)
    parent, popup = make_popup(monkeypatch, area)
    try:
        popup.open_at_parent()
        qapp.processEvents()
        assert popup.width() <= area.width()
        assert popup.height() <= area.height()
        assert area.contains(QRect(popup._open_pos, popup.size()))
        assert area.contains(QRect(popup._closed_pos, popup.size()))
        assert popup.art.width() == 448  # Preserve requested content scale.
    finally:
        popup.hide()
        popup.equalizer.apo.shutdown()
        sip.delete(parent)


def test_persistent_popup_rebinds_after_default_output_shutdown(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    def init(service: DefaultAudioOutputService) -> None:
        QObject.__init__(service)
        service._state = AudioOutputState()
        service._closed = False

    parent, popup = make_popup(monkeypatch, QRect(0, 0, 640, 480), show_equalizer=False)
    monkeypatch.setattr(DefaultAudioOutputService, "__init__", init)
    old = DefaultAudioOutputService()
    old._state = AudioOutputState("owned", "", "Owned output")
    old._closed = True
    replacement = DefaultAudioOutputService()
    replacement._state = AudioOutputState("replacement", "", "Replacement output")
    popup._output_service = old
    monkeypatch.setattr(DefaultAudioOutputService, "instance", staticmethod(lambda: replacement))
    try:
        popup.open_at_parent()
        qapp.processEvents()
        assert popup._output_service is replacement
        assert popup.device.text() == "Replacement output"
    finally:
        popup.hide()
        sip.delete(parent)


def test_keyboard_open_and_focus_traversal_keep_controls_in_view(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 320, 420), scale=2)
    session = MediaSessionState(
        Player("owned", "test.app", "Test"),
        playback=Playback(PlaybackState.PAUSED, capabilities=Capabilities(can_play_pause=True)),
        metadata_ready=True,
    )
    popup.set_state(MediaState((session,), "owned", ready=True), QPixmap())
    try:
        popup.open_at_parent(focus_first=True)
        qapp.processEvents()
        viewport = popup._scroll_area.viewport()
        assert viewport is not None
        assert popup.controls.play.hasFocus()
        assert viewport.rect().contains(
            QRect(popup.controls.play.mapTo(viewport, QPoint()), popup.controls.play.size())
        )
        visited = 0
        for _ in range(30):
            popup.focusNextChild()
            qapp.processEvents()
            focused = popup.focusWidget()
            if focused is not None and popup.border.isAncestorOf(focused):
                visited += 1
                rect = QRect(focused.mapTo(viewport, QPoint()), focused.size())
                if rect.width() <= viewport.width() and rect.height() <= viewport.height():
                    assert viewport.rect().contains(rect)
                else:
                    # Preserve scaled controls even when one is wider than the
                    # work area: its centre and the full feasible span must show.
                    assert viewport.rect().contains(rect.center())
                    visible = viewport.rect().intersected(rect)
                    assert visible.width() == min(rect.width(), viewport.width())
                    assert visible.height() == min(rect.height(), viewport.height())
        assert visited >= 10
    finally:
        popup.hide()
        popup.equalizer.apo.shutdown()
        sip.delete(parent)


@pytest.mark.parametrize("position", ["left", "right", "top", "hidden"])
@pytest.mark.parametrize("scale", [0.75, 1, 2])
@pytest.mark.parametrize("equalizer", [False, True])
@pytest.mark.parametrize(
    "area", [QRect(0, 0, 1920, 1040), QRect(0, 0, 1280, 680), QRect(-900, -200, 460, 700), QRect(0, 0, 320, 420)]
)
def test_viewport_preserves_content_and_reaches_last_control(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, position: str, scale: float, equalizer: bool, area: QRect
) -> None:
    parent, popup = make_popup(monkeypatch, area, scale=scale, artwork_position=position, show_equalizer=equalizer)
    try:
        popup.open_at_parent()
        qapp.processEvents()
        assert area.contains(QRect(popup._open_pos, popup.size()))
        assert area.contains(QRect(popup._closed_pos, popup.size()))
        assert popup.art.width() == round(224 * scale)
        assert popup.border.width() == round(625 * scale)
        viewport = popup._scroll_area.viewport()
        assert viewport is not None
        last = popup.equalizer.buttons["Classic"] if equalizer else popup.controls.play
        popup._scroll_area.ensureWidgetVisible(last, 0, 0)
        qapp.processEvents()
        rect = QRect(last.mapTo(viewport, QPoint()), last.size())
        assert viewport.rect().contains(rect)
        if popup.border.width() <= area.width() and popup.border.height() <= area.height():
            assert popup.size() == popup.border.size()
            horizontal = popup._scroll_area.horizontalScrollBar()
            vertical = popup._scroll_area.verticalScrollBar()
            assert horizontal is not None and vertical is not None
            assert horizontal.maximum() == vertical.maximum() == 0
    finally:
        popup.hide()
        if hasattr(popup, "equalizer"):
            popup.equalizer.apo.shutdown()
        sip.delete(parent)


def test_vertical_gutter_avoids_unnecessary_horizontal_scrolling(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    area = QRect(0, 0, 900, 300)
    parent, popup = make_popup(monkeypatch, area, scale=1)
    try:
        popup.open_at_parent()
        qapp.processEvents()
        horizontal = popup._scroll_area.horizontalScrollBar()
        vertical = popup._scroll_area.verticalScrollBar()
        assert horizontal is not None and vertical is not None
        assert vertical.maximum() > 0
        assert horizontal.maximum() == 0
        assert popup.width() > popup.border.width()
        assert popup.height() == area.height()
    finally:
        popup.hide()
        popup.equalizer.apo.shutdown()
        sip.delete(parent)


def test_reopen_recomputes_work_area_and_resize_hook_clamps(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    area = QRect(0, 0, 1600, 1000)
    parent, popup = make_popup(monkeypatch, area, scale=1, offset_left=500, offset_top=500)
    try:
        popup.open_at_parent()
        qapp.processEvents()
        assert area.contains(QRect(popup._open_pos, popup.size()))
        popup.hide()
        area.setRect(-800, -100, 400, 300)
        parent.move(area.topLeft())
        popup.open_at_parent()
        qapp.processEvents()
        assert area.contains(QRect(popup._open_pos, popup.size()))
        assert area.contains(QRect(popup._closed_pos, popup.size()))
        popup.setFixedSize(popup.width() - 10, popup.height() - 10)
        qapp.processEvents()
        assert area.contains(popup.geometry())
    finally:
        popup.hide()
        popup.equalizer.apo.shutdown()
        sip.delete(parent)


def test_missing_screen_falls_back_without_resizing_content(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 800, 600), scale=1)

    def no_screen(point: QPoint) -> None:
        return None

    monkeypatch.setattr(QApplication, "screenAt", staticmethod(no_screen))
    monkeypatch.setattr(parent, "screen", lambda: None)
    try:
        popup.open_at_parent()
        qapp.processEvents()
        assert popup.size() == popup.border.size()
        assert popup._work_area() is None
    finally:
        popup.hide()
        popup.equalizer.apo.shutdown()
        sip.delete(parent)
