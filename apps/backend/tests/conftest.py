import sqlite3
from pathlib import Path

import pytest

from app.db import _ensure_fts

SCHEMA_PATH = Path(__file__).parent.parent / "app" / "schema.sql"
SEED_PATH = Path(__file__).parent.parent / "app" / "seed_grades.sql"


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
