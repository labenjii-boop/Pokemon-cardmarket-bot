#!/usr/bin/env python3
"""Manual, one-off price-snapshot poll + Top 100 recompute — the same work
app/scheduler.py's poll jobs do, runnable standalone (e.g. right after
scripts/import_catalog.py, so the Top 100 screen has data on first launch instead of waiting on
the scheduler). Safe to re-run any time — TCGdex's batch rotates to different cards each run
rather than repeating the same ones (see services/jobs.py).

TCGdex runs first and is what this script actually depends on: it has, in practice, been the
reliable source for both catalog and pricing (English included, not just Japanese/Chinese).
pokemontcg.io runs after it as a best-effort bonus — its free tier has been unreliable in
practice (DATA_SOURCES.md §1), so a failure there is logged quietly rather than reported as
something to worry about; it doesn't block anything TCGdex already provided.

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
    total_written = 0

    with get_connection() as conn:
        # Bigger batch than the scheduled hourly job (services/jobs.py's default 300) since this
        # is a one-off manual run, not a recurring background poll — better to cover more ground
        # in the one shot someone's actually sitting there watching.
        result = jobs.poll_tcgdex_price_snapshots(conn, batch_size=800)
        print(
            f"tcgdex: polled {result.get('cards_polled', 0)} cards, "
            f"fetched {result.get('fetched', 0)}, written {result.get('written', 0)}"
        )
        if result.get("error"):
            print(f"  (had an error partway through, but kept whatever it got before that: {result['error']})")
        total_written += result.get("written", 0)

        result = jobs.poll_price_snapshots(conn)
        if result.get("written") or not result.get("error"):
            print(f"pokemontcg.io: fetched {result.get('fetched', 0)}, written {result.get('written', 0)}")
        else:
            # Best-effort secondary source — its free tier has been unreliable in practice, so a
            # failure here isn't presented as something needing attention. See Source Status in
            # the app if you want the detail.
            print("pokemontcg.io: skipped (currently unreliable — see Source Status in the app)")
        total_written += result.get("written", 0)

        if total_written:
            top100_result = jobs.recompute_top100(conn)
            print(f"top100 recomputed: {top100_result['rows_written']} rows at {top100_result['computed_at']}")
        else:
            print("no price data written this run — nothing to recompute Top 100 from yet")


if __name__ == "__main__":
    main()
