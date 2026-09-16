#!/usr/bin/env python3
"""Manual, one-off FX rate sync (last 90 days — the free ECB rolling feed's full range). Run
this once before first launch alongside import_catalog.py/poll_snapshots.py so currency
normalization (Section 8) has rates to work with immediately.

    cd apps/backend && source .venv/bin/activate
    python scripts/sync_fx.py
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
        result = jobs.sync_fx_rates(conn)
    print(f"fx rates written: {result.get('written', 0)}")
    if result.get("error"):
        print(f"error: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
