#!/usr/bin/env python3
"""Builds the FastAPI backend into a single-file PyInstaller binary and names it the way Tauri's
sidecar mechanism requires: `<name>-<target-triple>[.exe]`, dropped into
`apps/desktop/src-tauri/binaries/` (Section 10: "detect the Mac's chip... build the Python
sidecar for that architecture").

Run this on the target Mac itself (once per architecture — Apple Silicon and Intel need separate
builds; there is no cross-compiling PyInstaller from Linux to macOS). From apps/backend/:

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python scripts/build_sidecar.py

The resulting binary is picked up automatically by `tauri build` / `tauri dev` via
`bundle.externalBin` in ../desktop/src-tauri/tauri.conf.json.
"""
from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent
DESKTOP_BINARIES_DIR = BACKEND_DIR.parent / "desktop" / "src-tauri" / "binaries"
BINARY_NAME = "pokemon-card-tracker-backend"


def rust_target_triple() -> str:
    """Mirrors `rustc -vV`'s host triple for the two macOS architectures Section 10 asks for.
    Uses `rustc` directly when available (most accurate); falls back to a platform.machine()
    guess so this script still runs in a plain Python environment without Rust installed.
    """
    try:
        output = subprocess.check_output(["rustc", "-vV"], text=True)
        for line in output.splitlines():
            if line.startswith("host:"):
                return line.split(":", 1)[1].strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    machine = platform.machine()
    if sys.platform == "darwin":
        return "aarch64-apple-darwin" if machine == "arm64" else "x86_64-apple-darwin"
    raise SystemExit(
        "Could not determine the Rust target triple and this isn't macOS. "
        "Run this script on the target Mac, or install Rust so `rustc -vV` is available."
    )


def main() -> None:
    triple = rust_target_triple()
    subprocess.check_call(
        [
            sys.executable, "-m", "PyInstaller",
            "--onefile",
            "--name", BINARY_NAME,
            "--distpath", str(BACKEND_DIR / "dist"),
            "--workpath", str(BACKEND_DIR / "build"),
            "--specpath", str(BACKEND_DIR / "build"),
            str(BACKEND_DIR / "app" / "entrypoint.py"),
        ]
    )

    DESKTOP_BINARIES_DIR.mkdir(parents=True, exist_ok=True)
    built = BACKEND_DIR / "dist" / BINARY_NAME
    target = DESKTOP_BINARIES_DIR / f"{BINARY_NAME}-{triple}"
    target.write_bytes(built.read_bytes())
    target.chmod(0o755)
    print(f"sidecar binary ready: {target}")


if __name__ == "__main__":
    main()
