"""Bookkeeping for `connector_runs` — what the Source Status Panel (Section 11.9) reads to show
which connectors are healthy, delayed, or down. Every job in services/jobs.py wraps its work
with start_run/finish_run so that panel reflects real activity instead of the `NULL`s a fresh
database starts with.
"""
from __future__ import annotations

import sqlite3

from connectors.base import utcnow_iso


def start_run(conn: sqlite3.Connection, source_id: str) -> int:
    cur = conn.execute(
        "INSERT INTO connector_runs (source_id, started_at, status) VALUES (?, ?, 'running')",
        (source_id, utcnow_iso()),
    )
    conn.commit()
    return cur.lastrowid


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    status: str,
    records_fetched: int = 0,
    records_written: int = 0,
    error_message: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE connector_runs
        SET finished_at = ?, status = ?, records_fetched = ?, records_written = ?, error_message = ?
        WHERE id = ?
        """,
        (utcnow_iso(), status, records_fetched, records_written, error_message, run_id),
    )
    conn.commit()
