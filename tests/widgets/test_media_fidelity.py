# pyright: reportPrivateUsage=false

from collections.abc import Callable
from dataclasses import replace
from typing import Any, cast

import PyQt6.sip as sip
import pytest
from PyQt6.QtCore import QAbstractAnimation, QPoint, QPropertyAnimation, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFrame, QWidget

from core.validation.widgets.yasb.media_v2 import MediaDiscConfig
from core.widgets.services.media.model import MediaSessionState, MediaState, Metadata, Playback, PlaybackState, Player
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


def test_title_tooltip_follows_track_and_empty_state(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    player = MediaSessionState(Player("one", "one.app", "One"))
    track = replace(player, metadata=Metadata(title="Another Sky", album="North"), metadata_ready=True)
    try:
        popup.set_state(MediaState((track,), "one"), QPixmap())
        tip = getattr(popup.title, "_tooltip_filter")
        assert tip.tooltip_text == "Another Sky\nNorth"
        for state in (MediaState((player,), "one"), MediaState()):
            popup.set_state(state, QPixmap())
            assert tip.tooltip_text == popup.title.text()
    finally:
        popup.hide()
        popup.equalizer.apo.shutdown()
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
            assert popup.width() == round(625 * scale) and popup.height() == round(569 * scale)
            for index in range(3):
                popup.sections.tabs.setCurrentIndex(index)
                popup.sections.finish()
                qapp.processEvents()
                tabs = popup.sections.tabs
                for tab_index in range(tabs.count()):
                    assert tabs.rect().contains(tabs.tabRect(tab_index)), (tabs.rect(), tabs.tabRect(tab_index))
                assert popup.height() == round(569 * scale)
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


def test_info_row_centers_device_and_via_and_right_aligns_selector(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PyQt6.QtWidgets import QStyle, QStyleOptionComboBox

    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        for effect in popup._intro:
            effect.finish()
        players = tuple(MediaSessionState(Player(sid, sid, sid)) for sid in ("One", "Two"))
        for name in ("DAC", "A long device and player name " * 7):
            for count in (1, 2):
                popup.set_state(MediaState(players[:count], "One"), QPixmap())
                qapp.processEvents()
                source = popup.source if count == 1 else popup.selector
                for widget in (popup.device, source):
                    if widget is popup.selector:
                        setter = popup.selector.set_display_label
                        option = QStyleOptionComboBox()
                        popup.selector.initStyleOption(option)
                        bounds = cast(QStyle, widget.style()).subControlRect(
                            QStyle.ComplexControl.CC_ComboBox, option, QStyle.SubControl.SC_ComboBoxEditField, widget
                        )
                    else:
                        setter = popup.device.setText if widget is popup.device else popup.source.setText
                        bounds = widget.contentsRect()
                    setter("")
                    empty = widget.grab().toImage()
                    setter(name)
                    drawn = widget.grab().toImage()
                    dpr = drawn.devicePixelRatio()
                    ink = [
                        x / dpr
                        for x in range(drawn.width())
                        if any(drawn.pixel(x, y) != empty.pixel(x, y) for y in range(drawn.height()))
                    ]
                    assert ink, widget.objectName()
                    if widget is not popup.selector:
                        assert abs((min(ink) + max(ink)) / 2 - bounds.center().x()) <= 3, (bounds, min(ink), max(ink))
                    else:
                        assert abs(max(ink) - bounds.right()) <= 14, (widget.objectName(), bounds, ink[-1:])
                        if name == "DAC":
                            assert min(ink) > bounds.center().x(), widget.objectName()
                    if name != "DAC":
                        assert max(ink) - min(ink) >= bounds.width() * 0.65, widget.objectName()
    finally:
        popup.hide()
        popup.equalizer.apo.shutdown()
        sip.delete(parent)


def test_open_stages_art_text_transport_and_individual_equalizer_bands(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        stages = {effect.widget: effect for effect in popup._intro}
        for effect in stages.values():
            if effect.widget.isVisible():
                effect.sequence.setCurrentTime(200)
        assert 0 < stages[popup.title].progress < stages[popup.art].progress < 1
        assert stages[popup.controls].progress == 0
        bands = popup.equalizer.bands
        assert {effect.widget for effect in bands.intro} == {slider.parentWidget() for slider in bands.sliders}
        for effect in bands.intro:
            assert effect.progress == 0
            effect.sequence.setCurrentTime(650)
            assert 0 < effect.progress < 1
        assert bands.intro[0]._offset.y() < bands.intro[-1]._offset.y()
    finally:
        popup.hide()
        popup.equalizer.apo.shutdown()
        sip.delete(parent)


def test_player_selector_has_a_visible_themeable_arrow(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    from PyQt6.QtWidgets import QStyle, QStyleOptionComboBox

    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        players = tuple(MediaSessionState(Player(sid, sid, sid)) for sid in ("One", "Two"))
        popup.set_state(MediaState(players, "One"), QPixmap())
        popup.open_at_parent()
        for effect in popup._intro:
            effect.finish()
        selector = popup.selector
        option = QStyleOptionComboBox()
        selector.initStyleOption(option)
        area = cast(QStyle, selector.style()).subControlRect(
            QStyle.ComplexControl.CC_ComboBox, option, QStyle.SubControl.SC_ComboBoxArrow, selector
        )
        area.adjust(2, 5, -2, -5)

        def colors() -> set[str]:
            image = selector.grab(area).toImage()
            return {image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())}

        assert len(colors()) > 2
        selector.setStyleSheet("QComboBox::down-arrow { image: none; background: #ed0bee; width: 8px; height: 8px; }")
        assert "#ed0bee" in colors()
    finally:
        popup.hide()
        popup.equalizer.apo.shutdown()
        sip.delete(parent)


def test_visual_preset_buttons_move_handles_and_reverse_from_the_current_position(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    try:
        popup.open_at_parent()
        panel = popup.equalizer
        slider = panel.bands.sliders[0]
        qt_test = cast(Any, QTest)
        qt_test.mouseClick(panel.buttons["Bass"], Qt.MouseButton.LeftButton)
        motion = panel.bands.travel
        assert slider.gain == 0 and panel.apo.editing_gains[0] == 5
        motion.setCurrentTime(65)
        first = slider.gain
        assert 0 < first < 5
        qt_test.mouseClick(panel.buttons["Treble"], Qt.MouseButton.LeftButton)
        assert slider.gain == pytest.approx(first) and panel.apo.editing_gains[0] == -2
        motion.setCurrentTime(65)
        assert -2 < slider.gain < first
        motion.setCurrentTime(motion.duration())
        assert slider.gain == -2 and not panel.apo.has_draft

        def supersede(values: tuple[float, ...]) -> None:
            if values[0] == 5:
                panel.buttons["Flat"].click()

        panel.apo.committed_changed.connect(supersede)
        panel.buttons["Bass"].click()
        assert panel.preset == "Flat" and motion.targets[0] == 0 and slider.gain == -2
        motion.setCurrentTime(65)
        assert -2 < slider.gain < 0 and not panel.apo.has_draft
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


@pytest.mark.parametrize(("progress", "minimum_crest_pixels"), [(0.02, 4), (0.05, 8)])
def test_short_progress_wave_stays_inside_authoritative_fill(
    qapp: QApplication, progress: float, minimum_crest_pixels: int
) -> None:
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
        slider.set_progress(progress, reset=True)
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
            for x in range(round(track.left()), round(fill.right()) + 1)
            if wave.pixelColor(x, y) != base.pixelColor(x, y)
        )
        assert changed >= minimum_crest_pixels
        lookahead_changed = sum(
            1
            for y in range(max(0, round(handle.top()) - 12), round(handle.top()))
            for x in range(round(fill.right()) + 2, round(min(track.right(), fill.right() + 32)))
            if wave.pixelColor(x, y) != base.pixelColor(x, y)
        )
        assert lookahead_changed == 0
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
        effect.sequence.setCurrentTime(effect.sequence.duration() // 2)
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
        assert sections.action_slot.extent >= before
        action_motion = cast(dict[str, QPropertyAnimation], getattr(sections.action_slot, "_motion", {})).get("extent")
        assert action_motion is not None and action_motion.state() == QPropertyAnimation.State.Running
        action_motion.setCurrentTime(100)
        assert before < sections.action_slot.extent < action_motion.endValue()
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


def test_popup_frame_clock_merges_drivers_and_idles_when_paused_or_closed(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PyQt6.QtCore import QAbstractAnimation, QTimer

    from core.widgets.yasb.media_v2_motion import FrameClock

    parent, popup = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    other_parent, other = make_popup(monkeypatch, QRect(0, 0, 1920, 1040), scale=1)
    capture = install_capture(monkeypatch)
    playing = MediaSessionState(Player("one", "one.app", "One"), playback=Playback(PlaybackState.PLAYING))
    try:
        popup.set_state(MediaState((playing,), "one"), QPixmap())
        popup.open_at_parent()
        qapp.processEvents()
        clock = popup.frame_clock
        assert isinstance(clock, FrameClock) and clock is not other.frame_clock
        assert popup.border._timer.isActive() and popup.art._clock.isActive()
        assert getattr(popup.border._timer, "clock") is clock and popup.art._clock.clock is clock
        assert popup.surface._orbit_timer.clock is clock
        assert clock.subscribers == 2 and clock.state() == QAbstractAnimation.State.Running
        assert other.frame_clock.subscribers == 0 and other.frame_clock.state() != QAbstractAnimation.State.Running
        assert capture.readers
        popup.set_state(MediaState((replace(playing, playback=Playback(PlaybackState.PAUSED)),), "one"), QPixmap())
        assert popup.art._clock.isActive(), "the paused disc decays before it leaves the clock"
        popup.art._decay_started -= popup.art.PAUSE_DECAY_SECONDS + 0.1
        popup.art._tick()
        assert not popup.art._clock.isActive() and clock.subscribers == 1 and not capture.readers
        popup.hide()
        qapp.processEvents()
        assert clock.subscribers == 0 and clock.state() != QAbstractAnimation.State.Running
        assert not [timer for timer in popup.findChildren(QTimer) if timer.isActive()]
        assert not capture.readers
    finally:
        popup.hide()
        popup.equalizer.apo.shutdown()
        other.equalizer.apo.shutdown()
        sip.delete(parent)
        sip.delete(other_parent)


def test_frame_clock_runs_only_while_subscribed_and_honours_lower_rates(qapp: QApplication) -> None:
    from PyQt6.QtCore import QAbstractAnimation, QObject

    from core.widgets.yasb.media_v2_motion import FrameClock

    owner = QObject()
    clock = FrameClock(owner)
    calls: list[str] = []
    fast = clock.subscription(lambda: calls.append("fast"), 60)
    slow = clock.subscription(lambda: calls.append("slow"), 12)
    try:
        fast.start()
        slow.start()
        fast.start()
        assert clock.subscribers == 2 and clock.state() == QAbstractAnimation.State.Running
        cast(Any, QTest).qWait(400)
        assert calls.count("fast") >= 2 * calls.count("slow") > 0
        fast.stop()
        assert clock.state() == QAbstractAnimation.State.Running and not fast.isActive()
        slow.stop()
        slow.stop()
        assert clock.subscribers == 0 and clock.state() == QAbstractAnimation.State.Stopped
    finally:
        sip.delete(owner)


def preset_panel(qapp: QApplication, **equalizer: object) -> tuple[QWidget, Any]:
    from core.validation.widgets.yasb.media_v2 import MediaEqualizerConfig
    from core.widgets.yasb.media_v2_equalizer import EqualizerPanel

    host = QWidget()
    host.resize(600, 320)
    panel = EqualizerPanel(MediaEqualizerConfig.model_validate(equalizer), 1, host)
    panel.setGeometry(host.rect())
    host.show()
    qapp.processEvents()
    return host, panel


STYLE_CHECKS: dict[str, Callable[[list[float]], bool]] = {
    "cascade": lambda done: done[0] > done[1] > done[2] > 0 == done[9],
    "center_out": lambda done: done[4] == done[5] > done[3] > done[2] > 0 == done[0],
    "edges_in": lambda done: done[0] == done[9] > done[1] and done[4] == 0,
    "wave": lambda done: done[0] > done[1] > done[2] > 0 == done[9],
    "spring": lambda done: len({round(value, 6) for value in done}) == 1 and done[0] > 0,
}


@pytest.mark.parametrize("style", list(STYLE_CHECKS))
def test_preset_motion_styles_move_bands_with_distinct_progress(qapp: QApplication, style: str) -> None:
    check = STYLE_CHECKS[style]
    host, panel = preset_panel(qapp, preset_motion={"style": style, "duration_ms": 300, "stagger_ms": 60})
    try:
        panel.select_preset("Rock")
        travel = panel.bands.travel
        travel.setCurrentTime(150)
        done = [slider.gain / target for slider, target in zip(panel.bands.sliders, panel.apo.editing_gains)]
        assert check(done), (style, [round(value, 3) for value in done])
        travel.setCurrentTime(travel.duration())
        assert [slider.gain for slider in panel.bands.sliders] == [float(gain) for gain in panel.apo.editing_gains]
    finally:
        panel.apo.shutdown()
        sip.delete(host)


def test_overshooting_styles_exceed_then_settle_on_the_target(qapp: QApplication) -> None:
    host, panel = preset_panel(qapp, preset_motion={"style": "spring", "duration_ms": 600})
    try:
        panel.select_preset("Bass")
        travel, slider = panel.bands.travel, panel.bands.sliders[1]
        peak = 0.0
        for time in range(0, 601, 20):
            travel.setCurrentTime(time)
            peak = max(peak, slider.gain)
        assert peak > 7 and slider.gain == 7
    finally:
        panel.apo.shutdown()
        sip.delete(host)


def test_staggered_travel_reverses_ignores_echoes_and_releases_a_grabbed_band(qapp: QApplication) -> None:
    host, panel = preset_panel(qapp, preset_motion={"style": "cascade", "duration_ms": 300, "stagger_ms": 40})
    try:
        sliders, travel = panel.bands.sliders, panel.bands.travel
        panel.select_preset("Bass")
        travel.setCurrentTime(120)
        first = [slider.gain for slider in sliders]
        assert 0 < first[0] < 5
        panel.select_preset("Treble")
        assert [slider.gain for slider in sliders] == pytest.approx(first), "reversal starts from the presented gains"
        travel.setCurrentTime(100)
        assert -2 < sliders[0].gain < first[0]
        time = travel.currentTime()
        panel._present_gains(panel.apo.editing_gains)
        assert travel.currentTime() == time and travel.state() == QAbstractAnimation.State.Running
        panel._interrupt(sliders[3])
        held = sliders[3].gain
        travel.setCurrentTime(travel.duration())
        assert sliders[3].gain == held and sliders[0].gain == -2 and sliders[9].gain == 6
    finally:
        panel.apo.shutdown()
        sip.delete(host)


@pytest.mark.parametrize("effect", ["curve", "glow", "scan", "lightning", "ripple", "center_pulse"])
def test_preset_effects_paint_early_and_middle_frames_and_stop_when_settled(qapp: QApplication, effect: str) -> None:
    host, panel = preset_panel(qapp, preset_effect=effect)
    try:
        baseline = host.grab().toImage()
        panel.select_preset("Rock")
        bands = panel.bands
        animation = cast(dict[str, QPropertyAnimation], getattr(bands, "_motion"))["lightningPhase"]
        frames: list[QImage] = []
        for fraction in (0.1, 0.5):
            animation.setCurrentTime(round(animation.duration() * fraction))
            bands.travel.setCurrentTime(bands.travel.duration())
            frames.append(host.grab().toImage())
        animation.setCurrentTime(animation.duration())
        assert bands.phase == 1600 and animation.state() != QPropertyAnimation.State.Running
        settled = host.grab().toImage()
        assert frames[0] != settled or frames[1] != settled, effect
        assert not any(
            motion.state() == QAbstractAnimation.State.Running
            for motion in host.findChildren(QAbstractAnimation)
            if motion is not bands.travel
        )
        assert baseline is not None
    finally:
        panel.apo.shutdown()
        sip.delete(host)


def test_random_effect_uses_the_injected_generator_and_none_paints_nothing(qapp: QApplication) -> None:
    import random

    host, panel = preset_panel(qapp, preset_effect="random")
    try:
        panel.bands.random = random.Random(7)
        expected = random.Random(7).choice(sorted(["lightning", "ripple", "center_pulse", "curve", "glow", "scan"]))
        panel.select_preset("Bass")
        assert panel.bands.effect_mode == expected
    finally:
        panel.apo.shutdown()
        sip.delete(host)
    host, panel = preset_panel(qapp, preset_effect="none")
    try:
        panel.select_preset("Bass")
        assert panel.bands.phase == 1600
    finally:
        panel.apo.shutdown()
        sip.delete(host)


def test_preset_motion_total_travel_is_bounded() -> None:
    from pydantic import ValidationError

    from core.validation.widgets.yasb.media_v2 import MediaV2Config

    config = MediaV2Config.model_validate(
        {"popup": {"equalizer": {"preset_motion": {"duration_ms": 1200, "stagger_ms": 200}}}}
    )
    assert config.popup.equalizer.preset_motion.stagger_ms == 200
    with pytest.raises(ValidationError, match="must not exceed 3000"):
        MediaV2Config.model_validate(
            {"popup": {"equalizer": {"preset_motion": {"duration_ms": 1300, "stagger_ms": 200}}}}
        )
