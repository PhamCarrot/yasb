"""Profile-bound persistence/transport for the existing canonical APO writer.

Only the writer worker constructs, prepares, persists and closes a route. GUI
readback copies bounded broker reports; it never changes intent or a draft.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import shutil
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from core.widgets.services.media.native_api import (
    NativeBootstrap,
    NativeBroker,
    NativeDspApi,
    NativeParameters,
    NativeReport,
)


def canonical(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).resolve()))


@dataclass(frozen=True)
class NativeRouteOptions:
    profile: str
    library: str
    sha256: str

    def validate(self) -> None:
        if not self.profile or not Path(self.profile).is_absolute() or not Path(self.library).is_absolute():
            raise ValueError("Native DSP needs an absolute DLL path and a selected profile")
        if len(self.sha256) != 64 or any(char not in "0123456789abcdef" for char in self.sha256):
            raise ValueError("Native DSP needs the prepared DLL SHA-256")
        if any(char in self.library for char in '\0\r\n"'):
            raise ValueError("Invalid native DLL path")


@dataclass(frozen=True)
class NativeAudioState:
    balance: float = 0
    mono: bool = False
    swap: bool = False
    dynamics: int = 0
    adaptive: bool = False
    bypass: bool = False

    @classmethod
    def from_parameters(cls, parameters: NativeParameters) -> NativeAudioState:
        return cls(
            parameters.balance,
            bool(parameters.flags & 1),
            bool(parameters.flags & 2),
            parameters.dynamics,
            bool(parameters.flags & 4),
            bool(parameters.flags & 8),
        )

    def parameters(self, gains: tuple[float, ...], preamp_db: float) -> NativeParameters:
        if any(type(value) is not bool for value in (self.mono, self.swap, self.adaptive, self.bypass)):
            raise ValueError("Native audio switches must be boolean")
        flags = int(self.mono) | (int(self.swap) << 1) | (int(self.adaptive) << 2) | (int(self.bypass) << 3)
        result = NativeParameters(gains, self.balance, flags, self.dynamics, preamp_db)
        result.pack()
        return result


@dataclass(frozen=True)
class NativeObservation:
    intent_generation: int = 0
    persisted_revision: int = 0
    reports: tuple[NativeReport, ...] = ()
    detail: str = "Native DSP has no persisted route"
    advancing: bool = False

    def playback_status(self, bypass: bool) -> str:
        if self.processing:
            return "Bypass confirmed" if bypass else "Processing frames confirmed"
        if not self.reports:
            return "Saved; audio host has not connected"
        if any(row.status.processing == 2 for row in self.reports):
            return "Audio host connected; unsupported sample rate"
        if not self.advancing:
            return "Audio host connected; waiting for playback frames"
        if any(row.status.host_latency_pending for row in self.reports):
            return "Audio frames arriving; host latency update pending"
        return "Audio frames arriving; waiting for settings confirmation"

    @property
    def processing(self) -> bool:
        return (
            self.advancing
            and bool(self.reports)
            and all(
                row.confirmed_generation == self.persisted_revision
                and row.age_ms < 1000
                and row.status.processing in (1, 3)
                and row.status.processed_frames > 0
                and row.status.callback_age_ms < 1000
                and not row.status.host_latency_pending
                for row in self.reports
            )
        )


@dataclass(frozen=True)
class NativeCommit:
    bootstrap: NativeBootstrap
    parameters: NativeParameters
    revision: int
    intent_generation: int
    text: str
    previous: bytes | None


def native_parameters(
    gains: tuple[float, ...], audio: NativeAudioState, auto_preamp: bool, preamp_db: float
) -> NativeParameters:
    preamp = -max(0.0, max(gains)) if auto_preamp else preamp_db
    if not math.isfinite(preamp):
        raise ValueError("Invalid native preamp")
    return audio.parameters(gains, preamp)


class NativeApoRoute:
    def __init__(self, target: str, options: NativeRouteOptions) -> None:
        options.validate()
        self.target, self.options = canonical(target), options
        self.api = NativeDspApi(Path(options.library), expected_sha256=options.sha256)
        self.config_key = hashlib.sha256((canonical(options.profile) + "\0" + self.target).encode()).digest()
        self.record_path = (
            Path(options.profile) / "media-dsp" / (hashlib.sha256(self.target.encode()).hexdigest() + ".json")
        )
        self._broker: NativeBroker | None = None
        self._installation: bytes | None = None
        self._progress: dict[tuple[bytes, int, int], tuple[int, float, bool]] = {}
        self._committed: NativeCommit | None = None
        self._lock = threading.RLock()
        self._closed = False
        self._detail = "Native DSP has no connected processing instance"

    def prepare(
        self,
        parameters: NativeParameters,
        endpoint_guid: str,
        generation: int,
        *,
        restore: bool = False,
        auto_preamp: bool = True,
    ) -> NativeCommit:
        if self._closed:
            raise RuntimeError("Native route is closed")
        endpoint = hashlib.sha256(endpoint_guid.lower().encode()).digest()
        previous = None
        revision = 1
        try:
            if self.record_path.stat().st_size > 32768:
                raise ValueError("Native state record exceeds its size limit")
            previous = self.record_path.read_bytes()
        except FileNotFoundError:
            pass
        if previous is not None:
            value: object = json.loads(previous.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Unsupported native state record")
            record = cast(dict[str, object], value)
            if record.get("schema") != 1:
                raise ValueError("Unsupported native state record")
            expected = {
                "profile": canonical(self.options.profile),
                "target": self.target,
                "library": canonical(self.options.library),
                "sha256": self.options.sha256,
                "build": self.api.build,
            }
            if any(record.get(key) != value for key, value in expected.items()):
                raise ValueError("Native state belongs to another profile, target or DLL; review migration first")
            encoded_bootstrap, encoded_parameters = record.get("bootstrap"), record.get("parameters")
            if not isinstance(encoded_bootstrap, str) or not isinstance(encoded_parameters, str):
                raise ValueError("Missing native state payload")
            bootstrap = NativeBootstrap.unpack(base64.b64decode(encoded_bootstrap, validate=True))
            last = NativeParameters.unpack(base64.b64decode(encoded_parameters, validate=True))
            # Read/validate the committed payload even though the current explicit
            # intent supersedes it. Never overwrite an unrecognizable record.
            if last.revision != record.get("revision") or not 0 < last.revision < 2**64 - 1:
                raise ValueError("Invalid native persisted revision")
            revision = last.revision + 1
            if restore:
                parameters = replace(
                    last, preamp_db=-max(0.0, max(last.gains)) if auto_preamp else parameters.preamp_db
                )
            current = self.api.bootstrap(self.config_key, endpoint, installation=bootstrap.installation)
            if bootstrap.config != self.config_key or bootstrap.controller_sid != current.controller_sid:
                raise ValueError("Native state binding/controller mismatch")
            if bootstrap.endpoint != endpoint:
                bootstrap = replace(bootstrap, endpoint=endpoint, initial=parameters)
        else:
            if self._committed is not None:
                raise ValueError("Native state record was removed; restore its backup before continuing")
            bootstrap = self.api.bootstrap(
                self.config_key, endpoint, installation=self._installation, initial=parameters
            )
        parameters = replace(parameters, revision=revision)
        if self._broker is None:
            self._broker = self.api.create(bootstrap)
            self._installation = bootstrap.installation
        elif self._installation != bootstrap.installation:
            raise ValueError("Native installation binding changed while active")
        record = {
            "schema": 1,
            "profile": canonical(self.options.profile),
            "target": self.target,
            "library": canonical(self.options.library),
            "sha256": self.options.sha256,
            "build": self.api.build,
            "bootstrap": base64.b64encode(bootstrap.pack()).decode("ascii"),
            "parameters": base64.b64encode(parameters.pack()).decode("ascii"),
            "revision": revision,
        }
        return NativeCommit(bootstrap, parameters, revision, generation, json.dumps(record, indent=2) + "\n", previous)

    def persist(self, commit: NativeCommit) -> None:
        from core.widgets.services.media.equalizer_apo import atomic_write_text

        self.record_path.parent.mkdir(parents=True, exist_ok=True)
        if commit.previous is not None:
            backup = self.record_path.with_suffix(".json.backup")
            if not backup.exists():
                shutil.copy2(self.record_path, backup)
        atomic_write_text(self.record_path, commit.text)

    def publish(self, commit: NativeCommit) -> None:
        assert self._broker is not None
        accepted = self._broker.publish(commit.bootstrap, commit.parameters, commit.revision)
        with self._lock:
            self._committed = commit
            self._detail = (
                "Native DSP has no connected processing instance"
                if accepted
                else "Persisted; resident control rejected the update"
            )

    def observe(self, intent_generation: int) -> NativeObservation:
        with self._lock:
            commit, broker = self._committed, self._broker
            if commit is None or broker is None or self._closed:
                return NativeObservation(detail=self._detail)
            if commit.intent_generation != intent_generation:
                return NativeObservation(
                    intent_generation=intent_generation, detail="Native DSP intent is pending persistence"
                )
            rows = tuple(
                row
                for row in broker.reports()
                if row.config == commit.bootstrap.config and row.endpoint == commit.bootstrap.endpoint
            )
            now = time.monotonic()
            progress: dict[tuple[bytes, int, int], tuple[int, float, bool]] = {}
            advancing = bool(rows)
            for row in rows:
                identity = (row.status.instance_uuid, row.status.stream_epoch, row.connection_epoch)
                frames = row.status.processed_frames
                previous = self._progress.get(identity)
                if previous is None or frames < previous[0]:
                    value = (frames, now, False)
                elif frames > previous[0]:
                    value = (frames, now, True)
                else:
                    value = previous
                progress[identity] = value
                advancing = advancing and value[2] and now - value[1] < 1
            self._progress = progress
            return NativeObservation(
                intent_generation, commit.revision, rows, self._detail if not rows else "", advancing
            )

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._broker is not None:
                self._broker.close()
                self._broker = None
