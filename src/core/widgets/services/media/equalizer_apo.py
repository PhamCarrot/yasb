"""Optional Equalizer APO backend for Media Widget V2."""

from __future__ import annotations

import asyncio
import base64
import codecs
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any, ClassVar

from PyQt6.QtCore import QObject

from core.widgets.services.media.audio_device import DefaultAudioOutputService
from core.widgets.services.media.native_api import NativeParameters
from core.widgets.services.media.native_route import (
    NativeApoRoute,
    NativeAudioState,
    NativeCommit,
    NativeObservation,
    NativeRouteOptions,
    canonical,
    native_parameters,
)

try:
    import winreg
except ImportError:
    winreg = None
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QApplication

from core.utils.qobject import is_valid_qobject
from core.widgets.services.media.audio_device import AudioOutputState

logger = logging.getLogger("EqualizerAPO")

FREQUENCIES = (31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
MANAGED_FILENAME = "yasb-media-v2-eq.txt"
BACKUP_FILENAME = "config.txt.yasb-backup"
BEGIN_MARKER = "# BEGIN YASB MEDIA V2 EQ"
END_MARKER = "# END YASB MEDIA V2 EQ"
INCLUDE_LINE = f"Include: {MANAGED_FILENAME}"
_REGISTRY_PATH = r"SOFTWARE\EqualizerAPO"
_GUID_RE = re.compile(r"^\{[0-9a-fA-F-]{36}\}$")
_INCLUDE_RE = re.compile(r"^\s*Include\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_FILTER_RE = re.compile(
    r"^\s*(?:Preamp|GraphicEQ|Filter(?:\s+\d+)?|Convolution|Copy|Delay|LoudnessCorrection)\s*:",
    re.IGNORECASE | re.MULTILINE,
)
_MANAGED_BLOCK_RE = re.compile(rf"(?ms)^\s*{re.escape(BEGIN_MARKER)}\s*$.*?^\s*{re.escape(END_MARKER)}\s*$")


@dataclass(frozen=True)
class EqualizerApoInstallation:
    install_path: Path
    config_path: Path


@dataclass(frozen=True)
class ConfigText:
    text: str
    encoding: str
    newline: str


@dataclass(frozen=True)
class ApoApplyResult:
    status: str
    detail: str = ""
    applied: bool = False
    external_filters: bool = False
    state: ApoAppliedState | None = None
    native_parameters: NativeParameters | None = None


@dataclass(frozen=True)
class ApoWriteOptions:
    auto_preamp: bool
    preamp_db: float
    manage_include: bool
    processor: str = "graphic_eq"
    native: NativeRouteOptions | None = None

    @classmethod
    def snapshot(cls, options: Any, *, native_profile: str | None = None) -> ApoWriteOptions:
        processor = str(getattr(options, "processor", "graphic_eq"))
        native = getattr(options, "native", None)
        if processor == "native" and native is None:
            from core.config import get_config_dir

            native = NativeRouteOptions(
                canonical(native_profile if native_profile is not None else get_config_dir()),
                str(getattr(options, "native_library", "")),
                str(getattr(options, "native_sha256", "")).lower(),
            )
        return cls(bool(options.auto_preamp), float(options.preamp_db), bool(options.manage_include), processor, native)


@dataclass(frozen=True)
class ApoAppliedState:
    target: str
    revision: int
    gains: tuple[float, ...]
    output: AudioOutputState
    options: ApoWriteOptions
    audio: NativeAudioState = NativeAudioState()


@dataclass(frozen=True)
class ApoWriteRequest:
    generation: int
    intent_revision: int
    gains: tuple[float, ...]
    output: AudioOutputState
    options: ApoWriteOptions
    manager: EqualizerApoConfigManager
    target: str
    output_service: DefaultAudioOutputService
    audio: NativeAudioState = NativeAudioState()
    restore: bool = False


class ExistingConfigKind(StrEnum):
    EMPTY = "empty"
    NEUTRAL = "neutral"
    STOCK = "stock"
    CUSTOM = "custom"
    PEACE = "peace"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ExistingConfigAnalysis:
    kind: ExistingConfigKind
    external_filters: bool
    peace_detected: bool = False
    stock_lines: tuple[int, ...] = ()
    reason: str = ""


_STOCK_GRAPHIC_FREQS = (25, 40, 63, 100, 160, 250, 400, 630, 1000, 1600, 2500, 4000, 6300, 10000, 16000)
_PREAMP_RE = re.compile(r"^\s*Preamp\s*:\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*dB\s*$", re.IGNORECASE)
_GRAPHIC_EQ_RE = re.compile(r"^\s*GraphicEQ\s*:\s*(.*?)\s*$", re.IGNORECASE)
_INCLUDE_LINE_RE = re.compile(r"^\s*Include\s*:\s*(.*?)\s*$", re.IGNORECASE)
_KNOWN_PROCESSING_RE = re.compile(
    r"^\s*(?:Preamp|GraphicEQ|Filter(?:\s+\d+)?|Convolution|Copy|Delay|LoudnessCorrection|Include|Channel|Device|Eval)\s*:",
    re.IGNORECASE,
)


def discover_equalizer_apo_details(registry: Any = winreg) -> tuple[EqualizerApoInstallation | None, str]:
    """Return installation plus a stable discovery status for UI diagnostics."""
    if registry is None:
        return None, "not_installed"
    access = registry.KEY_READ
    if hasattr(registry, "KEY_WOW64_64KEY"):
        access |= registry.KEY_WOW64_64KEY
    try:
        key_context = registry.OpenKey(registry.HKEY_LOCAL_MACHINE, _REGISTRY_PATH, 0, access)
    except FileNotFoundError, OSError:
        return None, "not_installed"
    with key_context as key:
        try:
            install_path = str(registry.QueryValueEx(key, "InstallPath")[0] or "").strip()
        except FileNotFoundError, OSError:
            install_path = ""
        try:
            config_path = str(registry.QueryValueEx(key, "ConfigPath")[0] or "").strip()
        except FileNotFoundError, OSError:
            config_path = ""
    if not install_path:
        return None, "missing_install_path"
    if not config_path:
        return None, "missing_config_path"
    return EqualizerApoInstallation(
        Path(os.path.expandvars(install_path)),
        Path(os.path.expandvars(config_path)),
    ), "ready"


def validate_gains(gains: Sequence[float]) -> tuple[float, ...]:
    values = tuple(float(value) for value in gains)
    if len(values) != len(FREQUENCIES):
        raise ValueError("Equalizer APO requires exactly 10 gains")
    if any(value < -12.0 or value > 12.0 for value in values):
        raise ValueError("Equalizer APO gains must be between -12 and +12 dB")
    return values


def automatic_preamp(gains: Sequence[float]) -> float:
    values = validate_gains(gains)
    return -max(0.0, max(values))


def _format_db(value: float) -> str:
    rounded = round(float(value), 2)
    if abs(rounded - round(rounded)) < 1e-9:
        return str(int(round(rounded)))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def build_device_selector(endpoint_guid: str) -> str:
    guid = (endpoint_guid or "").strip()
    if not _GUID_RE.fullmatch(guid):
        raise ValueError("A valid playback endpoint GUID is required")
    return f"Device: {guid}"


def build_graphic_eq(gains: Sequence[float]) -> str:
    values = validate_gains(gains)
    pairs = "; ".join(f"{frequency} {_format_db(gain)}" for frequency, gain in zip(FREQUENCIES, values))
    return f"GraphicEQ: {pairs}"


def render_managed_config(
    gains: Sequence[float],
    endpoint_guid: str,
    *,
    auto_preamp: bool = True,
    preamp_db: float = 0.0,
    enabled: bool = True,
) -> str:
    values = validate_gains(gains)
    if not enabled:
        values = (0.0,) * len(FREQUENCIES)
    preamp = automatic_preamp(values) if auto_preamp else float(preamp_db)
    lines = [
        "# Media Widget V2 managed Equalizer APO configuration.",
        "# Changes may be overwritten while YASB is running.",
        "",
        build_device_selector(endpoint_guid),
        "Channel: all",
        "",
        f"Preamp: {_format_db(preamp)} dB",
        build_graphic_eq(values),
        "",
        "# Restore the default selector for any user config parsed after this include.",
        "Device: all",
        "",
    ]
    return "\n".join(lines)


def render_native_config(route: NativeApoRoute, commit: NativeCommit, endpoint_guid: str) -> str:
    chunk = base64.b64encode(commit.bootstrap.pack()).decode("ascii")
    return "\n".join(
        [
            "# Media Widget V2 managed Equalizer APO configuration.",
            "# Native route bootstrap; current settings live in the selected YASB profile.",
            "",
            build_device_selector(endpoint_guid),
            "Channel: L R",
            "",
            f'VSTPlugin: Library "{route.api.path}" ChunkData "{chunk}"',
            "",
            "# Restore the default selector for any user config parsed after this include.",
            "Device: all",
            "Channel: all",
            "",
        ]
    )


def _include_basename(value: str) -> str:
    target = value.strip().strip('"').replace("\\", "/")
    return target.rsplit("/", 1)[-1].casefold()


def _parse_graphic_eq(line: str) -> tuple[tuple[float, float], ...] | None:
    match = _GRAPHIC_EQ_RE.fullmatch(line)
    if not match:
        return None
    pairs: list[tuple[float, float]] = []
    try:
        for item in match.group(1).split(";"):
            fields = item.split()
            if len(fields) != 2:
                return None
            pairs.append((float(fields[0]), float(fields[1])))
    except ValueError:
        return None
    return tuple(pairs)


def _active_config_lines(config_text: str) -> list[tuple[int, str]]:
    """Return active non-comment lines outside the managed YASB block."""
    active: list[tuple[int, str]] = []
    in_managed_block = False
    for index, raw in enumerate((config_text or "").splitlines()):
        stripped = raw.strip()
        if stripped == BEGIN_MARKER:
            in_managed_block = True
            continue
        if in_managed_block:
            if stripped == END_MARKER:
                in_managed_block = False
            continue
        if not stripped or stripped.startswith("#"):
            continue
        active.append((index, stripped))
    return active


def _is_neutral_command(line: str) -> bool:
    preamp = _PREAMP_RE.fullmatch(line)
    if preamp:
        return abs(float(preamp.group(1))) < 1e-9
    graphic = _parse_graphic_eq(line)
    return graphic is not None and bool(graphic) and all(abs(gain) < 1e-9 for _frequency, gain in graphic)


def _is_stock_graphic_eq(line: str) -> bool:
    graphic = _parse_graphic_eq(line)
    if graphic is None or len(graphic) != len(_STOCK_GRAPHIC_FREQS):
        return False
    frequencies = tuple(round(frequency) for frequency, _gain in graphic)
    return (
        frequencies == _STOCK_GRAPHIC_FREQS
        and all(abs(frequency - round(frequency)) < 1e-9 for frequency, _gain in graphic)
        and all(abs(gain) < 1e-9 for _frequency, gain in graphic)
    )


def analyze_existing_config(config_text: str) -> ExistingConfigAnalysis:
    """Conservatively classify the parent Equalizer APO configuration.

    STOCK is intentionally narrow: the entire active config must be the known
    Equalizer APO sample chain observed in 1.4.x (preamp -6 dB, example.txt,
    then the stock 15-band all-zero GraphicEQ). Any additional active command
    prevents automatic neutralization.
    """
    active = _active_config_lines(config_text)
    if not active:
        return ExistingConfigAnalysis(ExistingConfigKind.EMPTY, False, reason="No active Equalizer APO commands.")

    include_names: list[str] = []
    for _index, line in active:
        match = _INCLUDE_LINE_RE.fullmatch(line)
        if match:
            include_names.append(_include_basename(match.group(1)))
    peace = any(name.startswith("peace") for name in include_names)
    if peace:
        return ExistingConfigAnalysis(
            ExistingConfigKind.PEACE,
            True,
            peace_detected=True,
            reason="A Peace-managed Include is active.",
        )

    if len(active) == 3:
        preamp = _PREAMP_RE.fullmatch(active[0][1])
        include = _INCLUDE_LINE_RE.fullmatch(active[1][1])
        if (
            preamp
            and abs(float(preamp.group(1)) + 6.0) < 1e-9
            and include
            and _include_basename(include.group(1)) == "example.txt"
            and _is_stock_graphic_eq(active[2][1])
        ):
            return ExistingConfigAnalysis(
                ExistingConfigKind.STOCK,
                True,
                stock_lines=tuple(index for index, _line in active),
                reason="Known Equalizer APO stock/sample processing chain.",
            )

    if all(_is_neutral_command(line) for _index, line in active):
        return ExistingConfigAnalysis(
            ExistingConfigKind.NEUTRAL,
            False,
            reason="Only neutral preamp/GraphicEQ commands are active.",
        )

    if all(_KNOWN_PROCESSING_RE.match(line) for _index, line in active):
        return ExistingConfigAnalysis(
            ExistingConfigKind.CUSTOM,
            True,
            reason="Existing Equalizer APO processing commands or Includes are active.",
        )

    return ExistingConfigAnalysis(
        ExistingConfigKind.UNKNOWN,
        True,
        reason="The existing Equalizer APO configuration contains unrecognized active commands.",
    )


def neutralize_stock_config(config_text: str, analysis: ExistingConfigAnalysis) -> str:
    """Comment only the three lines proven by analysis to be the stock chain."""
    if analysis.kind != ExistingConfigKind.STOCK or len(analysis.stock_lines) != 3:
        raise ValueError("Only a confidently recognized stock Equalizer APO config can be neutralized")
    stock_lines = set(analysis.stock_lines)
    rewritten: list[str] = []
    for index, raw in enumerate(config_text.splitlines(keepends=True)):
        if index not in stock_lines:
            rewritten.append(raw)
            continue
        content = raw.rstrip("\r\n")
        ending = raw[len(content) :]
        indent = content[: len(content) - len(content.lstrip())]
        command = content[len(indent) :]
        rewritten.append(f"{indent}# YASB neutralized stock: {command}{ending}")
    return "".join(rewritten)


def insert_managed_include(config_text: str, newline: str = "\n") -> tuple[str, bool]:
    """Install one managed block, upgrading one bare YASB Include when safe."""
    starts = config_text.count(BEGIN_MARKER)
    ends = config_text.count(END_MARKER)
    if starts == 1 and ends == 1 and _MANAGED_BLOCK_RE.search(config_text):
        return config_text, False
    if starts or ends:
        raise ValueError("Equalizer APO config contains an incomplete or duplicate YASB marker block")

    lines = config_text.splitlines(keepends=True)
    bare_lines: list[int] = []
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        include = _INCLUDE_LINE_RE.fullmatch(stripped)
        if include and _include_basename(include.group(1)) == MANAGED_FILENAME.casefold():
            bare_lines.append(index)
    if len(bare_lines) > 1:
        raise ValueError("Equalizer APO config contains multiple bare YASB Include lines")

    if len(bare_lines) == 1:
        index = bare_lines[0]
        raw = lines[index]
        content = raw.rstrip("\r\n")
        line_ending = raw[len(content) :] or newline
        indent = content[: len(content) - len(content.lstrip())]
        lines[index] = (
            line_ending.join(
                (
                    indent + BEGIN_MARKER,
                    indent + INCLUDE_LINE,
                    indent + END_MARKER,
                )
            )
            + line_ending
        )
        return "".join(lines), True

    block = newline.join((BEGIN_MARKER, INCLUDE_LINE, END_MARKER))
    prefix = config_text
    if prefix and not prefix.endswith(("\n", "\r")):
        prefix += newline
    if prefix:
        prefix += newline
    return prefix + block + newline, True


def read_config_text(path: Path) -> ConfigText:
    payload = path.read_bytes()
    if payload.startswith(codecs.BOM_UTF16_LE) or payload.startswith(codecs.BOM_UTF16_BE):
        encoding = "utf-16"
    elif payload.startswith(codecs.BOM_UTF8):
        encoding = "utf-8-sig"
    else:
        encoding = "utf-8"
    try:
        text = payload.decode(encoding)
    except UnicodeDecodeError:
        encoding = "cp1252"
        text = payload.decode(encoding)
    newline = "\r\n" if "\r\n" in text else "\n"
    return ConfigText(text, encoding, newline)


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        try:
            temporary_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


class EqualizerApoConfigManager:
    """Registry discovery and the small slice of Equalizer APO config YASB owns."""

    # Include/backup/managed writes and mutable attempt diagnostics form one
    # transaction, including calls made outside the Qt writer.
    _write_lock: ClassVar[threading.RLock] = threading.RLock()
    _revision: ClassVar[int] = 0
    _states: ClassVar[dict[str, ApoAppliedState]] = {}
    _listeners: ClassVar[list[Callable[[ApoAppliedState], None]]] = []

    @classmethod
    def subscribe(cls, callback: Callable[[ApoAppliedState], None]) -> None:
        cls._listeners.append(callback)

    @classmethod
    def unsubscribe(cls, callback: Callable[[ApoAppliedState], None]) -> None:
        cls._listeners.remove(callback)

    @classmethod
    def applied_for(cls, key: str) -> ApoAppliedState | None:
        # Immutable snapshots can be read without waiting on file I/O.
        return cls._states.get(key)

    def __init__(self, registry: Any = winreg) -> None:
        self._registry = registry
        self._installation_checked = False
        self._installation: EqualizerApoInstallation | None = None
        self._discovery_status = "unknown"
        self._external_filters = False
        self._analysis = ExistingConfigAnalysis(ExistingConfigKind.UNKNOWN, False)
        self._stock_neutralized = False

    def target_key(self) -> str:
        installation, _status = discover_equalizer_apo_details(self._registry)
        if installation is not None:
            try:
                return os.path.normcase(str((installation.config_path / MANAGED_FILENAME).resolve()))
            except OSError, RuntimeError, ValueError:
                pass
        return f"unresolved:{id(self._registry)}"

    @property
    def installation(self) -> EqualizerApoInstallation | None:
        if not self._installation_checked:
            self._installation_checked = True
            self._installation, self._discovery_status = discover_equalizer_apo_details(self._registry)
        return self._installation

    @property
    def external_filters(self) -> bool:
        return self._external_filters

    def _prepare_parent(self, manage_include: bool) -> ApoApplyResult | None:
        self._external_filters = False
        self._analysis = ExistingConfigAnalysis(ExistingConfigKind.UNKNOWN, False)
        self._stock_neutralized = False
        installation = self.installation
        if installation is None:
            if self._discovery_status == "missing_install_path":
                return ApoApplyResult(
                    "Equalizer APO — setup required",
                    "Equalizer APO registry key exists but InstallPath is missing.",
                )
            if self._discovery_status == "missing_config_path":
                return ApoApplyResult(
                    "Equalizer APO — setup required",
                    "Equalizer APO registry key exists but ConfigPath is missing.",
                )
            return ApoApplyResult("Visual only — Equalizer APO not installed")

        config_path = installation.config_path
        if not config_path.is_dir():
            return ApoApplyResult("Equalizer APO — setup required", f"ConfigPath does not exist: {config_path}")
        parent = config_path / "config.txt"
        if not parent.is_file():
            return ApoApplyResult("Equalizer APO — setup required", f"Missing {parent}")
        try:
            config = read_config_text(parent)
        except PermissionError as error:
            return ApoApplyResult("Equalizer APO — write access denied", str(error))
        except OSError as error:
            return ApoApplyResult("Equalizer APO — setup required", str(error))

        analysis = analyze_existing_config(config.text)
        self._analysis = analysis
        self._external_filters = analysis.external_filters
        starts = config.text.count(BEGIN_MARKER)
        ends = config.text.count(END_MARKER)
        marker_valid = starts == 1 and ends == 1 and _MANAGED_BLOCK_RE.search(config.text) is not None

        if (starts or ends) and not marker_valid:
            return ApoApplyResult(
                "Equalizer APO — setup required",
                "The existing YASB marker block is incomplete or duplicated; fix config.txt manually.",
                external_filters=self._external_filters,
            )

        # A correct marker installed by an older YASB build is already usable.
        # With manage_include enabled we may still neutralize the *known stock*
        # sample chain once, after preserving the pre-YASB parent config.
        if marker_valid and (not manage_include or analysis.kind != ExistingConfigKind.STOCK):
            return None

        if not marker_valid and not manage_include:
            return ApoApplyResult(
                "Equalizer APO — setup required",
                f"Add these lines to {parent}:\n{BEGIN_MARKER}\n{INCLUDE_LINE}\n{END_MARKER}",
                external_filters=self._external_filters,
            )

        backup = config_path / BACKUP_FILENAME
        try:
            if not backup.exists():
                shutil.copy2(parent, backup)

            updated = config.text
            changed = False
            if analysis.kind == ExistingConfigKind.STOCK:
                updated = neutralize_stock_config(updated, analysis)
                changed = updated != config.text
                self._stock_neutralized = changed

            if not marker_valid:
                updated, include_changed = insert_managed_include(updated, config.newline)
                changed = changed or include_changed

            if changed:
                atomic_write_text(parent, updated, config.encoding)

            verified = read_config_text(parent).text
            if verified.count(BEGIN_MARKER) != 1 or verified.count(END_MARKER) != 1:
                raise OSError("managed Include marker verification failed")
            _verified_again, include_changed = insert_managed_include(verified, config.newline)
            if include_changed:
                raise OSError("managed Include verification failed")

            self._analysis = analyze_existing_config(verified)
            self._external_filters = self._analysis.external_filters
            if self._stock_neutralized:
                self._external_filters = False
                logger.info("Equalizer APO stock/sample config neutralized after backup")
            else:
                logger.info("Equalizer APO managed include installed")
        except PermissionError as error:
            return ApoApplyResult(
                "Equalizer APO — write access denied",
                f"Could not update {parent}. Add manually: {INCLUDE_LINE}. {error}",
                external_filters=self._external_filters,
            )
        except (OSError, ValueError) as error:
            return ApoApplyResult(
                "Equalizer APO — setup required",
                f"Could not update {parent}: {error}",
                external_filters=self._external_filters,
            )
        return None

    def apply(
        self,
        gains: Sequence[float],
        output: AudioOutputState,
        apo_options: Any,
        *,
        enabled: bool = True,
        native: NativeApoRoute | None = None,
        audio: NativeAudioState = NativeAudioState(),
        generation: int = 0,
        restore: bool = False,
    ) -> ApoApplyResult:
        with self._write_lock:
            options = ApoWriteOptions.snapshot(apo_options)
            result = self._apply(
                gains,
                output,
                options,
                enabled=enabled,
                native=native,
                audio=audio,
                generation=generation,
                restore=restore,
            )
            if result.applied:
                assert self._installation is not None
                key = os.path.normcase(str((self._installation.config_path / MANAGED_FILENAME).resolve()))
                EqualizerApoConfigManager._revision += 1
                state = ApoAppliedState(
                    key,
                    self._revision,
                    result.native_parameters.gains
                    if result.native_parameters is not None
                    else validate_gains(gains)
                    if enabled
                    else (0.0,) * len(FREQUENCIES),
                    output,
                    options,
                    NativeAudioState.from_parameters(result.native_parameters)
                    if result.native_parameters is not None
                    else audio,
                )
                self._states[key] = state
                result = replace(result, state=state)
            listeners = tuple(self._listeners)
        if result.state is not None:
            for listener in listeners:
                listener(result.state)
        return result

    def _apply(
        self,
        gains: Sequence[float],
        output: AudioOutputState,
        apo_options: ApoWriteOptions,
        *,
        enabled: bool = True,
        native: NativeApoRoute | None = None,
        audio: NativeAudioState = NativeAudioState(),
        generation: int = 0,
        restore: bool = False,
    ) -> ApoApplyResult:
        commit: NativeCommit | None = None
        if apo_options.processor == "native":
            try:
                # Validate everything before parent preparation can change files.
                build_device_selector(output.endpoint_guid)
                if native is None or native.target != self.target_key() or native.options != apo_options.native:
                    raise ValueError("Native DSP needs a validated route owned by the shared writer")
                values = validate_gains(gains) if enabled else (0.0,) * len(FREQUENCIES)
                parameters = native_parameters(values, audio, apo_options.auto_preamp, apo_options.preamp_db)
                commit = native.prepare(
                    parameters, output.endpoint_guid, generation, restore=restore, auto_preamp=apo_options.auto_preamp
                )
            except (OSError, ValueError, RuntimeError) as error:
                return ApoApplyResult("Native DSP unavailable", str(error))
        elif apo_options.processor != "graphic_eq":
            return ApoApplyResult("Unknown audio processor", apo_options.processor)
        # Discovery and parent readiness belong to this attempt, not the lifetime
        # of a popup/manager. A repaired or externally changed setup must be read.
        self._installation_checked = False
        installation = self.installation
        setup = self._prepare_parent(bool(apo_options.manage_include))
        if setup is not None:
            return setup
        if installation is None:
            return ApoApplyResult("Visual only — Equalizer APO not installed")
        if not output.endpoint_guid:
            return ApoApplyResult(
                "Equalizer APO — output unavailable",
                "Windows did not provide a default multimedia render endpoint.",
                external_filters=self._external_filters,
            )
        try:
            if commit is not None:
                assert native is not None
                payload = render_native_config(native, commit, output.endpoint_guid)
            else:
                payload = render_managed_config(
                    gains,
                    output.endpoint_guid,
                    auto_preamp=bool(apo_options.auto_preamp),
                    preamp_db=float(apo_options.preamp_db),
                    enabled=enabled,
                )
            target = installation.config_path / MANAGED_FILENAME
            try:
                current = target.read_bytes()
            except FileNotFoundError:
                current = b""
            if commit is not None:
                assert native is not None
                backup = target.with_suffix(target.suffix + ".yasb-native-backup")
                if current and not backup.exists():
                    shutil.copy2(target, backup)
                native.persist(commit)
            if payload.encode("utf-8") != current:
                atomic_write_text(target, payload, "utf-8")
                logger.debug("Equalizer APO managed EQ updated for %s", output.endpoint_guid)
        except PermissionError as error:
            return ApoApplyResult(
                "Equalizer APO — write access denied",
                str(error),
                external_filters=self._external_filters,
            )
        except (OSError, ValueError) as error:
            return ApoApplyResult(
                "Equalizer APO — setup required",
                str(error),
                external_filters=self._external_filters,
            )

        if commit is not None:
            assert native is not None
            native.publish(commit)
            return ApoApplyResult(
                "Saved; native processing unconfirmed",
                "Settings and route persisted. Resident processing is reported separately.",
                True,
                self._external_filters,
                native_parameters=commit.parameters,
            )
        if self._stock_neutralized:
            return ApoApplyResult(
                "Equalizer APO — stock config neutralized",
                "The recognized Equalizer APO stock/sample processing was commented after backup; Media Widget V2 EQ is applied.",
                True,
                False,
            )
        if self._analysis.kind == ExistingConfigKind.PEACE:
            return ApoApplyResult(
                "Equalizer APO — Peace detected",
                "Media Widget V2 EQ is applied without modifying Peace; both filter chains may stack.",
                True,
                True,
            )
        if self._external_filters:
            detail = (
                "The recognized stock/sample filters remain enabled and may stack with Media Widget V2 EQ."
                if self._analysis.kind == ExistingConfigKind.STOCK
                else "Media Widget V2 EQ is active, but existing Equalizer APO filters are also enabled and may stack with it."
            )
            return ApoApplyResult(
                "Equalizer APO — existing filters detected",
                detail,
                True,
                True,
            )
        return ApoApplyResult("", "", True, False)

    def open_configurator(self) -> bool:
        installation = self.installation
        if installation is None:
            return False
        candidates = (installation.install_path / "Configurator.exe", installation.install_path / "Editor.exe")
        executable = next((path for path in candidates if path.is_file()), None)
        if executable is None:
            return False
        subprocess.Popen([str(executable)], shell=False)
        return True


@dataclass
class _ApoTarget:
    intent: ApoWriteRequest | None = None
    applied: ApoAppliedState | None = None
    completed: int = 0
    failed: bool = False
    status: str = ""
    detail: str = ""
    draft_owner: object | None = None


class EqualizerApoWriter(QObject):
    """Application-owned scheduler with one state owner per canonical file.

    A single executor also serializes distinct targets. There are few tiny config
    files; retaining one worker is simpler than allocating a pool per popup/file.
    """

    changed = pyqtSignal(str)
    redirected = pyqtSignal(str, str)
    _job_finished = pyqtSignal(object, object)
    _state_finished = pyqtSignal(object)
    _shared: ClassVar[EqualizerApoWriter | None] = None
    _closing: ClassVar[bool] = False
    _drain_task: ClassVar[asyncio.Task[None] | None] = None

    @classmethod
    def shared(cls) -> EqualizerApoWriter:
        if cls._shared is None or (not cls._closing and (not is_valid_qobject(cls._shared) or cls._shared._closed)):
            cls._shared = cls()
        return cls._shared

    @classmethod
    def shared_instance(cls) -> EqualizerApoWriter | None:
        return cls._shared

    @classmethod
    async def aclose_shared(cls) -> None:
        task = cls._drain_task
        if task is None or task.done():
            writer = cls._shared
            if writer is None:
                return
            cls._closing = True
            writer.shutdown()
            task = asyncio.create_task(cls._drain_shared(writer))
            cls._drain_task = task
        await asyncio.shield(task)

    @classmethod
    async def _drain_shared(cls, writer: EqualizerApoWriter) -> None:
        await asyncio.to_thread(writer._executor.shutdown, wait=True, cancel_futures=False)
        writer._running = None
        if cls._shared is writer:
            cls._shared = None
        if cls._drain_task is asyncio.current_task():
            cls._drain_task = None
        cls._closing = False

    def __init__(self) -> None:
        super().__init__(QApplication.instance())
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="yasb-equalizer-apo")
        self._targets: dict[str, _ApoTarget] = {}
        self._native_routes: dict[str, NativeApoRoute] = {}
        self._pending: OrderedDict[str, ApoWriteRequest] = OrderedDict()
        self._running: ApoWriteRequest | None = None
        self._outputs: dict[DefaultAudioOutputService, Callable[[AudioOutputState], None]] = {}
        self._generation = 0
        self._closed = False
        self._job_finished.connect(self._on_job_finished)
        self._state_finished.connect(self._on_state)
        EqualizerApoConfigManager.subscribe(self._post_state)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    @property
    def closed(self) -> bool:
        return self._closed

    def target(self, key: str) -> _ApoTarget:
        if key not in self._targets:
            self._targets[key] = _ApoTarget(applied=EqualizerApoConfigManager.applied_for(key))
        return self._targets[key]

    def _post_state(self, state: ApoAppliedState) -> None:
        try:
            self._state_finished.emit(state)
        except RuntimeError:
            pass

    def claim_draft(self, key: str, token: object, *, notify: bool = True) -> bool:
        target = self.target(key)
        if self._closed or target.draft_owner not in (None, token):
            return False
        target.draft_owner = token
        if notify:
            self.changed.emit(key)
        return True

    def release_draft(self, key: str, token: object) -> None:
        target = self.target(key)
        if target.draft_owner is token:
            target.draft_owner = None
            if not self._closed:
                self.changed.emit(key)

    def _on_state(self, state: ApoAppliedState) -> None:
        if self._closed:
            return
        target = self.target(state.target)
        if target.applied is None or state.revision > target.applied.revision:
            target.applied = state
            self.changed.emit(state.target)

    def queue(
        self,
        key: str,
        gains: tuple[float, ...],
        output: DefaultAudioOutputService,
        manager: EqualizerApoConfigManager,
        options: ApoWriteOptions,
        *,
        draft_target: str | None = None,
        draft_token: object | None = None,
        audio: NativeAudioState | None = None,
        restore: bool = False,
    ) -> bool:
        if self._closed:
            return False
        for stale, callback in tuple(self._outputs.items()):
            if type(stale) is not DefaultAudioOutputService or not stale.closed:
                continue
            try:
                stale.default_output_changed.disconnect(callback)
            except RuntimeError, TypeError:
                pass
            self._outputs.pop(stale, None)
        target = self.target(key)
        if (draft_target is not None or draft_token is not None) and (
            draft_target != key or draft_token is None or target.draft_owner is not draft_token
        ):
            return False
        if target.intent is not None and target.intent.restore and not restore:
            return False  # Restoration is an authoritative-base barrier, not a placeholder intent to edit.
        owner_options = (
            target.intent.options
            if target.intent is not None
            else target.applied.options
            if target.applied is not None
            else None
        )
        if owner_options is not None and (owner_options.processor, owner_options.native) != (
            options.processor,
            options.native,
        ):
            return False
        # Dynamic processing retains the committed manual curve, but manual
        # edits cannot alter it until an explicit Audio action disables learning.
        current_audio = (
            target.intent.audio
            if target.intent is not None
            else target.applied.audio
            if target.applied is not None
            else NativeAudioState()
        )
        if options.processor == "native" and audio is None and current_audio.adaptive and not restore:
            return False
        # Audio actions operate on committed EQ and do not consume its draft lease.
        if audio is None and target.draft_owner is not None and target.draft_owner is not draft_token:
            return False
        if audio is None:
            audio = (
                target.intent.audio
                if target.intent is not None
                else target.applied.audio
                if target.applied is not None
                else NativeAudioState()
            )
        else:
            if options.processor != "native":
                return False
            audio.parameters(gains, 0).pack()
            gains = (
                target.intent.gains
                if target.intent is not None
                else target.applied.gains
                if target.applied is not None
                else gains
            )
        if output not in self._outputs:

            def changed(state: AudioOutputState) -> None:
                self._retarget(output, state)

            self._outputs[output] = changed
            output.default_output_changed.connect(changed)
        self._generation += 1
        request = ApoWriteRequest(
            self._generation, self._generation, gains, output.state, options, manager, key, output, audio, restore
        )
        if draft_target is not None:
            target.draft_owner = None
        self._enqueue(request)
        return True

    def _enqueue(self, request: ApoWriteRequest) -> None:
        target = self.target(request.target)
        if target.intent is not None and target.intent.intent_revision > request.intent_revision:
            return  # A notification may have synchronously committed newer intent.
        request = replace(request, output=request.output_service.state)
        target.intent = request
        target.failed = False
        target.status, target.detail = "Applying…", ""
        self._pending[request.target] = request
        self._pending.move_to_end(request.target)
        self.changed.emit(request.target)
        self._submit_latest()

    def _retarget(self, output: DefaultAudioOutputService, state: AudioOutputState) -> None:
        if self._closed:
            return
        destinations: dict[str, list[ApoWriteRequest]] = {}
        for target in tuple(self._targets.values()):
            request = target.intent
            if request is not None:
                destinations.setdefault(request.manager.target_key(), []).append(request)
        for key, requests in destinations.items():
            if not any(request.output_service is output and request.output != state for request in requests):
                continue
            # Historical installations may now resolve to one file. Keep the
            # latest explicit intent, not whichever target was inserted last.
            request = max(requests, key=lambda item: item.intent_revision)
            target = self.target(key)
            pending = request.generation > target.completed
            for old in requests:
                queued = self._pending.get(old.target)
                if queued is not None and queued.intent_revision <= request.intent_revision:
                    self._pending.pop(old.target)
                if old.target != key:
                    self.target(old.target).intent = None
                    self.redirected.emit(old.target, key)
            request = replace(request, target=key)
            if target.intent is not None and target.intent.intent_revision > request.intent_revision:
                continue
            target.intent = request
            current_output = state if request.output_service is output else request.output_service.state
            if pending or request.output != current_output:
                self._generation += 1
                self._enqueue(replace(request, generation=self._generation, output=current_output))
            else:
                self.changed.emit(key)

    def _submit_latest(self) -> None:
        if self._closed or self._running is not None or not self._pending:
            return
        _key, request = self._pending.popitem(last=False)
        self._running = request
        future = self._executor.submit(self._execute, request)
        future.add_done_callback(lambda done: self._finish_worker(request, done))

    def _execute(self, request: ApoWriteRequest) -> ApoApplyResult:
        if request.options.processor == "native":
            if request.options.native is None:
                return ApoApplyResult("Native DSP unavailable", "Missing native binding options")
            key = request.manager.target_key()
            route = self._native_routes.get(key)
            if route is None:
                route = NativeApoRoute(key, request.options.native)
                self._native_routes[key] = route
            if route.options != request.options.native:
                return ApoApplyResult(
                    "Conflicting native route", "The canonical target already belongs to a different profile or DLL"
                )
            return request.manager.apply(
                request.gains,
                request.output,
                request.options,
                native=route,
                audio=request.audio,
                generation=request.generation,
                restore=request.restore,
            )
        return request.manager.apply(request.gains, request.output, request.options)

    def observe_native(self, key: str) -> NativeObservation:
        target = self.target(key)
        route = self._native_routes.get(key)
        if self._closed or route is None or target.intent is None:
            return NativeObservation()
        return route.observe(target.intent.generation)

    def _retire_native(self, keep: frozenset[str]) -> None:
        for key in tuple(self._native_routes):
            if key not in keep:
                self._native_routes.pop(key).close()

    def _close_native(self) -> None:
        for route in self._native_routes.values():
            route.close()
        self._native_routes.clear()

    def _finish_worker(self, request: ApoWriteRequest, future: Future[ApoApplyResult]) -> None:
        try:
            result = future.result()
        except Exception as error:
            logger.exception("Equalizer APO update failed")
            result = ApoApplyResult("Equalizer APO — write failed", str(error))
        try:
            self._job_finished.emit(request, result)
        except RuntimeError:
            pass

    def _on_job_finished(self, request: ApoWriteRequest, result: ApoApplyResult) -> None:
        self._running = None
        if self._closed:
            return
        key = request.target
        repair: ApoWriteRequest | None = None
        if result.state is not None:
            self._on_state(result.state)
            if result.state.target != key:
                old = self.target(key)
                new = self.target(result.state.target)
                if old.intent is not None and old.intent.generation == request.generation:
                    old.intent = None
                    if new.intent is None or new.intent.intent_revision < request.intent_revision:
                        new.intent = replace(request, target=result.state.target)
                if new.intent is not None and new.intent.intent_revision > request.intent_revision:
                    # Discovery may move an in-flight older intent onto a file
                    # whose newer explicit intent already finished. Restore it.
                    repair = new.intent
                self.redirected.emit(key, result.state.target)
                key = result.state.target
        target = self.target(key)
        if (
            request.restore
            and result.state is not None
            and target.intent is not None
            and target.intent.generation == request.generation
        ):
            target.intent = replace(target.intent, gains=result.state.gains, audio=result.state.audio, restore=False)
        target.completed = max(target.completed, request.generation)
        if target.intent is not None and target.intent.generation == request.generation:
            target.failed = not result.applied
            target.status, target.detail = result.status, result.detail
        self.changed.emit(key)
        if repair is not None:
            self._generation += 1
            self._enqueue(replace(repair, generation=self._generation, output=repair.output_service.state))
        if self._native_routes:
            keep = frozenset(
                key
                for key, value in self._targets.items()
                if value.intent is not None and value.intent.options.processor == "native"
            )
            self._executor.submit(self._retire_native, keep)
        self._submit_latest()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pending.clear()
        EqualizerApoConfigManager.unsubscribe(self._post_state)
        for output, callback in self._outputs.items():
            try:
                output.default_output_changed.disconnect(callback)
            except RuntimeError, TypeError:
                pass
        self._outputs.clear()
        self._executor.submit(self._close_native)
        self._executor.shutdown(wait=False, cancel_futures=False)
        for key in tuple(self._targets):
            self.changed.emit(key)


