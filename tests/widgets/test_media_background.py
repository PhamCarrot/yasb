# pyright: reportPrivateUsage=false

import asyncio
import threading
from collections.abc import Callable

import PyQt6.sip as sip
import pytest
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import QApplication

from core.validation.widgets.yasb.media_v2 import MediaBackgroundConfig
from core.widgets.yasb import media_v2_background as background


class HeldWorker:
    """Count real executing threads, including work whose awaiter was cancelled."""

    def __init__(self, *, fail: bool = False) -> None:
        self.release = threading.Event()
        self.started = threading.Event()
        self.lock = threading.Lock()
        self.fail = fail
        self.calls: list[str] = []
        self.active = 0
        self.peak = 0
        self.gui_thread = threading.get_ident()

    def __call__(self, image: QImage, filename: str, radius: float) -> tuple[QImage, list[str]]:
        assert threading.get_ident() != self.gui_thread
        with self.lock:
            self.calls.append(image.pixelColor(0, 0).name())
            self.active += 1
            self.peak = max(self.peak, self.active)
        self.started.set()
        try:
            if not self.release.wait(10):
                raise TimeoutError("Test worker was not released")
            if self.fail:
                raise ValueError("Controlled decode failure")
            return QImage(image), [image.pixelColor(0, 0).name()] * 3
        finally:
            with self.lock:
                self.active -= 1


async def until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


def artwork(color: str) -> QPixmap:
    pixmap = QPixmap(8, 8)
    pixmap.fill(QColor(color))
    return pixmap


def test_paused_background_keeps_ambient_static_without_orbit_timer(qapp: QApplication) -> None:
    surface = background.MediaSurface(MediaBackgroundConfig(), 8)
    try:
        surface.show()
        surface.set_media_state(True, False)
        qapp.processEvents()
        assert not surface._orbit_timer.isActive()
        surface.set_media_state(True, True)
        assert surface._orbit_timer.isActive()
    finally:
        surface.hide()
        sip.delete(surface)


