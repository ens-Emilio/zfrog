#!/usr/bin/env python3
"""Build the desktop sidecar binary with PyInstaller.

Output: ``src-tauri/binaries/zfrog-api-<target-triple>``
(e.g. ``zfrog-api-x86_64-unknown-linux-gnu`` on Linux x64,
``zfrog-api-x86_64-pc-windows-msvc.exe`` on Windows).

Usage::

    python scripts/build-sidecar.py              # build for current host
    python scripts/build-sidecar.py --check      # verify the binary exists
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = ROOT / "src-tauri" / "binaries"
MIN_SIDECAR_BYTES = 10 * 1024 * 1024  # sanity: real onefile build is >10MB


def target_triple() -> str:
    machine = platform.machine().lower()
    arch = "x86_64" if machine in ("x86_64", "amd64", "x64") else machine
    if sys.platform == "win32":
        return f"{arch}-pc-windows-msvc"
    if sys.platform == "darwin":
        return f"{arch}-apple-darwin"
    return f"{arch}-unknown-linux-gnu"


def build() -> Path:
    triple = target_triple()
    out_name = f"zfrog-api-{triple}"
    if sys.platform == "win32":
        out_name += ".exe"

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BIN_DIR / out_name

    # Ensure PyInstaller is available
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller …", file=sys.stderr)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "PyInstaller>=6"])

    hidden = [
        "zfrog.desktop_entry",
        "zfrog.api",
        "zfrog.config",
        "zfrog.orchestrator",
        "zfrog.engines",
        "zfrog.engines.base",
        "zfrog.engines.playwright",
        "zfrog.engines.scrapy",
        "zfrog.engines.jump",
        "zfrog.engines.tongue",
        "zfrog.pipeline",
        "zfrog.pipeline.screenshot",
        "zfrog.pipeline.packager",
        "zfrog.pipeline.safety",
        "zfrog.ws",
        "zfrog.auth",
        "zfrog.probe",
        "zfrog.models",
        "zfrog.session",
        "zfrog.utils.stealth",
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "anyio",
        "starlette.middleware.cors",
    ]

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        out_name,
        "--distpath",
        str(BIN_DIR),
        "--workpath",
        str(ROOT / "build" / "pyinstaller"),
        "--specpath",
        str(ROOT / "build"),
        "--clean",
        "--noconfirm",
        "--collect-all",
        "fastapi",
        "--collect-all",
        "uvicorn",
        "--collect-all",
        "pydantic",
        "--collect-all",
        "pydantic_settings",
        "--collect-all",
        "anyio",
        "--collect-all",
        "starlette",
    ]
    for h in hidden:
        cmd += ["--hidden-import", h]

    cmd.append(str(ROOT / "src" / "zfrog" / "desktop_entry.py"))

    print(f"Building {out_name} …", file=sys.stderr)
    print(" ".join(cmd), file=sys.stderr)
    subprocess.check_call(cmd)

    candidates = list(BIN_DIR.glob("zfrog-api*"))
    print(f"Artifacts: {candidates}", file=sys.stderr)
    if not out_path.exists():
        print(f"✗ Expected {out_path} not found. Found: {candidates}", file=sys.stderr)
        sys.exit(1)
    size = out_path.stat().st_size
    if size < MIN_SIDECAR_BYTES:
        print(f"✗ {out_path} too small ({size} bytes) — build incomplete", file=sys.stderr)
        sys.exit(1)
    print(f"✓ {out_path} ({size / 1_048_576:.1f} MB)", file=sys.stderr)

    # Tauri expects a sidecar named `zfrog-api` (without triple) when running
    # `tauri dev` — keep a symlink/copy for dev.
    dev_link = BIN_DIR / ("zfrog-api.exe" if sys.platform == "win32" else "zfrog-api")
    try:
        if dev_link.exists() or dev_link.is_symlink():
            dev_link.unlink()
        if sys.platform == "win32":
            shutil.copy2(out_path, dev_link)
        else:
            dev_link.symlink_to(out_path.name)
        print(f"  dev link: {dev_link} -> {out_path.name}", file=sys.stderr)
    except OSError as e:
        print(f"  (dev link skipped: {e})", file=sys.stderr)

    return out_path


def check() -> None:
    triple = target_triple()
    out_name = f"zfrog-api-{triple}"
    if sys.platform == "win32":
        out_name += ".exe"
    p = BIN_DIR / out_name
    if not p.exists():
        print(f"✗ Missing {p}")
        print("  Run: python scripts/build-sidecar.py")
        sys.exit(1)
    size = p.stat().st_size
    if size < MIN_SIDECAR_BYTES:
        print(f"✗ {p} exists but too small ({size} bytes) — rebuild", file=sys.stderr)
        print("  Run: python scripts/build-sidecar.py", file=sys.stderr)
        sys.exit(1)
    print(f"✓ {p} ({size / 1_048_576:.1f} MB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="Verify binary exists")
    args = ap.parse_args()
    if args.check:
        check()
    else:
        build()
