#!/usr/bin/env python3
"""One-time 10-year FX history backfill (Section 6) via the ECB SDMX historical series endpoint
— separate from the day-to-day `sync_fx_rates` job because it's a heavier, once-ever pull per
currency rather than something to repeat on every scheduled run.

    cd apps/backend && source .venv/bin/activate
    python scripts/backfill_fx_history.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.db import get_connection, init_db
from connectors.ecb_fx import EcbFxConnector

# Currencies the app actually needs: DKK (display currency), USD (TCGplayer/most eBay listings),
# JPY/GBP/CNY (Japanese, UK, and Chinese marketplace prices, for when those connectors exist).
CURRENCIES = ["USD", "DKK", "JPY", "GBP", "CNY"]


def main() -> None:
    settings.ensure_directories()
    init_db().close()
    connector = EcbFxConnector()
    written = 0
    try:
        with get_connection() as conn:
            for rate_date, currency, rate in connector.fetch_full_history(CURRENCIES):
                conn.execute(
                    "INSERT OR REPLACE INTO fx_rates (rate_date, currency, eur_rate, source) VALUES (?, ?, ?, 'ecb')",
                    (rate_date, currency, rate),
                )
                written += 1
            conn.commit()
    finally:
        connector.close()
    print(f"fx rate rows written: {written}")


if __name__ == "__main__":
    main()
