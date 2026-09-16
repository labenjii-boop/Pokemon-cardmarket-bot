#!/usr/bin/env python3
"""Manual, one-off catalog import — run this once before first launch so the Top 100 screen and
search have something to show, rather than waiting for the weekly scheduled refresh
(app/scheduler.py) to happen on its own. Safe to re-run any time; every write is an upsert.

    cd apps/backend && source .venv/bin/activate
    python scripts/import_catalog.py
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
        result = jobs.import_catalog(conn)
    print(f"pokemontcg.io: {result['pokemontcg_io']} cards")
    print(f"tcgdex: {result['tcgdex']} cards")
    if result["errors"]:
        print("errors:")
        for err in result["errors"]:
            print(f"  - {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
