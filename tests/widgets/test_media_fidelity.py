# pyright: reportPrivateUsage=false

from dataclasses import replace
from typing import Any, cast

import PyQt6.sip as sip
import pytest
from PyQt6.QtCore import QPoint, QPropertyAnimation, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFrame, QWidget

from core.validation.widgets.yasb.media_v2 import MediaDiscConfig
from core.widgets.services.media.model import MediaSessionState, MediaState, Playback, PlaybackState, Player
from core.widgets.yasb.media_v2_disc import DiscArt
from core.widgets.yasb.media_v2_motion import MediaText
from tests.widgets.test_media_popup_geometry import make_popup
from tests.widgets.test_media_v2 import install_capture


def test_marquee_reuses_shaping_and_releases_it_on_hide(qapp: QApplication) -> None:
    title = MediaText("media-v2-title", scrollable=True)
    title.resize(90, 38)
    title.setText("A long rolling song title")
    title.show()
    try:
        title.textMix = 1.0
        assert not title.grab().isNull()
        initial = title._marquee_layout
        assert initial is not None
        title.scrollOffset = 35.5
        assert not title.grab().isNull()
        assert title._marquee_layout is initial

        font = title.font()
        font.setPixelSize(21)
        title.setFont(font)
        assert not title.grab().isNull()
        assert title._marquee_layout is not None and title._marquee_layout is not initial
        title.hide()
        assert title._marquee_layout is None and title._ink_layer.isNull()
    finally:
        sip.delete(title)


