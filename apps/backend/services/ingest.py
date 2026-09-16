"""Writes connector output into SQLite. Kept separate from the connectors themselves (Section
5c rule 6: connectors don't know about the DB) and separate from the ranking/currency logic —
this module's only job is "dataclass in, upserted row out."
"""
from __future__ import annotations

import sqlite3
from typing import Iterable

from connectors.base import CatalogCard, CatalogSet, PriceObservation
from services.currency import normalize


def upsert_set(conn: sqlite3.Connection, s: CatalogSet) -> str:
    internal_id = f"{s.language}-{s.source}-{s.source_set_id}"
    conn.execute(
        """
        INSERT INTO sets (id, source_set_id, source, name, name_original, series, era,
                           language, total_cards, release_date, set_code)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (source, source_set_id) DO UPDATE SET
            name = excluded.name, total_cards = excluded.total_cards,
            release_date = excluded.release_date
        """,
        (
            internal_id, s.source_set_id, s.source, s.name, s.name_original, s.series, s.era,
            s.language, s.total_cards, s.release_date, s.set_code,
        ),
    )
    row = conn.execute(
        "SELECT id FROM sets WHERE source = ? AND source_set_id = ?", (s.source, s.source_set_id)
    ).fetchone()
    return row["id"]


def upsert_card(conn: sqlite3.Connection, c: CatalogCard, set_internal_id: str) -> str:
    internal_id = f"{set_internal_id}-{c.number}"
    conn.execute(
        """
        INSERT INTO cards (id, set_id, source, source_card_id, name, name_original, name_en,
                            number, set_total, rarity, variant, language, release_date,
                            image_source_url, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        ON CONFLICT (source, source_card_id) DO UPDATE SET
            name = excluded.name, rarity = excluded.rarity, variant = excluded.variant,
            image_source_url = excluded.image_source_url,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
        """,
        (
            internal_id, set_internal_id, c.source, c.source_card_id, c.name, c.name_original,
            c.name_en, c.number, c.set_total, c.rarity, c.variant, c.language, c.release_date,
            c.image_source_url,
        ),
    )
    row = conn.execute(
        "SELECT id FROM cards WHERE source = ? AND source_card_id = ?", (c.source, c.source_card_id)
    ).fetchone()
    conn.execute(
        """
        INSERT INTO cards_fts (card_id, name, name_original, name_en, set_name)
        VALUES (?, ?, ?, ?, (SELECT name FROM sets WHERE id = ?))
        """,
        (row["id"], c.name, c.name_original, c.name_en, set_internal_id),
    )
    return row["id"]


def ingest_catalog_sets(conn: sqlite3.Connection, sets: Iterable[CatalogSet]) -> dict[str, str]:
    """Returns a map of (source, source_set_id) -> internal set id, for use by ingest_catalog_cards."""
    result: dict[str, str] = {}
    for s in sets:
        internal_id = upsert_set(conn, s)
        result[f"{s.source}:{s.source_set_id}"] = internal_id
    return result


def _resolve_grade_id(conn: sqlite3.Connection, grade_label: str | None) -> str:
    if grade_label is None:
        return "raw-nm"  # ungraded market price defaults to the "Near Mint" raw bucket
    row = conn.execute("SELECT id FROM grades WHERE label = ? LIMIT 1", (grade_label,)).fetchone()
    if row is None:
        raise ValueError(f"unknown grade label: {grade_label!r}")
    return row["id"]


def ingest_price_observations(
    conn: sqlite3.Connection, source_id: str, observations: Iterable[PriceObservation]
) -> int:
    """Writes PriceObservation rows into `price_snapshots` (or, when `is_transaction=True`, a
    future connector's rows go to `sales` instead — not implemented here since no such connector
    exists yet, see DATA_SOURCES.md §0). Skips rows whose currency has no FX rate on that date
    yet rather than failing the whole batch — normalization backfills once the rate lands.
    """
    written = 0
    for obs in observations:
        card_row = conn.execute(
            "SELECT id FROM cards WHERE source = ? AND source_card_id = ?",
            (obs.source, obs.card_source_id),
        ).fetchone()
        if card_row is None:
            continue  # catalog hasn't been imported for this card yet
        grade_id = _resolve_grade_id(conn, obs.grade_label)
        date = obs.observed_at[:10]
        # normalize() resolves EUR/DKK independently and returns None for whichever rate isn't
        # available yet, rather than failing the whole row (see services/currency.py).
        eur_amount, dkk_amount = normalize(conn, obs.price_amount, obs.price_currency, date)
        conn.execute(
            """
            INSERT INTO price_snapshots (card_id, grade_id, source_id, observed_at,
                                          price_amount, price_currency, price_eur, price_dkk, price_kind)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                card_row["id"], grade_id, source_id, obs.observed_at, obs.price_amount,
                obs.price_currency, eur_amount, dkk_amount, obs.price_kind,
            ),
        )
        written += 1
    return written
