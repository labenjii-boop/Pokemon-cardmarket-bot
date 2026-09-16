#!/usr/bin/env python3
"""Manual, one-off price-snapshot poll + Top 100 recompute — the same work
app/scheduler.py's `poll_snapshots` job does, runnable standalone (e.g. right after
scripts/import_catalog.py, so the Top 100 screen has data on first launch instead of waiting up
to 6 hours for the first scheduled poll).

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
    with get_connection() as conn:
        result = jobs.poll_price_snapshots(conn)
        print(f"price snapshots: fetched {result.get('fetched', 0)}, written {result.get('written', 0)}")
        if result.get("error"):
            print(f"error: {result['error']}")
            sys.exit(1)
        if result.get("written"):
            top100_result = jobs.recompute_top100(conn)
            print(f"top100 recomputed: {top100_result['rows_written']} rows at {top100_result['computed_at']}")


if __name__ == "__main__":
    main()
