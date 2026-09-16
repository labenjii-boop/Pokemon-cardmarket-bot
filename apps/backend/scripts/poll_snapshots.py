#!/usr/bin/env python3
"""Manual, one-off price-snapshot poll (both connectors) + Top 100 recompute — the same work
app/scheduler.py's `poll_snapshots`/`poll_tcgdex_snapshots` jobs do, runnable standalone (e.g.
right after scripts/import_catalog.py, so the Top 100 screen has data on first launch instead of
waiting on the scheduler). Safe to re-run any time — TCGdex's batch rotates to different cards
each run rather than repeating the same ones (see services/jobs.py).

    cd apps/backend && source .venv/bin/activate
    python scripts/poll_snapshots.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.db import get_connection, init_db
from services import jobs


def main() -> None:
    settings.ensure_directories()
    init_db().close()
    had_error = False
    total_written = 0

    with get_connection() as conn:
        result = jobs.poll_price_snapshots(conn)
        print(f"pokemontcg.io: fetched {result.get('fetched', 0)}, written {result.get('written', 0)}")
        if result.get("error"):
            print(f"  error: {result['error']}")
            had_error = True
        total_written += result.get("written", 0)

        result = jobs.poll_tcgdex_price_snapshots(conn)
        print(
            f"tcgdex: polled {result.get('cards_polled', 0)} cards, "
            f"fetched {result.get('fetched', 0)}, written {result.get('written', 0)}"
        )
        if result.get("error"):
            print(f"  error: {result['error']}")
            had_error = True
        total_written += result.get("written", 0)

        if total_written:
            top100_result = jobs.recompute_top100(conn)
            print(f"top100 recomputed: {top100_result['rows_written']} rows at {top100_result['computed_at']}")

    if had_error and not total_written:
        sys.exit(1)


if __name__ == "__main__":
    main()
