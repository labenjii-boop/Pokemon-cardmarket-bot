"""Process entry point — what actually runs, both in `python -m app.entrypoint` dev mode and as
the PyInstaller-built Tauri sidecar binary (Section 10). Binds to localhost only; nothing here
is ever reachable from outside the machine.
"""
from __future__ import annotations

import uvicorn

from app.config import BACKEND_HOST, BACKEND_PORT


def main() -> None:
    uvicorn.run("app.main:app", host=BACKEND_HOST, port=BACKEND_PORT, log_level="info")


if __name__ == "__main__":
    main()
