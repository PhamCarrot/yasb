# pyright: reportPrivateUsage=false

from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

import pytest

from core.validation.widgets.yasb.media_v2 import MediaEqualizerApoConfig
from core.widgets.services.media import equalizer_apo as apo
from core.widgets.services.media.audio_device import AudioOutputState
from core.widgets.services.media.equalizer_apo import (
    BEGIN_MARKER,
    END_MARKER,
    INCLUDE_LINE,
    EqualizerApoConfigManager,
)

OUTPUT = AudioOutputState("test-endpoint", "{01234567-0123-0123-0123-0123456789ab}", "Owned output")
GAINS = (0.0,) * 10
BLOCK = f"{BEGIN_MARKER}\n{INCLUDE_LINE}\n{END_MARKER}\n"


class Registry:
    KEY_READ = 1
    KEY_WOW64_64KEY = 2
    HKEY_LOCAL_MACHINE = 3

    def __init__(self, root: Path) -> None:
        self.available = True
        self.values = {"InstallPath": str(root), "ConfigPath": str(root / "config")}
        self.reads = 0

    def OpenKey(self, hive: int, name: str, reserved: int, access: int) -> AbstractContextManager[Registry]:
        self.reads += 1
        if not self.available:
            raise FileNotFoundError("Not installed in owned registry double")
        return nullcontext(self)

    def QueryValueEx(self, key: Registry, name: str) -> tuple[str, int]:
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], 1


