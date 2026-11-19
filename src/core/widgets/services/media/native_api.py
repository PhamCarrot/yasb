"""Validate the native DSP library and manage its broker handle."""

from __future__ import annotations

import hashlib
import math
import struct
import threading
from ctypes import c_void_p, cast, create_string_buffer, get_last_error
from dataclasses import dataclass, replace
from pathlib import Path

from core.utils.win32.bindings.yasb_media_dsp import MediaDspLibrary

MAGIC = 0x59445350
PROTOCOL = 3
_PARAMETERS = struct.Struct("<IIQ10ffIIf")
_BOOTSTRAP = struct.Struct("<IIII16s32s32s192s")
_STATUS = struct.Struct("<II6Q6I2Q18f16s3Q4IQ")
_REPORT = struct.Struct("<32s32s232sQQQ")
_INFO = struct.Struct("<6IQ")
assert (_PARAMETERS.size, _BOOTSTRAP.size + _PARAMETERS.size, _STATUS.size, _REPORT.size) == (72, 360, 232, 320)


@dataclass(frozen=True)
class NativeParameters:
    gains: tuple[float, ...] = (0.0,) * 10
    balance: float = 0
    flags: int = 0
    dynamics: int = 0
    preamp_db: float = 0
    revision: int = 1

    def pack(self) -> bytes:
        if (
            len(self.gains) != 10
            or any(not math.isfinite(gain) or abs(gain) > 12 for gain in self.gains)
            or not math.isfinite(self.balance)
            or abs(self.balance) > 1
            or not math.isfinite(self.preamp_db)
            or not -24 <= self.preamp_db <= 12
            or self.flags & ~15
            or self.dynamics not in (0, 1, 2)
            or not 0 <= self.revision < 2**64
        ):
            raise ValueError("Invalid native audio parameters")
        return _PARAMETERS.pack(
            MAGIC, PROTOCOL, self.revision, *self.gains, self.balance, self.flags, self.dynamics, self.preamp_db
        )

    @classmethod
    def unpack(cls, data: bytes) -> NativeParameters:
        fields = _PARAMETERS.unpack(data)
        if fields[:2] != (MAGIC, PROTOCOL):
            raise ValueError("Unsupported native audio protocol")
        result = cls(
            tuple(float(value) for value in fields[3:13]),
            float(fields[13]),
            int(fields[14]),
            int(fields[15]),
            float(fields[16]),
            int(fields[2]),
        )
        result.pack()
        return result

    @property
    def fingerprint(self) -> int:
        value = 14695981039346656037
        for byte in self.pack()[16:]:
            value = ((value ^ byte) * 1099511628211) & (2**64 - 1)
        return value


@dataclass(frozen=True)
class NativeBootstrap:
    installation: bytes
    config: bytes
    endpoint: bytes
    controller_sid: str
    initial: NativeParameters = NativeParameters()

    def pack(self) -> bytes:
        sid = self.controller_sid.encode("ascii")
        if (
            len(self.installation) != 16
            or not any(self.installation)
            or len(self.config) != 32
            or not any(self.config)
            or len(self.endpoint) != 32
            or not any(self.endpoint)
            or not sid.startswith(b"S-1-")
            or len(sid) >= 192
            or b"\0" in sid
            or not self.initial.revision
        ):
            raise ValueError("Invalid native bootstrap binding")
        return (
            _BOOTSTRAP.pack(MAGIC, PROTOCOL, 360, 0, self.installation, self.config, self.endpoint, sid)
            + self.initial.pack()
        )

    @classmethod
    def unpack(cls, data: bytes) -> NativeBootstrap:
        if len(data) != 360:
            raise ValueError("Invalid native bootstrap size")
        fields = _BOOTSTRAP.unpack(data[:288])
        if fields[:4] != (MAGIC, PROTOCOL, 360, 0):
            raise ValueError("Unsupported native bootstrap")
        result = cls(
            bytes(fields[4]),
            bytes(fields[5]),
            bytes(fields[6]),
            bytes(fields[7]).split(b"\0", 1)[0].decode("ascii"),
            NativeParameters.unpack(data[288:]),
        )
        result.pack()
        return result


