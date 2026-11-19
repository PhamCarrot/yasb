"""Bounded worker-side image reuse across Media V2 views.

The existing view tasks still own demand, coalescing and publication. This cache
starts no workers and performs no GUI work. A single worker lock also collapses
concurrent identical work; only QImage snapshots cross back to the GUI thread.
"""

from __future__ import annotations

import hashlib
import sys
import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import cast

from PyQt6.QtGui import QImage

ImageAsset = tuple[QImage, tuple[str, ...]]


@dataclass(frozen=True)
class ImageCacheState:
    entries: int
    bytes: int
    hits: int
    misses: int


def _key_weight(key: Hashable) -> int:
    return sys.getsizeof(key) + (
        sum(_key_weight(item) for item in cast(tuple[Hashable, ...], key)) if isinstance(key, tuple) else 0
    )


def _asset_weight(key: Hashable, asset: ImageAsset) -> int:
    image, palette = asset
    # QImage pixels alone omit compressed-file metadata retained after decode.
    # Keep it intact, but count native ICC/palette/UTF-16 text and Python keys.
    metadata = image.colorSpace().iccProfile().size() + len(image.colorTable()) * 4
    metadata += sum(
        len(name.encode("utf-16-le")) + len(image.text(name).encode("utf-16-le")) for name in image.textKeys()
    )
    return image.sizeInBytes() + metadata + _key_weight(key) + sum(sys.getsizeof(color) for color in palette) + 128


class ImageAssetCache:
    def __init__(self, max_entries: int = 8, max_bytes: int = 32 * 1024 * 1024) -> None:
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self._lock = threading.RLock()
        self._entries: OrderedDict[Hashable, tuple[ImageAsset, int]] = OrderedDict()
        self._bytes = self._hits = self._misses = 0
        self._state = ImageCacheState(0, 0, 0, 0)

    def get(self, key: Hashable, create: Callable[[], ImageAsset]) -> ImageAsset:
        # Called only within the existing to_thread work. Never take this lock
        # from a widget or audio callback. Retain no compressed input in the key.
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                asset, _ = cached
                self._hits += 1
                self._entries.move_to_end(key)
            else:
                self._misses += 1
                self._state = ImageCacheState(len(self._entries), self._bytes, self._hits, self._misses)
                image, palette = create()  # Exceptions are retryable, never cached.
                asset = (QImage(image), tuple(palette))
                weight = _asset_weight(key, asset)
                if self.max_entries > 0 and weight <= self.max_bytes:
                    while self._entries and (
                        len(self._entries) >= self.max_entries or self._bytes + weight > self.max_bytes
                    ):
                        _, old = self._entries.popitem(last=False)
                        self._bytes -= old[1]
                    self._entries[key] = asset, weight
                    self._bytes += weight
            self._state = ImageCacheState(len(self._entries), self._bytes, self._hits, self._misses)
            # Qt implicit sharing is thread-safe for these independent values;
            # callers may mutate their copy without altering the cached image.
            return QImage(asset[0]), asset[1]

    def state(self) -> ImageCacheState:
        # Immutable published snapshot: diagnostics never block the GUI on work.
        return self._state


def image_digest(image: QImage) -> bytes:
    bits = image.constBits()
    if bits is None:
        return b""
    return hashlib.sha256(bits.asstring(image.sizeInBytes())).digest()


shared_image_assets = ImageAssetCache()
