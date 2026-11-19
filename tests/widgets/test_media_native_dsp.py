"""Real x64 DLL + native host, synthetic buffers only; no playback or APO setup."""

import cmath
import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from build_media_dsp import build
from tests.win32.msvc import ToolchainMissing, find_toolchain

FREQUENCIES = (32, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
pytestmark = pytest.mark.sdk


@pytest.fixture(scope="module")
def native_host(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    try:
        toolchain = find_toolchain()
    except ToolchainMissing as exc:
        if os.environ.get("YASB_REQUIRE_SDK", "") not in ("", "0"):
            pytest.fail(f"Native media DSP checks require MSVC/Windows SDK: {exc}")
        pytest.skip(f"Native media DSP needs MSVC/Windows SDK; CI requires it ({exc})")
    output = tmp_path_factory.mktemp("media-native-dsp")
    dll = build(output)
    env = dict(toolchain.env)
    compiler = shutil.which("cl.exe", path=env.get("PATH") or env.get("Path"))
    assert compiler is not None
    source = Path(__file__).with_name("native_media_dsp_host.cpp")
    exe = output / "offline_host.exe"
    result = subprocess.run(
        [compiler, "/nologo", "/std:c++17", "/EHsc", "/O2", "/MT", "/W4", "/WX", "/utf-8", str(source), f"/Fe:{exe}"],
        cwd=output,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return exe, dll


def run_case(native_host: tuple[Path, Path], *arguments: object) -> dict[str, Any]:
    exe, dll = native_host
    result = subprocess.run(
        [str(exe), str(dll), *(str(arg) for arg in arguments)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def peak_response(rate: int, centre: float, frequency: float, gain: float) -> float:
    # Independent transfer-function oracle (the native code uses time-domain DF2).
    a = 10 ** (gain / 40)
    w = 2 * math.pi * centre / rate
    alpha = math.sin(w) / 2
    z = cmath.exp(-2j * math.pi * frequency / rate)
    numerator = (1 + alpha * a) - 2 * math.cos(w) * z + (1 - alpha * a) * z * z
    denominator = (1 + alpha / a) - 2 * math.cos(w) * z + (1 - alpha / a) * z * z
    return abs(numerator / denominator)


@pytest.mark.parametrize("band", range(10))
@pytest.mark.parametrize("factor", [0.5, 1])
def test_all_ten_q1_filters_match_frequency_response(native_host: tuple[Path, Path], band: int, factor: float) -> None:
    frequency = FREQUENCIES[band] * factor
    result = run_case(native_host, "eq", 48000, band, frequency, 6)
    assert result["ratio"] == pytest.approx(peak_response(48000, FREQUENCIES[band], frequency, 6), rel=2e-4)


@pytest.mark.parametrize("rate", [44100, 48000, 88200, 96000, 176400, 192000])
@pytest.mark.parametrize("band", [0, 5, 9])
def test_supported_rates_and_extreme_cuts(native_host: tuple[Path, Path], rate: int, band: int) -> None:
    result = run_case(native_host, "eq", rate, band, FREQUENCIES[band], -12)
    assert result["ratio"] == pytest.approx(10 ** (-12 / 20), rel=2e-4)
    assert result["rate"] == rate


@pytest.mark.parametrize(
    ("flags", "balance", "left", "right"),
    [
        (0, 0, 0.25, -0.75),
        (0, 1, 0, -0.75),
        (0, -1, 0.25, 0),
        (0, 0.5, 0.125, -0.75),
        (2, 0, -0.75, 0.25),
        (2, -0.5, -0.75, 0.125),
        (1, 1, -0.25, -0.25),
        (3, -1, -0.25, -0.25),
    ],
)
def test_stereo_matrix_order_and_mono_balance_exclusion(
    native_host: tuple[Path, Path],
    flags: int,
    balance: float,
    left: float,
    right: float,
) -> None:
    result = run_case(native_host, "matrix", flags, balance)
    assert result["left"] == pytest.approx(left, abs=1e-7)
    assert result["right"] == pytest.approx(right, abs=1e-7)


@pytest.mark.parametrize("case", ["protocol", "lifecycle", "mailbox", "concurrent", "finite-in-place", "accumulating"])
def test_native_abi_state_and_bounded_publication(native_host: tuple[Path, Path], case: str) -> None:
    result = run_case(native_host, case)
    assert result


@pytest.mark.parametrize(
    ("mode", "first", "settled"),
    [(1, 0.9997680082, 0.06227098197), (2, 0.9968134628, 0.02154434690)],
)
def test_compressor_mean_square_knee_and_no_makeup(
    native_host: tuple[Path, Path], mode: int, first: float, settled: float
) -> None:
    unit = run_case(native_host, "compressor", 48000, mode, 1)
    quiet = run_case(native_host, "compressor", 48000, mode, 0.1)
    assert unit["first"] == pytest.approx(first, abs=1e-9)
    assert quiet["settled"] == pytest.approx(settled, abs=1e-8)


@pytest.mark.parametrize("rate", [44100, 48000, 88200, 96000, 176400, 192000])
def test_limiter_exact_delay_and_linked_stereo(native_host: tuple[Path, Path], rate: int) -> None:
    result = run_case(native_host, "limiter", rate)
    assert result["delay"] == math.floor(0.005 * rate) - 1
    assert result["left"] == pytest.approx(10 ** (-1 / 20), abs=1e-9)
    assert result["right"] == pytest.approx(result["left"] / 2, abs=1e-9)


@pytest.mark.parametrize("mode", [0, 1, 2])
def test_dynamics_chain_is_partition_invariant(native_host: tuple[Path, Path], mode: int) -> None:
    results = [run_case(native_host, "dynamics", mode, block) for block in (1, 31, 256, 1024)]
    assert all(row == results[0] for row in results)
    if mode == 1:
        assert results[0]["attenuation_db"] == pytest.approx(-10.908707, abs=0.4)
    elif mode == 0:
        assert results[0]["attenuation_db"] == pytest.approx(0, abs=1e-9)


def test_bypass_freezes_history_and_has_no_delay(native_host: tuple[Path, Path]) -> None:
    assert run_case(native_host, "bypass") == {"bypass_immediate": True, "history_frozen": True}


def test_night_mode_leaves_quiet_material_unchanged(native_host: tuple[Path, Path]) -> None:
    assert abs(run_case(native_host, "quiet-night")["attenuation_db"]) < 0.1


@pytest.mark.parametrize("lowering", [False, True])
def test_limiter_ceiling_switch_retains_each_samples_original_requirement(
    native_host: tuple[Path, Path], lowering: bool
) -> None:
    result = run_case(native_host, "limiter-switch", int(lowering))
    before = 10 ** ((-0.1 if lowering else -1) / 20)
    after = 10 ** ((-1 if lowering else -0.1) / 20)
    assert result["left"] == pytest.approx(min(before, after), abs=1e-9)
    assert result["right"] == pytest.approx(before / 2, abs=1e-9)


def test_adaptive_scalar_math(native_host: tuple[Path, Path]) -> None:
    result = run_case(native_host, "adaptive-scalars")
    assert result["weights"] == pytest.approx([0, 1, 1, 0, 0.5, 0.5], abs=1e-9)
    assert result["bass"] == pytest.approx([1, 0.5, 0], abs=1e-9)
    assert result["correction"] == pytest.approx(
        [-0.622749, -1.929076, -3.931054, 0.616112, 1.748349, 2.750421], abs=1e-6
    )


@pytest.mark.parametrize("mode", [0, 1, 2])
def test_fft_power_is_stereo_energy_and_cannot_cancel(native_host: tuple[Path, Path], mode: int) -> None:
    result = run_case(native_host, "spectrum", mode)
    assert result["observations"] == 2
    assert result["total"] == pytest.approx(0.0025 if mode == 1 else 0.005, rel=1e-6)


@pytest.mark.parametrize("mode", ["silence", "dc", "quiet", "low", "dc-tone"])
def test_adaptive_admission_rejects_dc_but_retains_useful_quiet_material(
    native_host: tuple[Path, Path], mode: str
) -> None:
    result = run_case(native_host, "adaptive-learning", mode)
    assert result["observations"] > 0
    assert (result["admitted"] > 0) == (mode in ("low", "dc-tone"))
    if mode in ("silence", "dc", "quiet"):
        assert result["makeup"] == 0


def deviation(powers: list[float]) -> float:
    frequencies = [1000 * 2 ** ((band - 14) / 3) for band in range(27)]
    weights = [
        0
        if f <= 50 or f >= 16000
        else 0.5 - 0.5 * math.cos(math.pi * math.log2(f / 50))
        if f < 100
        else 1
        if f <= 10000
        else 0.5 + 0.5 * math.cos(math.pi * math.log(f / 10000) / math.log(1.6))
        for f in frequencies
    ]
    shape = [10 * math.log10(p + 1e-20) + 2.5 * math.log2(f / 1000) for p, f in zip(powers, frequencies)]
    centre = sum(w * s for w, s in zip(weights, shape)) / sum(weights)
    return math.sqrt(sum(w * (s - centre) ** 2 for w, s in zip(weights, shape)) / sum(weights))


def test_adaptive_eq_learns_and_reduces_coloration(native_host: tuple[Path, Path]) -> None:
    result = run_case(native_host, "adaptive-learning", "colored")
    assert result["admitted"] > 40
    assert deviation(result["output"]) < 0.85 * deviation(result["input"])
    frequencies = [1000 * 2 ** ((band - 14) / 3) for band in range(27)]
    weights = [independent_k_power(f) for f in frequencies]
    original = sum(w * p for w, p in zip(weights, result["input"]))
    processed = sum(w * p for w, p in zip(weights, result["output"]))
    assert abs(10 * math.log10(processed / original)) < 1


def independent_k_power(frequency: float) -> float:
    z = cmath.exp(-2j * math.pi * frequency / 48000)
    w = 2 * math.pi * 38.13 / 48000
    c, alpha = math.cos(w), math.sin(w) / (2 * 0.5003)
    numerator = (1 + c) / 2 - (1 + c) * z + (1 + c) / 2 * z * z
    denominator = 1 + alpha - 2 * c * z + (1 - alpha) * z * z
    highpass = abs(numerator / denominator) ** 2
    a = 10 ** (3.9998 / 40)
    w = 2 * math.pi * 1681.97 / 48000
    c = math.cos(w)
    beta = 2 * math.sqrt(a) * math.sin(w) / (2 * 0.7072)
    numerator = (
        a * (a + 1 + (a - 1) * c + beta) - 2 * a * (a - 1 + (a + 1) * c) * z + a * (a + 1 + (a - 1) * c - beta) * z * z
    )
    denominator = a + 1 - (a - 1) * c + beta + 2 * (a - 1 - (a + 1) * c) * z + (a + 1 - (a - 1) * c - beta) * z * z
    return highpass * abs(numerator / denominator) ** 2


def test_adaptive_disable_decays_and_reenable_resets(native_host: tuple[Path, Path]) -> None:
    assert run_case(native_host, "adaptive-learning", "reset") == {"decayed_neutral": True, "reenable_resets": True}


def test_adaptive_processing_is_causal_partition_invariant_and_replaces_manual_curve(
    native_host: tuple[Path, Path],
) -> None:
    results = [run_case(native_host, "adaptive-partition", block, 0) for block in (1, 31, 256, 1024)]
    assert all(result == results[0] for result in results)
    assert run_case(native_host, "adaptive-partition", 256, 12) == results[0]


@pytest.mark.parametrize("rate", [44100, 48000, 88200, 96000, 176400, 192000])
def test_adaptive_all_supported_rates_are_finite_and_learn(native_host: tuple[Path, Path], rate: int) -> None:
    result = run_case(native_host, "adaptive-rate", rate)
    assert result["admitted"] > 0
    assert result["observed"] == (8 * rate - 16384) // 8192 + 1


def test_adaptive_only_enables_true_safety_limiter(native_host: tuple[Path, Path]) -> None:
    result = run_case(native_host, "adaptive-safety")
    assert result["left"] == pytest.approx(10 ** (-0.1 / 20), abs=1e-7)
    assert result["right"] == pytest.approx(result["left"] / 2, abs=1e-7)


@pytest.mark.parametrize("db", [-24, -6, 0, 12])
@pytest.mark.parametrize("bypassed", [False, True])
def test_native_preamp_ramp_and_bypass(native_host: tuple[Path, Path], db: int, bypassed: bool) -> None:
    result = run_case(native_host, "preamp", db, int(bypassed))
    gain = 1 if bypassed else 10 ** (db / 20)
    assert result["left"] == pytest.approx(0.25 * gain, rel=1e-6)
    assert result["right"] == pytest.approx(-0.75 * gain, rel=1e-6)