def test_hide_reopen_retains_one_actual_worker(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        worker = HeldWorker()
        monkeypatch.setattr(background, "prepare_assets", worker)
        surface = background.MediaSurface(MediaBackgroundConfig(), 8)
        surface.set_artwork(artwork("red"))
        try:
            surface.show()
            await until(worker.started.is_set)
            for _ in range(4):
                surface.hide()
                await asyncio.sleep(0)
                surface.show()
                await asyncio.sleep(0)
            assert len(worker.calls) == 1
            worker.release.set()
            assert surface._task is not None
            await surface._task
            assert worker.peak == 1 and worker.active == 0
            assert surface._loaded_key == surface._key
            assert surface._pixmap.toImage().pixelColor(0, 0) == QColor("red")
        finally:
            worker.release.set()
            surface.hide()
            if surface._task is not None:
                await asyncio.gather(surface._task, return_exceptions=True)
            sip.delete(surface)

    asyncio.run(run())


def test_changes_coalesce_to_latest_artwork(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        worker = HeldWorker()
        monkeypatch.setattr(background, "prepare_assets", worker)
        surface = background.MediaSurface(MediaBackgroundConfig(), 8)
        colors: list[list[str]] = []
        surface.palette_changed.connect(colors.append)
        try:
            surface.set_artwork(artwork("red"))
            surface.show()
            await until(worker.started.is_set)
            surface.set_artwork(artwork("green"), clear_previous=True)
            surface.hide()
            surface.set_artwork(artwork("blue"), clear_previous=True)
            surface.show()
            worker.release.set()
            assert surface._task is not None
            await surface._task
            assert worker.calls == ["#ff0000", "#0000ff"]
            assert worker.peak == 1 and worker.active == 0
            assert colors == [["#0000ff"] * 3]
            assert surface._loaded_key == surface._key
        finally:
            worker.release.set()
            surface.hide()
            if surface._task is not None:
                await asyncio.gather(surface._task, return_exceptions=True)
            sip.delete(surface)

    asyncio.run(run())


@pytest.mark.parametrize("fail", [False, True])
def test_hidden_completion_does_not_publish(qapp: QApplication, monkeypatch: pytest.MonkeyPatch, fail: bool) -> None:
    async def run() -> None:
        worker = HeldWorker(fail=fail)
        monkeypatch.setattr(background, "prepare_assets", worker)
        surface = background.MediaSurface(MediaBackgroundConfig(), 8)
        colors: list[list[str]] = []
        surface.palette_changed.connect(colors.append)
        try:
            surface.set_artwork(artwork("red"))
            surface.show()
            await until(worker.started.is_set)
            task = surface._task
            assert task is not None
            surface.hide()
            worker.release.set()
            await task
            assert not colors
            assert surface._loaded_key is None
            assert surface._pixmap.isNull()
            assert worker.active == 0
            surface.show()
            assert surface._task is not None
            await surface._task
            assert len(colors) == 1
            assert surface._loaded_key == surface._key
            assert worker.peak == 1
        finally:
            worker.release.set()
            surface.hide()
            if surface._task is not None:
                await asyncio.gather(surface._task, return_exceptions=True)
            sip.delete(surface)

    asyncio.run(run())


def test_cached_a_restored_after_pending_b_is_superseded(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        worker = HeldWorker()
        worker.release.set()
        monkeypatch.setattr(background, "prepare_assets", worker)
        surface = background.MediaSurface(MediaBackgroundConfig(), 8)
        first = artwork("red")
        try:
            surface.set_artwork(first, clear_previous=True)
            surface.show()
            assert surface._task is not None
            await surface._task
            worker.release.clear()
            worker.started.clear()
            surface.set_artwork(artwork("blue"), clear_previous=True)
            await until(worker.started.is_set)
            surface.set_artwork(first, clear_previous=True)
            worker.release.set()
            assert surface._task is not None
            await surface._task
            assert surface._loaded_key == surface._key
            assert surface._pixmap.toImage().pixelColor(0, 0) == QColor("red")
            assert worker.calls == ["#ff0000", "#0000ff"]
            assert worker.peak == 1
        finally:
            worker.release.set()
            surface.hide()
            if surface._task is not None:
                await asyncio.gather(surface._task, return_exceptions=True)
            sip.delete(surface)

    asyncio.run(run())


def test_destroyed_surface_drops_result_and_worker_finishes(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        worker = HeldWorker()
        monkeypatch.setattr(background, "prepare_assets", worker)
        surface = background.MediaSurface(MediaBackgroundConfig(), 8)
        colors: list[list[str]] = []
        surface.palette_changed.connect(colors.append)
        surface.set_artwork(artwork("red"))
        surface.show()
        await until(worker.started.is_set)
        task = surface._task
        assert task is not None
        try:
            sip.delete(surface)
            await asyncio.gather(task, return_exceptions=True)
            assert task.cancelled()
            assert worker.active == 1  # Qt destruction cannot interrupt native image work.
            worker.release.set()
            await until(lambda: worker.active == 0)
            assert not colors
            assert len(worker.calls) == worker.peak == 1
        finally:
            worker.release.set()

    asyncio.run(run())


def channels(color: QColor) -> tuple[int, int, int, int]:
    return color.red(), color.green(), color.blue(), color.alpha()


def test_settled_background_is_composed_once_and_released_on_hide(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.widgets.yasb.media_v2_motion import settle

    surface = background.MediaSurface(MediaBackgroundConfig(), 12)
    surface.setStyleSheet("QFrame { background: #1e1e2e; border-radius: 10px; }")
    surface.resize(320, 240)
    surface.show()
    try:
        image = QImage(64, 64, QImage.Format.Format_RGB32)
        image.fill(QColor("#c08040"))
        image.setPixelColor(10, 10, QColor("#2060ff"))
        surface._install(("fixture", 18), QPixmap.fromImage(image), ["#cba6f7", "#89b4fa", "#f38ba8"])
        assert surface._static_layer() is None, "a crossfade paints directly"
        settle(surface)
        cached = surface.grab().toImage()
        layer = surface._static_layer()
        assert layer is not None and surface._static_layer() is layer

        def paint_directly(self: background.MediaSurface) -> QPixmap | None:
            return None

        monkeypatch.setattr(background.MediaSurface, "_static_layer", paint_directly)
        direct = surface.grab().toImage()
        monkeypatch.undo()
        worst = max(
            abs(a - b)
            for y in range(direct.height())
            for x in range(direct.width())
            for a, b in zip(channels(cached.pixelColor(x, y)), channels(direct.pixelColor(x, y)))
        )
        assert worst <= 2
        surface.overlayTop = QColor(0, 0, 0, 10)
        assert surface._static_layer() is not layer
        surface.hide()
        assert surface._layer.isNull() and surface._layer_key is None
    finally:
        sip.delete(surface)