@dataclass(frozen=True)
class NativeStatus:
    build: int
    accepted_revision: int
    applied_revision: int
    settled_revision: int
    processed_frames: int
    sample_rate: int
    channels: int
    latency_frames: int
    processing: int
    flags: int
    dynamics: int
    adaptive_observations: int
    adaptive_admitted: int
    adaptive_makeup: float
    adaptive_gains: tuple[float, ...]
    instance_uuid: bytes
    stream_epoch: int
    accepted_fingerprint: int
    applied_fingerprint: int
    transport_state: int
    transport_error: int
    process_id: int
    host_latency_pending: bool
    callback_age_ms: int

    @classmethod
    def unpack(cls, data: bytes) -> NativeStatus:
        f = _STATUS.unpack(data)
        if f[:2] != (PROTOCOL, _STATUS.size) or f[41] not in (0, 1):
            raise ValueError("Unsupported native status")
        result = cls(
            int(f[2]),
            int(f[4]),
            int(f[5]),
            int(f[6]),
            int(f[7]),
            int(f[8]),
            int(f[9]),
            int(f[10]),
            int(f[11]),
            int(f[12]),
            int(f[13]),
            int(f[14]),
            int(f[15]),
            float(f[16]),
            tuple(float(value) for value in f[17:34]),
            bytes(f[34]),
            int(f[35]),
            int(f[36]),
            int(f[37]),
            int(f[38]),
            int(f[39]),
            int(f[40]),
            bool(f[41]),
            int(f[42]),
        )
        if (
            result.processing not in (0, 1, 2, 3)
            or result.channels != 2
            or result.applied_revision > result.accepted_revision
            or result.settled_revision > result.applied_revision
            or result.adaptive_admitted > result.adaptive_observations
            or result.flags & ~15
            or result.dynamics not in (0, 1, 2)
            or result.transport_state not in (0, 1, 2, 3)
            or not result.process_id
            or not result.stream_epoch
            or result.instance_uuid == b"\0" * 16
            or not all(math.isfinite(value) for value in (result.adaptive_makeup, *result.adaptive_gains))
            or (
                result.sample_rate != 0
                if result.processing == 2
                else result.sample_rate not in (44100, 48000, 88200, 96000, 176400, 192000)
            )
        ):
            raise ValueError("Invalid native status")
        return result


@dataclass(frozen=True)
class NativeReport:
    config: bytes
    endpoint: bytes
    status: NativeStatus
    age_ms: int
    confirmed_generation: int
    connection_epoch: int

    @classmethod
    def unpack(cls, data: bytes) -> NativeReport:
        fields = _REPORT.unpack(data)
        return cls(
            bytes(fields[0]),
            bytes(fields[1]),
            NativeStatus.unpack(bytes(fields[2])),
            int(fields[3]),
            int(fields[4]),
            int(fields[5]),
        )


def _native_error(action: str) -> OSError:
    code = get_last_error()
    return OSError(code, f"Native media {action} failed (Windows error {code})")


class NativeDspApi:
    def __init__(self, path: Path, *, expected_sha256: str | None = None) -> None:
        self.path = path.resolve(strict=True)
        self.sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()
        if expected_sha256 is not None and self.sha256 != expected_sha256:
            raise ValueError("Native media DLL does not match its manifest")
        self._library = MediaDspLibrary(str(self.path))
        self._info = self._library.info
        self._bootstrap = self._library.bootstrap
        self._create = self._library.create
        self.broker_publish = self._library.publish
        self.broker_reports = self._library.reports
        self.broker_destroy = self._library.destroy
        buffer = create_string_buffer(_INFO.size)
        if not self._info(cast(buffer, c_void_p), len(buffer)):
            raise _native_error("protocol query")
        info = _INFO.unpack(buffer.raw)
        if info[:6] != (PROTOCOL, 72, 360, 232, 320, 0) or not info[6]:
            raise ValueError("Incompatible native media ABI")
        self.build = int(info[6])

    def bootstrap(
        self,
        config: bytes,
        endpoint: bytes,
        *,
        installation: bytes | None = None,
        initial: NativeParameters = NativeParameters(),
    ) -> NativeBootstrap:
        buffer = create_string_buffer(360)
        if not self._bootstrap(cast(buffer, c_void_p), len(buffer)):
            raise _native_error("bootstrap")
        current = NativeBootstrap.unpack(buffer.raw)
        result = replace(
            current,
            config=config,
            endpoint=endpoint,
            installation=installation or current.installation,
            initial=initial,
        )
        result.pack()
        return result

    def create(self, bootstrap: NativeBootstrap) -> NativeBroker:
        buffer = create_string_buffer(bootstrap.pack())
        handle = self._create(cast(buffer, c_void_p), 360)
        if not handle:
            raise _native_error("broker startup")
        return NativeBroker(self, int(handle))


class NativeBroker:
    def __init__(self, api: NativeDspApi, handle: int) -> None:
        self.api = api
        self._handle = handle
        self._lock = threading.RLock()

    def publish(self, binding: NativeBootstrap, parameters: NativeParameters, generation: int) -> bool:
        if not 0 < generation < 2**64:
            raise ValueError("Invalid native intent generation")
        route, values = create_string_buffer(binding.pack()), create_string_buffer(parameters.pack())
        with self._lock:
            if not self._handle:
                raise RuntimeError("Native media broker is closed")
            return bool(
                self.api.broker_publish(self._handle, cast(route, c_void_p), 360, cast(values, c_void_p), generation)
            )

    def reports(self) -> tuple[NativeReport, ...]:
        buffer = create_string_buffer(_REPORT.size * 16)
        with self._lock:
            if not self._handle:
                return ()
            count = int(self.api.broker_reports(self._handle, cast(buffer, c_void_p), 16))
            if not count and get_last_error():
                raise _native_error("report query")
            if count > 16:
                raise ValueError("Native report count exceeds its buffer")
            return tuple(
                NativeReport.unpack(buffer.raw[i * _REPORT.size : (i + 1) * _REPORT.size]) for i in range(count)
            )

    def close(self) -> None:
        with self._lock:
            if self._handle:
                handle, self._handle = self._handle, 0
                self.api.broker_destroy(handle)

    def __enter__(self) -> NativeBroker:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
