"""Optional Equalizer APO backend for Media Widget V2."""

from __future__ import annotations

import codecs
import logging
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

try:
    import winreg
except ImportError:
    winreg = None
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

from core.widgets.services.media.audio_device import AudioOutputState, DefaultAudioOutputService

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


@dataclass(frozen=True)
class ApoWriteRequest:
    generation: int
    gains: tuple[float, ...]
    output: AudioOutputState


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


def discover_equalizer_apo_details(registry=winreg) -> tuple[EqualizerApoInstallation | None, str]:
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


def discover_equalizer_apo(registry=winreg) -> EqualizerApoInstallation | None:
    """Discover Equalizer APO from HKLM without assuming Program Files."""
    return discover_equalizer_apo_details(registry)[0]


def validate_gains(gains) -> tuple[float, ...]:
    values = tuple(float(value) for value in gains)
    if len(values) != len(FREQUENCIES):
        raise ValueError("Equalizer APO requires exactly 10 gains")
    if any(value < -12.0 or value > 12.0 for value in values):
        raise ValueError("Equalizer APO gains must be between -12 and +12 dB")
    return values


def automatic_preamp(gains) -> float:
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


def build_graphic_eq(gains) -> str:
    values = validate_gains(gains)
    pairs = "; ".join(f"{frequency} {_format_db(gain)}" for frequency, gain in zip(FREQUENCIES, values))
    return f"GraphicEQ: {pairs}"


