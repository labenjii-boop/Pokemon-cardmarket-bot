"""Card search (Section 11.3), backed by the `cards_fts` FTS5 index that's kept in sync by
services/ingest.py's upsert_card. Split out from the route so it's testable without spinning up
the whole FastAPI app.
"""
from __future__ import annotations

import sqlite3


def _fts_match_query(q: str) -> str:
    """Builds an FTS5 MATCH expression: each whitespace-separated term becomes a quoted prefix
    match (so typing "char" finds "Charizard"), quotes doubled per FTS5's string-literal escaping
    so a stray `"` in the input can't break the query syntax."""
    terms = q.strip().split()
    escaped = [t.replace('"', '""') for t in terms]
    return " ".join(f'"{t}"*' for t in escaped)


def search_cards(conn: sqlite3.Connection, q: str, limit: int = 60) -> list[dict]:
    base_columns = """
        c.id, c.name, c.name_en, c.name_original, c.number, c.language, c.rarity, c.variant,
        c.image_source_url, s.name AS set_name, s.language AS set_language
    """
    if q.strip():
        rows = conn.execute(
            f"""
            SELECT {base_columns}
            FROM cards_fts
            JOIN cards c ON c.id = cards_fts.card_id
            JOIN sets s ON s.id = c.set_id
            WHERE cards_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (_fts_match_query(q), limit),
        ).fetchall()
    else:
        # No query yet: browse the most recently imported cards rather than showing nothing.
        rows = conn.execute(
            f"""
            SELECT {base_columns}
            FROM cards c
            JOIN sets s ON s.id = c.set_id
            ORDER BY c.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
