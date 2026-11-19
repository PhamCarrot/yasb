"""Real worker concurrency and image mutation/eviction contracts for shared assets."""

import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin
from PyQt6.QtGui import QColor, QColorSpace, QImage
from PyQt6.QtWidgets import QApplication

from core.widgets.services.media.image_assets import ImageAssetCache
from core.widgets.yasb import media_v2 as media
from core.widgets.yasb import media_v2_background as background


def test_concurrent_identical_work_executes_once_and_diagnostics_never_wait(qapp: QApplication) -> None:
    cache = ImageAssetCache()
    entered, release = threading.Event(), threading.Event()
    calls = 0

    def create():
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(2)
        image = QImage(20, 20, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        return image, ("#ff0000",)

    with ThreadPoolExecutor(max_workers=3) as executor:
        first = executor.submit(cache.get, "same", create)
        assert entered.wait(1)
        second = executor.submit(cache.get, "same", create)
        try:
            snapshot = executor.submit(cache.state).result(timeout=0.25)
            assert snapshot.entries == 0 and snapshot.misses == 1
        finally:
            release.set()
        one, two = first.result(), second.result()
    assert calls == 1 and cache.state().hits == 1
    assert one[0] == two[0] and one[1] == two[1] == ("#ff0000",)
    one[0].fill(QColor("blue"))
    assert two[0].pixelColor(0, 0) == QColor("red")
    assert cache.get("same", create)[0].pixelColor(0, 0) == QColor("red")


def test_lru_enforces_bytes_and_entry_limits_and_does_not_retain_oversize(qapp: QApplication) -> None:
    cache = ImageAssetCache(max_entries=2, max_bytes=1000)

    def asset(size: int = 10):
        image = QImage(size, size, QImage.Format.Format_RGB32)
        image.fill(QColor("green"))
        return image, ()

    cache.get("one", asset)
    cache.get("two", asset)
    assert cache.state().entries == 1 and 400 < cache.state().bytes < 1000
    cache.get("huge", lambda: asset(100))
    assert cache.state().entries == 1 and 400 < cache.state().bytes < 1000
    cache = ImageAssetCache(max_entries=2, max_bytes=10000)
    for key in ("one", "two", "one", "three"):
        cache.get(key, asset)
    before = cache.state().misses
    cache.get("one", asset)
    assert cache.state().misses == before
    cache.get("two", asset)
    assert cache.state().misses == before + 1 and cache.state().entries == 2


def test_failed_work_is_retryable_and_never_publishes_a_partial_entry(qapp: QApplication) -> None:
    cache = ImageAssetCache()

    def fail():
        raise ValueError("owned preparation failure")

    with pytest.raises(ValueError):
        cache.get("retry", fail)
    assert cache.state().entries == 0
    image, _ = cache.get("retry", lambda: (QImage(1, 1, QImage.Format.Format_RGB32), ()))
    assert not image.isNull() and cache.state().entries == 1


def test_decode_identity_is_content_and_extent_with_detached_results(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(media, "shared_image_assets", ImageAssetCache())
    data = BytesIO()
    Image.new("RGB", (256, 128), "red").save(data, format="PNG")
    first = media.decode_artwork(data.getvalue(), 64)
    second = media.decode_artwork(bytes(bytearray(data.getvalue())), 64)
    assert first == second and first.width() == 64
    assert media.shared_image_assets.state().hits == 1
    first.fill(QColor("blue"))
    assert second.pixelColor(0, 0) == QColor("red")
    smaller = media.decode_artwork(data.getvalue(), 32)
    assert smaller.width() == 32 and media.shared_image_assets.state().misses == 2


def test_background_identity_covers_pixel_palette_radius_and_file_changes(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache = ImageAssetCache()
    monkeypatch.setattr(background, "shared_image_assets", cache)
    image = QImage(32, 32, QImage.Format.Format_Indexed8)
    image.setColorTable([QColor("red").rgba()])
    image.fill(0)
    red, red_palette = background.prepare_assets(image, "", 0)
    blue_image = QImage(image)
    blue_image.setColorTable([QColor("blue").rgba()])
    blue, blue_palette = background.prepare_assets(blue_image, "", 0)
    assert red != blue and red_palette != blue_palette
    background.prepare_assets(blue_image, "", 2)
    assert cache.state().misses == 3
    file = tmp_path / "owned-background.png"
    assert red.save(str(file))
    old, _ = background.prepare_assets(QImage(), str(file), 0)
    assert blue.save(str(file))
    new, _ = background.prepare_assets(QImage(), str(file), 0)
    assert old != new
    file.unlink()
    with pytest.raises(FileNotFoundError):
        background.prepare_assets(QImage(), str(file), 0)


@pytest.mark.parametrize("metadata", ["text", "icc"])
def test_compressed_image_metadata_counts_toward_budget_without_losing_fidelity(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, metadata: str
) -> None:
    cache = ImageAssetCache(max_bytes=1024 * 1024)
    monkeypatch.setattr(media, "shared_image_assets", cache)
    data = BytesIO()
    options: dict[str, object] = {}
    if metadata == "text":
        info = PngImagePlugin.PngInfo()
        info.add_text("Description", "x" * (2 * 1024 * 1024), zip=True)  # pyright: ignore[reportUnknownMemberType] - Pillow metadata writer lacks parameter stubs.
        options["pnginfo"] = info
    else:
        profile = QColorSpace(QColorSpace.NamedColorSpace.SRgb).iccProfile().data()
        options["icc_profile"] = (
            (4 * 1024 * 1024).to_bytes(4, "big") + profile[4:] + b"\0" * (4 * 1024 * 1024 - len(profile))
        )
    Image.new("RGB", (64, 64), "red").save(data, format="PNG", **options)  # type: ignore[arg-type]
    assert len(data.getvalue()) < 10000
    image = media.decode_artwork(data.getvalue(), 64)
    assert not image.isNull()
    if metadata == "text":
        assert len(image.text("Description")) == 2 * 1024 * 1024
    else:
        assert image.colorSpace().iccProfile().size() == 4 * 1024 * 1024
    assert cache.state().entries == cache.state().bytes == 0
