"""Reads price observations out of SQLite and drives services/top100.py's pure ranking
functions, writing the result into `top100_snapshots` — the background job Section 9 asks for
("pre-compute the aggregates... so switching time ranges is instant"). Kept separate from
top100.py itself so that module stays DB-free and independently unit-testable.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

from connectors.base import utcnow_iso
from services.top100 import (
    TIME_RANGE_TO_TIMEDELTA,
    CardSeries,
    Observation,
    RankingSettings,
    period_for_range,
    rank_top100,
)

SORT_KEYS = ("change_pct", "change_abs", "volume")


def _parse_iso(value: str) -> datetime:
    # SQLite stores our own "%Y-%m-%dT%H:%M:%S.%fZ" writes; Python 3.11+'s fromisoformat
    # handles the trailing 'Z' directly.
    return datetime.fromisoformat(value)


def _format_bound(dt: datetime) -> str:
    """Formats a query boundary to match exactly how observed_at is written to the DB
    (utcnow_iso(), '...ffffffZ'). SQLite's BETWEEN on these columns is a plain string
    comparison — `datetime.isoformat()` would emit '+00:00' instead of 'Z', and comparing a
    'Z'-suffixed stored value against a '+00:00'-suffixed bound silently miscompares whenever
    the two are otherwise identical (e.g. a period_end of "now" against a snapshot written in
    that same instant), because 'Z' sorts after '+' character-by-character. Same format on both
    sides makes the comparison a correct chronological comparison, not just usually-correct."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def load_card_series(
    conn: sqlite3.Connection, period_start: datetime, period_end: datetime
) -> list[CardSeries]:
    """Today this reads only `price_snapshots` (see DATA_SOURCES.md §0 for why `sales` is empty).
    The day a real sold-price connector exists, this is the only function that needs to change —
    union in a second query over non-excluded `sales` rows — everything downstream (top100.py,
    the API route) is already agnostic to where the observations came from.
    """
    rows = conn.execute(
        """
        SELECT card_id, grade_id, observed_at, price_eur
        FROM price_snapshots
        WHERE observed_at BETWEEN ? AND ? AND price_eur IS NOT NULL
        ORDER BY card_id, grade_id, observed_at
        """,
        (_format_bound(period_start), _format_bound(period_end)),
    ).fetchall()

    grouped: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    for row in rows:
        key = (row["card_id"], row["grade_id"])
        grouped[key].append(Observation(observed_at=_parse_iso(row["observed_at"]), price_eur=row["price_eur"]))

    return [CardSeries(card_id=cid, grade_id=gid, observations=tuple(obs)) for (cid, gid), obs in grouped.items()]


def load_ranking_settings(conn: sqlite3.Connection) -> RankingSettings:
    """Section 2: minimum-sales threshold must be adjustable in Settings. Reads from `settings`
    (key/value, Section 12) and falls back to RankingSettings' defaults when unset."""
    row = conn.execute("SELECT value FROM settings WHERE key = 'top100_min_observations'").fetchone()
    min_observations = int(row["value"]) if row else RankingSettings().min_observations
    row = conn.execute("SELECT value FROM settings WHERE key = 'top100_min_price_eur'").fetchone()
    min_price_eur = float(row["value"]) if row else RankingSettings().min_price_eur
    return RankingSettings(min_observations=min_observations, min_price_eur=min_price_eur)


def compute_and_store_top100(conn: sqlite3.Connection, now: datetime | None = None) -> dict[str, int]:
    """Computes every (time_range x sort_key) ranking and inserts a fresh batch of rows stamped
    with a shared `computed_at`. Old batches are left in place (a cheap history of past
    rankings) — the API route always reads the latest `computed_at` per (time_range, sort_key),
    so this needs no delete/replace step to stay correct.
    """
    now = now or datetime.now(timezone.utc)
    computed_at = utcnow_iso()
    settings = load_ranking_settings(conn)
    written = 0

    for time_range in TIME_RANGE_TO_TIMEDELTA:
        period_start, period_end = period_for_range(time_range, now)
        series = load_card_series(conn, period_start, period_end)
        for sort_key in SORT_KEYS:
            ranked = rank_top100(series, period_start, period_end, settings, sort_key=sort_key, limit=100)
            for rank, entry in enumerate(ranked, start=1):
                conn.execute(
                    """
                    INSERT INTO top100_snapshots (
                        time_range, computed_at, rank, card_id, grade_id,
                        start_price_eur, end_price_eur, change_pct, change_abs_eur,
                        observation_count, sort_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        time_range, computed_at, rank, entry.card_id, entry.grade_id,
                        entry.start_price_eur, entry.end_price_eur, entry.change_pct,
                        entry.change_abs_eur, entry.observation_count, sort_key,
                    ),
                )
                written += 1
    conn.commit()
    return {"computed_at": computed_at, "rows_written": written}