class EqualizerApoController(QObject):
    """A view's editing state and lease on the application's shared APO writer."""

    status_changed = pyqtSignal(str, str)
    committed_changed = pyqtSignal(object)
    applied_changed = pyqtSignal(object)
    draft_changed = pyqtSignal()

    def __init__(
        self,
        options: Any,
        parent: QObject | None = None,
        *,
        output_service: DefaultAudioOutputService | None = None,
        manager: Any = None,
    ) -> None:
        super().__init__(parent)
        self.options = options
        self.apo_options = getattr(
            options,
            "apo",
            SimpleNamespace(
                enabled=False,
                auto_preamp=True,
                preamp_db=0.0,
                write_debounce_ms=100,
                manage_include=False,
            ),
        )
        self.enabled = getattr(options, "backend", "visual") == "equalizer_apo" and bool(self.apo_options.enabled)
        self._native_profile: str | None = None
        if self.enabled and getattr(self.apo_options, "processor", "graphic_eq") == "native":
            from core.config import get_config_dir

            self._native_profile = canonical(get_config_dir())
        self._manager: EqualizerApoConfigManager = manager or EqualizerApoConfigManager()
        self._output = output_service or DefaultAudioOutputService.instance()
        self._ensure_output_service()
        self._writer = EqualizerApoWriter.shared() if self.enabled else None
        self._target = ""
        self._editing_gains = (0.0,) * len(FREQUENCIES)
        self._applied: ApoAppliedState | None = None
        self._dirty = False
        self._draft_token = object()
        self._draft_target: str | None = None
        self._draft_writer: EqualizerApoWriter | None = None
        self._draft_base: ApoAppliedState | None = None
        self._visual_committed = self._editing_gains
        self._write_failed = False
        self._closed = False
        if self._writer is not None and is_valid_qobject(self._writer) and not self._writer.closed:
            self._writer.changed.connect(self._on_owner_changed)
            self._writer.redirected.connect(self._redirected)
            self._output.request_refresh()

    @property
    def gains(self) -> tuple[float, ...]:
        return self._editing_gains

    @property
    def editing_gains(self) -> tuple[float, ...]:
        return self._editing_gains

    @property
    def applied_gains(self) -> tuple[float, ...] | None:
        return self._applied.gains if self._applied is not None else None

    @property
    def applied_state(self) -> ApoAppliedState | None:
        return self._applied

    @property
    def pending(self) -> bool:
        writer = self._ensure_writer()
        if writer is None:
            return self._dirty
        target = writer.target(self._target)
        intent, applied = target.intent, target.applied
        same_values = False
        if intent is not None and applied is not None:
            if intent.options.processor == "native":
                # Compare the actual float32 protocol values, including Audio.
                # Python float64 intent must match the same settings decoded
                # from the persisted float32 protocol. This is not a DSP ACK.
                try:
                    wanted = native_parameters(
                        intent.gains, intent.audio, intent.options.auto_preamp, intent.options.preamp_db
                    )
                    saved = native_parameters(
                        applied.gains, applied.audio, applied.options.auto_preamp, applied.options.preamp_db
                    )
                    same_values = wanted.pack()[16:] == saved.pack()[16:]
                except ValueError:
                    pass
            else:
                same_values = intent.gains == applied.gains
        return (
            self._dirty
            or target.failed
            or bool(
                intent
                and (
                    intent.generation > target.completed
                    or applied is None
                    or not same_values
                    or (intent.output, intent.options) != (applied.output, applied.options)
                )
            )
        )

    @property
    def write_failed(self) -> bool:
        return self._write_failed

    @property
    def has_draft(self) -> bool:
        return self._dirty

    @property
    def draft_identity(self) -> object | None:
        return self._draft_token if self._dirty else None

    @property
    def writer_available(self) -> bool:
        return not self.enabled or self._ensure_writer() is not None

    @property
    def draft_available(self) -> bool:
        writer = self._ensure_writer()
        if writer is None:
            return not self.enabled
        target = writer.target(self._target)
        requested = ApoWriteOptions.snapshot(self.apo_options, native_profile=self._native_profile)
        owner = (
            target.intent.options
            if target.intent is not None
            else target.applied.options
            if target.applied is not None
            else None
        )
        return target.draft_owner in (None, self._draft_token) and (
            owner is None or (owner.processor, owner.native) == (requested.processor, requested.native)
        )

    @staticmethod
    def _settled_base(target: _ApoTarget) -> ApoAppliedState | None:
        applied, intent = target.applied, target.intent
        if applied is None or target.failed:
            return None
        if intent is not None and (
            intent.generation > target.completed
            or (intent.gains, intent.options, intent.output, intent.audio)
            != (applied.gains, applied.options, applied.output, applied.audio)
        ):
            return None
        return applied

    @property
    def draft_needs_review(self) -> bool:
        writer = self._ensure_writer()
        key = self._draft_target
        if writer is None or key is None or key != self._manager.target_key():
            return False
        target = writer.target(key)
        if writer is self._draft_writer and target.draft_owner is self._draft_token:
            return False
        base = self._draft_base
        return base is None or self._settled_base(target) != base or EqualizerApoConfigManager.applied_for(key) != base

    def _ensure_output_service(self) -> None:
        if type(self._output) is DefaultAudioOutputService and (
            not is_valid_qobject(self._output) or self._output.closed
        ):
            self._output = DefaultAudioOutputService.instance()

    def _disconnect_writer(self, writer: EqualizerApoWriter) -> None:
        if not is_valid_qobject(writer):
            return
        try:
            writer.changed.disconnect(self._on_owner_changed)
            writer.redirected.disconnect(self._redirected)
        except RuntimeError, TypeError:
            pass

    def _ensure_writer(self) -> EqualizerApoWriter | None:
        if not self.enabled or self._closed:
            return None
        writer = self._writer
        shared = EqualizerApoWriter.shared_instance()
        if writer is not None and writer is shared and is_valid_qobject(writer) and not writer.closed:
            return writer
        if writer is not None:
            self._disconnect_writer(writer)
        if shared is None or not is_valid_qobject(shared) or shared.closed:
            self._writer = None
            return None
        self._writer = shared
        shared.changed.connect(self._on_owner_changed)
        shared.redirected.connect(self._redirected)
        return shared

    def reconnect_writer(self) -> None:
        if self._closed or not self.enabled:
            return
        EqualizerApoWriter.shared()
        if self._ensure_writer() is None:
            self.status_changed.emit("Equalizer APO writer unavailable", "Retry when the current writer has drained.")
        elif self._dirty:
            self.status_changed.emit("", "")
        else:
            self._on_owner_changed(self._target, force=True)
        self.draft_changed.emit()

    def review_custom(self) -> None:
        if self.draft_needs_review:
            self.discard_custom()
            self.status_changed.emit("Review the current curve", "Edit again to create a fresh draft.")

    def _bind(self) -> None:
        self._ensure_output_service()
        self._target = self._manager.target_key()

    def _authorize_destination(self) -> bool:
        key = self._manager.target_key()
        writer = self._ensure_writer()
        if self.enabled and writer is None:
            return False
        if writer is not None:
            target = writer.target(key)
            owner = (
                target.intent.options
                if target.intent is not None
                else target.applied.options
                if target.applied is not None
                else None
            )
            requested = ApoWriteOptions.snapshot(self.apo_options, native_profile=self._native_profile)
            if owner is not None and (owner.processor, owner.native) != (requested.processor, requested.native):
                return False
            current_audio = (
                target.intent.audio
                if target.intent is not None
                else target.applied.audio
                if target.applied is not None
                else NativeAudioState()
            )
            if (
                target.draft_owner not in (None, self._draft_token)
                or (target.intent is not None and target.intent.restore)
                or self._requires_restore(target)
                or (requested.processor == "native" and current_audio.adaptive)
            ):
                return False
        self._target = key
        return True

    def start(self, gains: Sequence[float]) -> None:
        if self._closed:
            return
        self._visual_committed = validate_gains(gains)
        self._bind()
        writer = self._ensure_writer()
        if writer is not None:
            target = writer.target(self._target)
            current_options = (
                target.intent.options
                if target.intent is not None
                else target.applied.options
                if target.applied is not None
                else None
            )
            requested = ApoWriteOptions.snapshot(self.apo_options, native_profile=self._native_profile)
            if current_options is not None and (current_options.processor, current_options.native) != (
                requested.processor,
                requested.native,
            ):
                self.status_changed.emit(
                    "Conflicting audio processor",
                    "This canonical configuration target already has a different processor/profile owner.",
                )
                return
        if writer is not None and writer.target(self._target).intent is not None:
            self._on_owner_changed(self._target, force=True)
        elif writer is not None and (applied := writer.target(self._target).applied) is not None:
            self._editing_gains = applied.gains
            writer.queue(self._target, applied.gains, self._output, self._manager, applied.options)
            self._on_owner_changed(self._target, force=True)
        else:
            if writer is not None and getattr(self.apo_options, "processor", "graphic_eq") == "native":
                self._editing_gains = validate_gains(gains)
                self._queue_write(restore=True)
            else:
                self.apply_preset(gains)
            if writer is not None:
                self._on_owner_changed(self._target, force=True)

    def apply_preset(self, gains: Sequence[float]) -> bool:
        if self._closed or not self._authorize_destination():
            return False
        values = validate_gains(gains)
        if self.enabled:
            if self.draft_needs_review or not self._admit_draft() or not self._queue_write(gains=values):
                return False
        else:
            self._editing_gains = self._visual_committed = values
            self._dirty = False
            self.committed_changed.emit(values)
        self.draft_changed.emit()
        return True

    def update_custom(
        self, gains: Sequence[float], *, final: bool = False, expected_draft: object | None = None
    ) -> bool:
        """Edit only a draft, including slider release; final no longer writes."""
        accepted, _identity = self.edit_custom(gains, expected_draft=expected_draft)
        return accepted

    def edit_custom(
        self, gains: Sequence[float], *, expected_draft: object | None = None
    ) -> tuple[bool, object | None]:
        """Return the lease of this edit even if a synchronous observer replaces it."""
        if self._closed or not self._authorize_destination():
            return False, None
        writer = self._ensure_writer()
        if expected_draft is not None and (
            self.draft_identity is not expected_draft
            or self.enabled
            and (
                writer is None
                or self._draft_writer is not writer
                or self._draft_target != self._target
                or writer.target(self._target).draft_owner is not expected_draft
            )
        ):
            return False, None
        if self._draft_target is not None and self._draft_target != self._target:
            self.discard_custom()
            return False, None
        if not self._admit_draft(notify=True):
            return False, None
        values = validate_gains(gains)
        target = writer.target(self._target) if writer is not None else None
        baseline = self._committed_gains(target)
        if values == baseline:
            self.discard_custom()
            return True, None
        if not self._dirty:
            self._draft_token = object()
        self._editing_gains = values
        self._dirty = True
        identity = self._draft_token
        if writer is not None:
            if self._draft_target is None:
                self._draft_base = self._settled_base(writer.target(self._target))
                self._draft_target = self._target
                self._draft_writer = writer
                writer.claim_draft(self._target, identity)
        self.draft_changed.emit()
        return True, identity

    def flush(self) -> None:
        """Explicit commit alias; no timer or release event calls this method."""
        self.apply_custom()

    def apply_custom(self) -> bool:
        if self._closed:
            return False
        self._ensure_output_service()
        writer = self._ensure_writer()
        if self.enabled and writer is None:
            self.status_changed.emit("Equalizer APO writer unavailable", "Reconnect before applying this curve.")
            return False
        if writer is not None and not self._dirty:
            key = self._manager.target_key()
            target = writer.target(key)
            if target.intent is not None and target.intent.restore:
                requested = ApoWriteOptions.snapshot(self.apo_options, native_profile=self._native_profile)
                owner = target.intent.options
                if target.intent.generation > target.completed or (owner.processor, owner.native) != (
                    requested.processor,
                    requested.native,
                ):
                    return False
                # Retry a failed startup restoration without converting its
                # placeholder UI curve into a new committed setting.
                return writer.queue(
                    target.intent.target,
                    target.intent.gains,
                    self._output,
                    self._manager,
                    target.intent.options,
                    restore=True,
                )
            if self._requires_restore(target):
                self._target = key
                return self._queue_write(gains=self._visual_committed, restore=True)
        if writer is not None and self._draft_target is not None:
            if self._manager.target_key() != self._draft_target:
                self.discard_custom()
                self._bind()
                self._on_owner_changed(self._target, force=True)
                self.status_changed.emit("Output configuration changed", "Review the curve before applying again.")
                return False
        if not self._authorize_destination():
            return False
        if writer is not None:
            if self._dirty:
                if not self._admit_draft() or not self._queue_write():
                    self.draft_changed.emit()
                    return False
            else:
                target = writer.target(self._target)
                if not target.failed or target.intent is None or not self._queue_write(gains=target.intent.gains):
                    return False
        else:
            self._dirty = False
            self._visual_committed = self._editing_gains
            self.committed_changed.emit(self._editing_gains)
        self.draft_changed.emit()
        return True

    def _admit_draft(self, *, notify: bool = False) -> bool:
        key = self._draft_target
        if key is None:
            return not self._dirty or not self.enabled
        writer = self._ensure_writer()
        if writer is None or key != self._target:
            return False
        if writer is self._draft_writer and writer.target(key).draft_owner is self._draft_token:
            return True
        if self.draft_needs_review or writer.target(key).draft_owner is not None:
            return False
        self._draft_writer = writer
        token = self._draft_token = object()
        # Apply/preset will publish the lease change alongside the queued intent.
        return (
            writer.claim_draft(key, token, notify=notify) and self._draft_token is token and self._draft_target == key
        )

    def _release_draft(self) -> None:
        writer, self._draft_writer = self._draft_writer, None
        self._draft_base = None
        if self._draft_target is not None:
            key, self._draft_target = self._draft_target, None
            if writer is not None and is_valid_qobject(writer) and not writer.closed:
                writer.release_draft(key, self._draft_token)

    def discard_custom(self) -> None:
        self._dirty = False
        writer = self._ensure_writer()
        self._release_draft()
        target = writer.target(self._target) if writer is not None else None
        if target is not None and (target.intent is not None or target.applied is not None):
            self._on_owner_changed(self._target, force=True)
        else:
            self._editing_gains = self._applied.gains if self._applied is not None else self._visual_committed
            self.committed_changed.emit(self._editing_gains)
        self.draft_changed.emit()

    def _queue_write(self, *, gains: tuple[float, ...] | None = None, restore: bool = False) -> bool:
        writer = self._ensure_writer()
        if writer is None or (self._draft_target is not None and self._draft_writer is not writer):
            return False
        self._ensure_output_service()
        # Queue notifications can synchronously start a new draft on the new intent.
        old_gains, old_dirty = self._editing_gains, self._dirty
        old_writer, self._draft_writer = self._draft_writer, None
        old_base, self._draft_base = self._draft_base, None
        old_target, self._draft_target = self._draft_target, None
        self._editing_gains = gains if gains is not None else old_gains
        self._dirty = False
        accepted = writer.queue(
            self._target,
            self._editing_gains,
            self._output,
            self._manager,
            ApoWriteOptions.snapshot(self.apo_options, native_profile=self._native_profile),
            draft_target=old_target,
            draft_token=self._draft_token if old_target is not None else None,
            restore=restore,
        )
        if not accepted:
            self._editing_gains, self._dirty = old_gains, old_dirty
            self._draft_writer, self._draft_base = old_writer, old_base
            self._draft_target = old_target
        return accepted

    @property
    def restore_required(self) -> bool:
        writer = self._ensure_writer()
        return writer is not None and self._requires_restore(writer.target(self._manager.target_key()))

    def _requires_restore(self, target: _ApoTarget) -> bool:
        return self._native_profile is not None and target.intent is None and target.applied is None

    @property
    def restoring(self) -> bool:
        writer = self._ensure_writer()
        if writer is None:
            return False
        intent = writer.target(self._target).intent
        return bool(intent is not None and intent.restore)

    @property
    def persistence_pending(self) -> bool:
        writer = self._ensure_writer()
        if writer is None:
            return False
        target = writer.target(self._target)
        return bool(target.intent is not None and target.intent.generation > target.completed)

    @property
    def audio_available(self) -> bool:
        writer = self._ensure_writer()
        if writer is None or self._closed or self.restoring:
            return False
        target = writer.target(self._target)
        options = ApoWriteOptions.snapshot(self.apo_options, native_profile=self._native_profile)
        return bool(
            target.intent is not None
            and options.processor == "native"
            and (options.processor, options.native) == (target.intent.options.processor, target.intent.options.native)
        )

    @property
    def output_state(self) -> AudioOutputState:
        self._ensure_output_service()
        return self._output.state

    @property
    def audio_state(self) -> NativeAudioState:
        writer = self._ensure_writer()
        if writer is not None:
            target = writer.target(self._target)
            if target.intent is not None:
                return target.intent.audio
            if target.applied is not None:
                return target.applied.audio
        return NativeAudioState()

    @property
    def native_observation(self) -> NativeObservation:
        writer = self._ensure_writer()
        return writer.observe_native(self._target) if writer is not None else NativeObservation()

    def update_audio(self, **changes: Any) -> bool:
        writer = self._ensure_writer()
        if self._closed or writer is None:
            return False
        self._ensure_output_service()
        key = self._manager.target_key()
        options = ApoWriteOptions.snapshot(self.apo_options, native_profile=self._native_profile)
        if options.processor != "native":
            return False
        if key != self._target:
            self.discard_custom()
            self._target = key
            self._on_owner_changed(key, force=True)
        target = writer.target(key)
        if target.intent is not None:
            gains, baseline = target.intent.gains, target.intent.audio
        elif target.applied is not None:
            gains, baseline = target.applied.gains, target.applied.audio
        else:
            return False  # The destination must acquire/restore a committed base first.
        audio = replace(baseline, **changes)
        return writer.queue(key, gains, self._output, self._manager, options, audio=audio)

    def _redirected(self, old: str, new: str) -> None:
        if self._target == old:
            self._target = new
            if self._draft_target == old:
                self._dirty = False
                self._release_draft()
            self._on_owner_changed(new, force=True)

    def _on_owner_changed(self, key: str, *, force: bool = False) -> None:
        writer = self._ensure_writer()
        if self._closed or key != self._target:
            return
        if writer is None:
            self.draft_changed.emit()
            return
        target = writer.target(key)
        if target.intent is not None and target.intent.audio.adaptive and self._dirty:
            self._dirty = False
            self._release_draft()
        if target.applied != self._applied:
            self._applied = target.applied
            self.applied_changed.emit(self._applied)
        if not self._dirty and (target.intent is not None or target.applied is not None):
            gains = self._committed_gains(target)
            if force or gains != self._editing_gains:
                self._editing_gains = gains
                self.committed_changed.emit(gains)
        self._write_failed = target.failed
        self.status_changed.emit(target.status, target.detail)
        self.draft_changed.emit()

    def _committed_gains(self, target: _ApoTarget | None) -> tuple[float, ...]:
        if target is not None:
            if target.intent is not None:
                return target.intent.gains
            if target.applied is not None:
                return target.applied.gains
        return self._visual_committed

    def open_configurator(self) -> bool:
        try:
            return self._manager.open_configurator()
        except Exception:
            logger.debug("Unable to open Equalizer APO Configurator", exc_info=True)
            return False

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        writer = self._writer
        self._release_draft()
        if writer is not None and is_valid_qobject(writer):
            try:
                writer.changed.disconnect(self._on_owner_changed)
                writer.redirected.disconnect(self._redirected)
            except RuntimeError, TypeError:
                pass