@pytest.mark.parametrize("broken", ["# No block yet\n", BEGIN_MARKER, BLOCK * 2])
def test_repaired_parent_is_revalidated_without_recreating_manager(tmp_path: Path, broken: str) -> None:
    registry = Registry(tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    parent = config / "config.txt"
    parent.write_text(broken)
    manager = EqualizerApoConfigManager(registry)
    options = MediaEqualizerApoConfig()
    assert not manager.apply(GAINS, OUTPUT, options).applied
    parent.write_text(BLOCK)
    assert manager.apply(GAINS, OUTPUT, options).applied


def test_repaired_installation_discovery_is_retried(tmp_path: Path) -> None:
    registry = Registry(tmp_path)
    registry.available = False
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.txt").write_text(BLOCK)
    manager = EqualizerApoConfigManager(registry)
    options = MediaEqualizerApoConfig()
    assert not manager.apply(GAINS, OUTPUT, options).applied
    registry.available = True
    assert manager.apply(GAINS, OUTPUT, options).applied
    assert registry.reads == 2


@pytest.mark.parametrize("key", ["InstallPath", "ConfigPath"])
def test_repaired_registry_value_is_retried(tmp_path: Path, key: str) -> None:
    registry = Registry(tmp_path)
    saved = registry.values.pop(key)
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.txt").write_text(BLOCK)
    manager = EqualizerApoConfigManager(registry)
    options = MediaEqualizerApoConfig()
    assert not manager.apply(GAINS, OUTPUT, options).applied
    registry.values[key] = saved
    assert manager.apply(GAINS, OUTPUT, options).applied


@pytest.mark.parametrize("missing", ["directory", "parent"])
def test_setup_files_appearing_after_failure_are_retried(tmp_path: Path, missing: str) -> None:
    registry = Registry(tmp_path)
    config = tmp_path / "config"
    if missing == "parent":
        config.mkdir()
    manager = EqualizerApoConfigManager(registry)
    options = MediaEqualizerApoConfig()
    assert not manager.apply(GAINS, OUTPUT, options).applied
    config.mkdir(exist_ok=True)
    (config / "config.txt").write_text(BLOCK)
    assert manager.apply(GAINS, OUTPUT, options).applied


@pytest.mark.parametrize("broken", ["# removed managed block\n", BEGIN_MARKER, BLOCK * 2])
def test_previous_success_does_not_hide_external_setup_damage(tmp_path: Path, broken: str) -> None:
    registry = Registry(tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    parent = config / "config.txt"
    parent.write_text(BLOCK)
    manager = EqualizerApoConfigManager(registry)
    options = MediaEqualizerApoConfig()
    assert manager.apply(GAINS, OUTPUT, options).applied
    managed = (config / apo.MANAGED_FILENAME).read_bytes()
    parent.write_text(broken)
    assert not manager.apply(GAINS, OUTPUT, options).applied
    assert parent.read_text() == broken
    assert (config / apo.MANAGED_FILENAME).read_bytes() == managed
    parent.write_text(BLOCK)
    assert manager.apply(GAINS, OUTPUT, options).applied


def test_successful_discovery_is_refreshed_when_config_path_changes(tmp_path: Path) -> None:
    registry = Registry(tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.txt").write_text(BLOCK)
    manager = EqualizerApoConfigManager(registry)
    options = MediaEqualizerApoConfig()
    assert manager.apply(GAINS, OUTPUT, options).applied
    moved = tmp_path / "new-config"
    registry.values["ConfigPath"] = str(moved)
    assert not manager.apply(GAINS, OUTPUT, options).applied
    moved.mkdir()
    (moved / "config.txt").write_text(BLOCK)
    assert manager.apply(GAINS, OUTPUT, options).applied
    assert (moved / apo.MANAGED_FILENAME).is_file()


def test_target_change_invalidates_payload_even_if_validation_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = Registry(tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.txt").write_text(BLOCK)
    manager = EqualizerApoConfigManager(registry)
    options = MediaEqualizerApoConfig()
    assert manager.apply(GAINS, OUTPUT, options).applied
    moved = tmp_path / "new-config"
    moved.mkdir()
    parent = moved / "config.txt"
    parent.write_text(BLOCK)
    registry.values["ConfigPath"] = str(moved)
    read = apo.read_config_text
    failed = False

    def fail_once(path: Path) -> apo.ConfigText:
        nonlocal failed
        if path == parent and not failed:
            failed = True
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "Owned malformed configuration")
        return read(path)

    monkeypatch.setattr(apo, "read_config_text", fail_once)
    with pytest.raises(UnicodeDecodeError):
        manager.apply(GAINS, OUTPUT, options)
    assert manager.apply(GAINS, OUTPUT, options).applied
    assert (moved / apo.MANAGED_FILENAME).is_file()
    assert registry.reads == 3


@pytest.mark.parametrize("error", [PermissionError, OSError])
def test_transient_parent_read_error_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: type[OSError]
) -> None:
    registry = Registry(tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    parent = config / "config.txt"
    parent.write_text(BLOCK)
    read = apo.read_config_text
    reads = 0

    def fail_once(path: Path) -> apo.ConfigText:
        nonlocal reads
        reads += 1
        if reads == 1:
            raise error("Owned transient read failure")
        return read(path)

    monkeypatch.setattr(apo, "read_config_text", fail_once)
    manager = EqualizerApoConfigManager(registry)
    options = MediaEqualizerApoConfig()
    assert not manager.apply(GAINS, OUTPUT, options).applied
    assert manager.apply(GAINS, OUTPUT, options).applied
    assert reads == 2


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "cp1252"])
def test_parent_write_retry_preserves_original_backup_encoding_and_custom_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, encoding: str
) -> None:
    registry = Registry(tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    parent = config / "config.txt"
    original_text = "# Café — owned config\r\nFilter 1: ON PK Fc 100 Hz Gain 1 dB Q 1\r\n"
    original = original_text.encode(encoding)
    parent.write_bytes(original)
    write = apo.atomic_write_text
    denied = False

    def fail_once(path: Path, text: str, encoding: str = "utf-8") -> None:
        nonlocal denied
        if path == parent and not denied:
            denied = True
            raise PermissionError("Owned transient write failure")
        write(path, text, encoding)

    monkeypatch.setattr(apo, "atomic_write_text", fail_once)
    manager = EqualizerApoConfigManager(registry)
    options = MediaEqualizerApoConfig(manage_include=True)
    assert not manager.apply(GAINS, OUTPUT, options).applied
    assert parent.read_bytes() == original
    assert (config / apo.BACKUP_FILENAME).read_bytes() == original
    result = manager.apply(GAINS, OUTPUT, options)
    assert result.applied and result.external_filters
    updated = parent.read_bytes().decode(encoding)
    assert updated.startswith(original_text)
    assert updated.count(BEGIN_MARKER) == updated.count(END_MARKER) == 1
    assert updated.count(INCLUDE_LINE) == 1
    assert "\n" not in updated.replace("\r\n", "")
    assert (config / apo.BACKUP_FILENAME).read_bytes() == original


def test_stock_diagnostics_do_not_hide_later_external_filters(tmp_path: Path) -> None:
    registry = Registry(tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    parent = config / "config.txt"
    stock = (
        "Preamp: -6 dB\nInclude: example.txt\nGraphicEQ: "
        + "; ".join(
            f"{frequency} 0"
            for frequency in (25, 40, 63, 100, 160, 250, 400, 630, 1000, 1600, 2500, 4000, 6300, 10000, 16000)
        )
        + "\n"
    )
    parent.write_text(stock)
    manager = EqualizerApoConfigManager(registry)
    options = MediaEqualizerApoConfig(manage_include=True)
    first = manager.apply(GAINS, OUTPUT, options)
    assert first.applied and "stock config neutralized" in first.status
    backup = (config / apo.BACKUP_FILENAME).read_bytes()
    assert backup == stock.replace("\n", "\r\n").encode()
    custom = "Filter 1: ON PK Fc 100 Hz Gain 1 dB Q 1\n" + BLOCK
    parent.write_text(custom)
    later = manager.apply(GAINS, OUTPUT, options)
    assert later.applied and later.external_filters
    assert "existing filters detected" in later.status
    assert parent.read_text() == custom
    assert (config / apo.BACKUP_FILENAME).read_bytes() == backup