def test_playing_disc_repaints_only_when_tick_changes_visible_content(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = install_capture(monkeypatch)
    disc = DiscArt(MediaDiscConfig())
    disc.resize(224, 224)
    disc.show()
    try:
        disc.set_artwork(QPixmap(), playing=True)
        qapp.processEvents()
        repaint_requests: list[None] = []
        monkeypatch.setattr(disc, "update", lambda: repaint_requests.append(None))

        disc._last_tick -= 0.03
        angle = disc._angle
        disc._tick()
        assert disc._angle != angle and capture.readers
        assert not repaint_requests

        cover = QPixmap(32, 32)
        cover.fill(Qt.GlobalColor.red)
        disc.set_artwork(cover, playing=True)
        disc.artMix = 1.0
        repaint_requests.clear()
        disc._tick()
        assert repaint_requests

        disc.set_artwork(QPixmap(), playing=True)
        assert not disc._old_pixmap.isNull() and disc.artMix < 1
        repaint_requests.clear()
        disc._tick()
        assert repaint_requests

        disc.artMix = 1.0
        capture.is_active = True

        def signal_magnitudes(channel: str) -> list[float]:
            return [1.0] * 1025

        monkeypatch.setattr(capture, "magnitudes", signal_magnitudes)
        repaint_requests.clear()
        disc._tick()
        assert max(disc._levels) > 0 and repaint_requests
    finally:
        disc.hide()
        assert not capture.readers
        sip.delete(disc)


def test_popup_preserves_documented_style_identities_after_reparenting(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    panel, sections = popup.equalizer, popup.sections

    def identity(widget: QWidget, name: str, *classes: str) -> None:
        assert widget.objectName() == name
        assert set(classes) <= set(str(widget.property("class")).split())
        assert widget is popup or popup.isAncestorOf(widget)

    try:
        identity(popup, "media-v2-popup", "media-v2-popup")
        viewport = popup._scroll_area.viewport()
        assert viewport is not None
        identity(viewport, "media-viewport")
        identity(popup.border, "media-border")
        identity(popup.surface, "media-surface", "media-surface")
        main = popup.surface.findChild(QWidget, "media-main")
        details = popup.surface.findChild(QWidget, "media-details")
        output = popup.surface.findChild(QWidget, "media-v2-output")
        timeline = popup.surface.findChild(QWidget, "media-v2-timeline")
        separator = popup.surface.findChild(QWidget, "media-v2-separator")
        presets = popup.surface.findChild(QWidget, "media-presets")
        assert main is not None and details is not None and output is not None
        assert timeline is not None and separator is not None and presets is not None
        identity(main, "media-main")
        identity(details, "media-details")
        identity(popup.art, "media-art", "media-art", "artwork")
        identity(popup.title, "media-v2-title", "media-title", "title")
        identity(popup.artist, "media-v2-artist", "media-artist", "artist")
        identity(output, "media-v2-output", "media-output")
        identity(popup.device, "media-v2-output-label", "media-output-label", "label")
        identity(popup.source, "media-source", "btn", "media-source")
        identity(popup.selector, "media-player-selector", "combobox", "media-player-selector", "automatic")
        assert popup.selector.popup_menu.objectName() == "media-player-menu"
        assert {"menu", "media-player-menu"} <= set(str(popup.selector.popup_menu.property("class")).split())
        assert popup.selector.popup_menu.parent() is popup.selector
        identity(timeline, "media-v2-timeline", "media-timeline")
        identity(popup.elapsed, "media-v2-elapsed", "playback-time", "elapsed")
        identity(popup.duration, "media-v2-duration", "playback-time", "duration")
        identity(separator, "media-v2-separator", "separator", "media-separator")
        identity(presets, "media-presets", "presets")
        identity(popup.controls, "media-controls", "media-controls")
        identity(popup.controls.previous, "media-previous", "btn", "transport", "previous")
        identity(popup.controls.play, "media-play", "btn", "transport", "play")
        popup.controls.play.set_playing(True)
        identity(popup.controls.play, "media-play", "btn", "transport", "pause")
        identity(popup.controls.next, "media-next", "btn", "transport", "next")
        for shape in ("square", "rounded", "circle"):
            popup.controls.play.set_shape(shape)
            assert shape in str(popup.controls.play.property("class")).split()
        popup.controls.play.set_shape("rounded")
        identity(popup.progress, "media-progress", "media-progress")
        identity(popup.progress._track, "media-progress-track", "media-progress-track")
        identity(popup.progress._fill, "media-progress-fill", "media-progress-fill")
        identity(popup.progress._handle, "media-progress-handle", "media-progress-handle")
        identity(panel, "media-equalizer-section", "equalizer-section")
        identity(panel.bands, "media-equalizer", "equalizer")
        for slider, band in zip(
            panel.bands.sliders, ("31", "63", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"), strict=True
        ):
            identity(slider, f"media-eq-{band}", "eq-band", f"band-{band}")
            assert panel.bands.isAncestorOf(slider)
        assert set(panel.buttons) == {"Flat", "Bass", "Treble", "Vocal", "Pop", "Rock", "Jazz", "Classic"}
        for name, button in panel.buttons.items():
            identity(button, f"media-preset-{name.lower()}", "btn", "preset", name.lower())
        identity(panel.title, "media-equalizer-title", "equalizer-title", "title")
        identity(panel.status, "media-equalizer-status", "equalizer-status", "label")
        identity(panel.current, "media-equalizer-current", "equalizer-current", "label")
        identity(panel.apply_button, "media-equalizer-apply", "equalizer-apply")
        identity(sections.tabs, "media-section-tabs", "media-section-tabs")
        identity(sections.audio.dynamics, "media-audio-dynamics", "audio-dynamics")
        identity(sections.audio.adaptive, "media-audio-adaptive")
        identity(sections.audio.reset_button, "media-audio-reset", "audio-reset")
        assert not hasattr(sections.audio, "test_button")
        assert not hasattr(sections.lyrics, "import_button")
        assert panel.header.isAncestorOf(panel.apply_button)
        assert panel.header.isAncestorOf(sections.audio.reset_button)
        assert panel.header.isAncestorOf(sections.audio.adaptive)
        assert {"btn", "lyrics-retry", "lyrics-action"} <= set(
            str(sections.lyrics.retry_button.property("class")).split()
        )
    finally:
        popup.hide()
        panel.apo.shutdown()
        sip.delete(parent)


def test_popup_publishes_documented_dynamic_style_classes(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    first = MediaSessionState(Player("one", "one.app", "One"))
    second = MediaSessionState(Player("two", "two.app", "Two"))
    try:
        for playback, expected in (
            (None, "empty"),
            (PlaybackState.UNKNOWN, "unknown"),
            (PlaybackState.OPENED, "opened"),
            (PlaybackState.CHANGING, "changing"),
            (PlaybackState.STOPPED, "stopped"),
            (PlaybackState.PLAYING, "playing"),
            (PlaybackState.PAUSED, "paused"),
            (PlaybackState.CLOSED, "closed"),
        ):
            state = (
                MediaState() if playback is None else MediaState((replace(first, playback=Playback(playback)),), "one")
            )
            popup.set_state(state, QPixmap())
            assert popup.property("class") == f"media-v2-popup {expected}"

        popup.set_state(MediaState((first, second), "one"), QPixmap())
        assert "automatic" in str(popup.source.property("class")).split()
        assert "automatic" in str(popup.selector.property("class")).split()
        popup.set_state(MediaState((first, second), "one", "one"), QPixmap())
        assert "pinned" in str(popup.source.property("class")).split()
        assert "pinned" in str(popup.selector.property("class")).split()
    finally:
        popup.hide()
        popup.equalizer.apo.shutdown()
        sip.delete(parent)


@pytest.mark.parametrize("scale", [0.75, 1, 2])
def test_canonical_layout_negotiates_pages_without_clipping_and_reopens_stably(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, scale: float
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 4000, 2500), scale=scale)
    try:
        for _ in range(3):
            popup.open_at_parent()
            qapp.processEvents()
            assert popup.width() == round(625 * scale) and popup.height() == round(565 * scale)
            for index in range(3):
                popup.sections.tabs.setCurrentIndex(index)
                popup.sections.finish()
                qapp.processEvents()
                assert popup.height() == round(565 * scale)
                page = popup.sections.pages[index]
                vertical, horizontal = page.verticalScrollBar(), page.horizontalScrollBar()
                assert vertical is not None and horizontal is not None
                assert vertical.maximum() == 0 and horizontal.maximum() == 0
                viewport = page.viewport()
                assert viewport is not None
                controls = (
                    popup.equalizer.buttons.values()
                    if index == 0
                    else (popup.sections.audio.dynamics,)
                    if index == 1
                    else (popup.sections.lyrics.message,)
                )
                for control in controls:
                    assert viewport.rect().contains(QRect(control.mapTo(viewport, QPoint()), control.size()))
            popup.hide()
    finally:
        popup.equalizer.apo.shutdown()
        sip.delete(parent)


def test_player_picker_is_visible_only_for_multiple_sessions_and_retires_menu_when_single(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    first, second = (MediaSessionState(Player(sid, sid + ".app", sid.title())) for sid in ("one", "two"))
    try:
        popup.set_state(MediaState((first,), "one"), QPixmap())
        popup.open_at_parent()
        qapp.processEvents()
        assert popup.source.isVisible() and not popup.source.isEnabled()
        assert popup.source.focusPolicy() == Qt.FocusPolicy.NoFocus and not popup.selector.isVisible()
        popup._open_session_menu()
        assert not popup.selector.menu_active
        popup.set_state(MediaState((first, second), "one"), QPixmap())
        qapp.processEvents()
        assert popup.selector.isVisible() and not popup.source.isVisible() and popup.selector.width() == 140
        assert popup.selector._display_label == "One" and popup.selector.itemText(0) == "Automatic"
        popup._open_session_menu()
        assert popup.selector.menu_active
        popup.set_state(MediaState((replace(first, metadata_ready=True),), "one"), QPixmap())
        assert not popup.selector.menu_active and popup.source.isVisible()
    finally:
        popup.hide()
        popup.equalizer.apo.shutdown()
        sip.delete(parent)


def test_seek_during_pause_decay_does_not_freeze_wave_clock(qapp: QApplication) -> None:
    from core.widgets.yasb.media_v2_components import SeekSlider

    qt = cast(Any, QTest)
    slider = SeekSlider(1)
    try:
        slider.show()
        slider.set_playing(True)
        qt.qWait(660)
        slider.set_playing(False)
        qt.qWait(80)
        assert 0 < slider.waveAmplitude < 1
        slider.cancel_interaction()
        qt.qWait(650)
        assert slider.waveAmplitude == 0
        assert slider._wave_clock.state() != QPropertyAnimation.State.Running
    finally:
        slider.hide()
        sip.delete(slider)


def test_short_progress_wave_keeps_a_visible_crest(qapp: QApplication) -> None:
    from core.widgets.yasb.media_v2_components import SeekSlider

    slider = SeekSlider(1)
    slider.setStyleSheet(
        ".media-progress-fill { background: #89b4fa; }"
        ".media-progress-track { background: #313244; }"
        ".media-progress-handle { background: #cdd6f4; }"
    )
    slider.resize(625, 50)
    try:
        slider.show()
        slider.set_progress(0.05, reset=True)
        slider.waveOpacity = 1.0
        slider.wavePhase = 0.0
        slider.waveAmplitude = 0.0
        qapp.processEvents()
        base = slider.grab().toImage()
        track, fill, handle = slider._visual_rects()
        slider.waveAmplitude = 1.0
        qapp.processEvents()
        wave = slider.grab().toImage()
        changed = sum(
            1
            for y in range(max(0, round(handle.top()) - 12), round(handle.top()))
            for x in range(max(0, round(handle.left())), round(handle.right()) + 1)
            if wave.pixelColor(x, y) != base.pixelColor(x, y)
        )
        assert changed >= 8
        lookahead_changed = sum(
            1
            for y in range(max(0, round(handle.top()) - 12), round(handle.top()))
            for x in range(round(fill.right()) + 2, round(min(track.right(), fill.right() + 32)))
            if wave.pixelColor(x, y) != base.pixelColor(x, y)
        )
        assert lookahead_changed >= 4
    finally:
        slider.hide()
        sip.delete(slider)


def test_wave_styled_frame_preserves_existing_path_clip(qapp: QApplication) -> None:
    from core.widgets.yasb.media_v2_components import SeekSlider

    frame = QFrame()
    frame.setStyleSheet("QFrame { background: white; }")
    image = QImage(30, 30, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    path = QPainterPath()
    path.addRect(QRectF(10, 10, 5, 5))
    painter = QPainter(image)
    painter.setClipPath(path)
    SeekSlider._paint_styled_frame(painter, frame, QRectF(0, 0, 30, 30))
    painter.end()
    assert image.pixelColor(12, 12).alpha() == 255
    assert image.pixelColor(5, 5).alpha() == 0
    sip.delete(frame)


@pytest.mark.parametrize("radius", [8, 999])
def test_half_seek_thumb_is_round_with_theme_color(qapp: QApplication, radius: int) -> None:
    from core.widgets.yasb.media_v2_components import SeekSlider

    slider = SeekSlider(1)
    slider.setStyleSheet(
        f".media-progress-handle {{ background: #cdd6f4; border: none; border-radius: {radius}px; }}"
        ".media-progress-fill { background: #89b4fa; }"
        ".media-progress-track { background: #313244; }"
    )
    slider.resize(350, 50)
    try:
        slider.show()
        slider.set_progress(0.5, reset=True)
        slider._hovered = False
        slider.handleScale = 1
        slider.handleTint = 0
        image = slider.grab().toImage()
        _, fill, handle = slider._visual_rects()
        thumb = QColor("#cdd6f4")
        middle, corner = handle.center().toPoint(), handle.topLeft().toPoint()
        assert image.pixelColor(middle) == thumb
        assert image.pixelColor(corner + QPoint(1, 1)) != thumb
        assert image.pixelColor(middle + QPoint(0, -7)) == thumb
        assert image.pixelColor(fill.center().toPoint()) != thumb
    finally:
        slider.hide()
        sip.delete(slider)


def test_interrupted_intro_close_preserves_band_presentation(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        effect = popup.equalizer.bands.intro[0]
        effect.sequence.setCurrentTime(600)
        progress = effect.progress
        assert 0 < progress < 1
        popup.hide_animated()
        assert effect.progress == progress
        popup.open_at_parent()
        assert effect.progress == progress and not popup._is_closing
    finally:
        popup.hide()
        popup.equalizer.apo.shutdown()
        sip.delete(parent)


def test_wave_reopen_resets_hover_and_hidden_clock(qapp: QApplication) -> None:
    from core.widgets.yasb.media_v2_components import SeekSlider
    from core.widgets.yasb.media_v2_motion import animate

    slider = SeekSlider(1)
    try:
        slider.show()
        slider._hovered = True
        slider.handleScale = 1.2
        slider.waveOpacity = 0.9
        animate(slider, "handleScale", 1.15, 150)
        slider.hide()
        slider.show()
        assert slider.handleScale == 1 and slider.waveOpacity == 0.55
        slider.set_playing(True)
        assert slider._wave_clock.state() == QPropertyAnimation.State.Running
        slider.hide()
        assert slider._wave_clock.state() != QPropertyAnimation.State.Running
        assert all(
            m.state() != QPropertyAnimation.State.Running
            for m in cast(dict[str, QPropertyAnimation], getattr(slider, "_motion")).values()
        )
    finally:
        slider.hide()
        sip.delete(slider)


def test_header_morph_and_adaptive_overlay_stay_page_scoped(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.widgets.yasb.media_v2_motion import settle

    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        qapp.processEvents()
        sections, panel = popup.sections, popup.equalizer
        tabs_rect = sections.tabs.geometry()
        before = sections.action_slot.extent
        sections.tabs.setCurrentIndex(1)
        assert sections.action_slot.extent == before
        assert cast(dict[str, QPropertyAnimation], getattr(sections.action_slot, "_motion"))["extent"].duration() == 400
        sections.finish()
        qapp.processEvents()
        assert sections.tabs.geometry() == tabs_rect
        assert sections.audio.reset_button.isVisible()
        sections.tabs.setCurrentIndex(0)
        panel.adaptiveMix = 1
        panel._place_adaptive_overlay()
        assert panel.manual_opacity.opacity() == pytest.approx(0.3)
        assert panel.adaptive_overlay.isVisible()
        assert panel.adaptive_overlay.parentWidget() is sections.pages[0].viewport()
        viewport = sections.pages[0].viewport()
        assert viewport is not None
        assert panel.adaptive_overlay.geometry() == viewport.rect()
        sections.tabs.setCurrentIndex(1)
        assert not panel.adaptive_overlay.isVisible()
        settle(panel)
    finally:
        popup.hide()
        popup.equalizer.apo.shutdown()
        sip.delete(parent)
