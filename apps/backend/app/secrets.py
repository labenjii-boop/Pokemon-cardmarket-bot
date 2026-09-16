"""Secret storage — the macOS Keychain (Section 10: "any free API keys stored in the macOS
Keychain... never in code"), via the cross-platform `keyring` package rather than shelling out
to `security` directly.

Two things this file works around:
  * PyInstaller freezes the app, and `keyring`'s normal backend auto-discovery relies on
    `importlib.metadata` entry points, which don't resolve inside a frozen binary. Explicitly
    selecting the macOS backend on darwin sidesteps that instead of relying on discovery.
  * Everywhere else (Linux/Windows dev machines, this repo's CI/sandbox), there may be no OS
    keyring available at all — `keyring` raises `KeyringError` in that case. Callers get `None`/
    `False` back rather than a crash; running without a stored key just means the connector
    falls back to its lower, unauthenticated rate limit (DATA_SOURCES.md §5), which is a
    perfectly normal thing for this app to do, not an error condition.
"""
from __future__ import annotations

import logging
import sys

import keyring
import keyring.errors

logger = logging.getLogger("secrets")

SERVICE_NAME = "Pokemon Card Tracker"

if sys.platform == "darwin":
    try:
        from keyring.backends import macOS

        keyring.set_keyring(macOS.Keyring())
    except Exception:  # noqa: BLE001 — best-effort; falls through to normal auto-discovery
        logger.warning("could not force the macOS keyring backend; falling back to auto-discovery")


def get_secret(key: str) -> str | None:
    try:
        return keyring.get_password(SERVICE_NAME, key)
    except keyring.errors.KeyringError:
        logger.warning("no OS keyring backend available; can't read %r", key)
        return None


def set_secret(key: str, value: str) -> bool:
    try:
        keyring.set_password(SERVICE_NAME, key, value)
        return True
    except keyring.errors.KeyringError:
        logger.warning("no OS keyring backend available; can't store %r", key)
        return False


def delete_secret(key: str) -> None:
    try:
        keyring.delete_password(SERVICE_NAME, key)
    except keyring.errors.KeyringError:
        pass
