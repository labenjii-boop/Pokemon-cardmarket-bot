import sqlite3
import time
from pathlib import Path

import pytest

from app.db import _ensure_fts

SCHEMA_PATH = Path(__file__).parent.parent / "app" / "schema.sql"
SEED_PATH = Path(__file__).parent.parent / "app" / "seed_grades.sql"


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """connectors/_retry.py backs off with real time.sleep() between retries. Applied to every
    test automatically so a test exercising a retry path (persistent 5xx, etc.) can't
    accidentally cost several real seconds just because it forgot to mock sleep — a mistake this
    suite already made once (see test_jobs.py's import_catalog resilience test)."""
    monkeypatch.setattr(time, "sleep", lambda *_: None)


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text())
    conn.executescript(SEED_PATH.read_text())
    _ensure_fts(conn)
    yield conn
    conn.close()
