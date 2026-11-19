"""Build the optional Media V2 DSP library for x64 Windows."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "src/core/widgets/services/media/native"


def build(output: Path, *, test_hooks: bool = False) -> Path:
    from tests.win32.msvc import find_toolchain

    toolchain = find_toolchain()
    if toolchain.target != "x64":
        raise RuntimeError("The Media V2 DSP build requires x64 Windows")
    env = dict(toolchain.env)
    compiler = shutil.which("cl.exe", path=env.get("PATH") or env.get("Path"))
    if compiler is None:
        raise RuntimeError("MSVC compiler unavailable")
    output.mkdir(parents=True, exist_ok=True)
    inputs = sorted(p for p in NATIVE.rglob("*") if p.suffix in (".cpp", ".h"))
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    build_id = hashlib.sha256(
        json.dumps({"inputs": hashes, "test_hooks": test_hooks}, sort_keys=True).encode()
    ).hexdigest()[:16]
    dll = output / "YASBMediaProcessor.dll"
    command = [
        compiler,
        "/nologo",
        "/std:c++17",
        "/EHsc",
        "/O2",
        "/MT",
        "/W4",
        "/WX",
        "/utf-8",
        "/LD",
        "/DYASB_DSP_EXPORTS",
        *(["/DYASB_DSP_TEST_HOOKS"] if test_hooks else []),
        f"/DYASB_DSP_BUILD_ID=0x{build_id}ULL",
        *(str(source) for source in sorted(NATIVE.glob("*.cpp"))),
        f"/Fe:{dll}",
        "/link",
        "/DYNAMICBASE",
        "/NXCOMPAT",
        "advapi32.lib",
        "bcrypt.lib",
    ]
    result = subprocess.run(command, cwd=output, env=env, capture_output=True, text=True, check=False)
    print(result.stdout + result.stderr)
    result.check_returncode()
    notices = output / "licenses/xaymar-vst2"
    notices.mkdir(parents=True, exist_ok=True)
    for name in ("LICENSE", "README.md", "vst.h"):
        shutil.copyfile(NATIVE / "vendor/xaymar-vst2" / name, notices / name)
    receipt = {
        "command": command,
        "cwd": str(output),
        "toolchain": toolchain.description,
        "build_id": build_id,
        "inputs": hashes,
        "sha256": hashlib.sha256(dll.read_bytes()).hexdigest(),
        "test_hooks": test_hooks,
        "installed": False,
        "activated": False,
    }
    (output / "build.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return dll


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/media-dsp")
    print(build(parser.parse_args().output.resolve()))