def render_managed_config(
    gains,
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

    include_names = []
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


def detect_external_filters(config_text: str) -> bool:
    """Backward-compatible boolean view of the richer config analysis."""
    return analyze_existing_config(config_text).external_filters


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

    def __init__(self, registry=winreg) -> None:
        self._registry = registry
        self._installation_checked = False
        self._installation: EqualizerApoInstallation | None = None
        self._discovery_status = "unknown"
        self._parent_checked = False
        self._include_ready = False
        self._external_filters = False
        self._analysis = ExistingConfigAnalysis(ExistingConfigKind.UNKNOWN, False)
        self._stock_neutralized = False
        self._last_payload = ""

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
        if self._parent_checked:
            return (
                None
                if self._include_ready
                else ApoApplyResult(
                    "Equalizer APO — setup required",
                    f"Add this line to {parent}: {INCLUDE_LINE}",
                    external_filters=self._external_filters,
                )
            )

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
        self._parent_checked = True

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
            self._include_ready = True
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

            self._include_ready = True
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

    def apply(self, gains, output: AudioOutputState, apo_options, *, enabled: bool = True) -> ApoApplyResult:
        setup = self._prepare_parent(bool(apo_options.manage_include))
        if setup is not None:
            return setup
        installation = self.installation
        if installation is None:
            return ApoApplyResult("Visual only — Equalizer APO not installed")
        if not output.endpoint_guid:
            return ApoApplyResult(
                "Equalizer APO — output unavailable",
                "Windows did not provide a default multimedia render endpoint.",
                external_filters=self._external_filters,
            )
        try:
            payload = render_managed_config(
                gains,
                output.endpoint_guid,
                auto_preamp=bool(apo_options.auto_preamp),
                preamp_db=float(apo_options.preamp_db),
                enabled=enabled,
            )
            if payload != self._last_payload:
                atomic_write_text(installation.config_path / MANAGED_FILENAME, payload, "utf-8")
                self._last_payload = payload
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


class EqualizerApoController(QObject):
    """Qt-facing serialized/coalescing controller for autosaved EQ writes."""

    status_changed = pyqtSignal(str, str)
    _job_finished = pyqtSignal(object, object)

    def __init__(self, options, parent=None, *, output_service=None, manager=None) -> None:
        super().__init__(parent)
        self.options = options
        self.apo_options = getattr(
            options,
            "apo",
            SimpleNamespace(
                enabled=False,
                target_device="default",
                auto_preamp=True,
                preamp_db=0.0,
                write_debounce_ms=100,
                manage_include=False,
            ),
        )
        self.enabled = getattr(options, "backend", "visual") == "equalizer_apo" and bool(self.apo_options.enabled)
        self._manager = manager or EqualizerApoConfigManager()
        self._output = output_service or DefaultAudioOutputService.instance()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="yasb-equalizer-apo")
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(int(self.apo_options.write_debounce_ms))
        self._timer.timeout.connect(self.flush)
        self._job_finished.connect(self._on_job_finished)
        self._generation = 0
        self._running = False
        self._latest_request: ApoWriteRequest | None = None
        self._inflight_request: ApoWriteRequest | None = None
        self._editing_gains = (0.0,) * len(FREQUENCIES)
        self._applied_gains: tuple[float, ...] | None = None
        self._write_failed = False
        self._closed = False
        self._connected = False
        if self.enabled:
            self._output.default_output_changed.connect(self._on_output_changed)
            self._connected = True
            self._output.request_refresh()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    @property
    def gains(self) -> tuple[float, ...]:
        return self._editing_gains

    @property
    def editing_gains(self) -> tuple[float, ...]:
        return self._editing_gains

    @property
    def applied_gains(self) -> tuple[float, ...] | None:
        return self._applied_gains

    @property
    def pending(self) -> bool:
        return self.enabled and (self._write_failed or self._applied_gains != self._editing_gains)

    @property
    def write_failed(self) -> bool:
        return self._write_failed

    def start(self, gains) -> None:
        self.apply_preset(gains)

    def apply_preset(self, gains) -> None:
        self._editing_gains = validate_gains(gains)
        self._timer.stop()
        self._write_failed = False
        if self.enabled:
            self._queue_write(self._editing_gains)

    def update_custom(self, gains, *, final: bool = False) -> None:
        self._editing_gains = validate_gains(gains)
        if not self.enabled:
            return
        self._write_failed = False
        if final:
            self._timer.stop()
            self._queue_write(self._editing_gains)
        else:
            self._timer.start()

    def flush(self) -> None:
        if self.enabled and not self._closed:
            self._queue_write(self._editing_gains)

    def _on_output_changed(self, _state: AudioOutputState) -> None:
        if not self.enabled or self._closed:
            return
        # Autosave-only semantics: the visible curve is always the intended
        # curve, so a default-output change retargets that exact state.
        self._queue_write(self._editing_gains)

    def _queue_write(self, gains) -> None:
        if self._closed:
            return
        values = validate_gains(gains)
        self._generation += 1
        self._latest_request = ApoWriteRequest(self._generation, values, self._output.state)
        if not self._running:
            self._submit_latest()

    def _submit_latest(self) -> None:
        request = self._latest_request
        if request is None or self._closed:
            return
        self._running = True
        self._inflight_request = request
        future = self._executor.submit(self._manager.apply, request.gains, request.output, self.apo_options)
        future.add_done_callback(lambda result, request=request: self._finish_worker(request, result))

    def _finish_worker(self, request: ApoWriteRequest, future) -> None:
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
        self._running = False
        self._inflight_request = None
        if self._closed:
            return

        relevant = request.generation == self._generation and request.gains == self._editing_gains
        if result.applied:
            self._applied_gains = request.gains
            if relevant:
                self._write_failed = False
        elif relevant:
            # Keep the visible Custom curve. A later slider movement, preset,
            # or output change retries naturally through the same autosave path.
            self._write_failed = True

        if relevant:
            self._emit_status(result.status, result.detail)

        latest = self._latest_request
        if latest is not None and latest.generation > request.generation:
            self._submit_latest()

    def _emit_status(self, status: str, detail: str) -> None:
        try:
            self.status_changed.emit(status, detail)
        except RuntimeError:
            pass

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
        self._timer.stop()
        if self._connected:
            try:
                self._output.default_output_changed.disconnect(self._on_output_changed)
            except RuntimeError, TypeError:
                pass
            self._connected = False
        self._latest_request = None
        self._executor.shutdown(wait=False, cancel_futures=True)
