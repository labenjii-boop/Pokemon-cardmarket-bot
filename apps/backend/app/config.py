"""App-wide configuration.

Single local user, no server deployment (Section 1/10) — this reads defaults, then a JSON
settings file, then environment variables (highest priority, for development). There is no
remote config and nothing here is ever sent anywhere.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


APP_NAME = "Pokemon Card Tracker"
BACKEND_HOST = "127.0.0.1"  # localhost only — the sidecar is never exposed to the network
BACKEND_PORT = 8756


def app_support_dir() -> Path:
    """~/Library/Application Support/<app name>/ on macOS (Section 10).

    Falls back to a XDG-style path when not running on macOS (this repo's CI and any
    Linux/Windows dev use), so the backend is runnable outside a packaged macOS app too.
    """
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME


@dataclass(frozen=True)
class Settings:
    app_support_dir: Path = field(default_factory=app_support_dir)

    @property
    def db_path(self) -> Path:
        return self.app_support_dir / "database.sqlite3"

    @property
    def image_cache_dir(self) -> Path:
        return self.app_support_dir / "images"

    @property
    def log_dir(self) -> Path:
        return self.app_support_dir / "logs"

    @property
    def backup_dir(self) -> Path:
        return self.app_support_dir / "backups"

    @property
    def settings_file(self) -> Path:
        """Non-secret local settings (currency toggle, thresholds, etc). API keys never live
        here — those go in the macOS Keychain (Section 10)."""
        return self.app_support_dir / "settings.json"

    def ensure_directories(self) -> None:
        for d in (self.app_support_dir, self.image_cache_dir, self.log_dir, self.backup_dir):
            d.mkdir(parents=True, exist_ok=True)

    def load_local_settings(self) -> dict:
        if not self.settings_file.exists():
            return {}
        return json.loads(self.settings_file.read_text())

    def save_local_settings(self, data: dict) -> None:
        self.settings_file.write_text(json.dumps(data, indent=2))


settings = Settings()
