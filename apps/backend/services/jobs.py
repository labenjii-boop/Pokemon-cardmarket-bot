"""The actual units of work the scheduler (app/scheduler.py) and the manual CLI scripts
(scripts/) both call. Kept here, independent of both, so they can be unit-tested directly and
so "run this from a cron-like scheduler" vs. "run this once from a terminal" are just two
different callers of the same function.

Every job wraps its connector call with services/connector_runs.py bookkeeping so
`GET /sources/status` (Section 11.9) reflects what actually happened, including failures.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, timedelta

from app.secrets import get_secret
from connectors.ecb_fx import EcbFxConnector
from connectors.pokemontcg_io import PokemonTcgIoConnector
from connectors.tcgdex import TcgdexConnector
from services.connector_runs import finish_run, start_run
from services.ingest import ingest_catalog_sets, ingest_price_observations, upsert_card
from services.top100_job import compute_and_store_top100

logger = logging.getLogger("jobs")


def sync_fx_rates(conn: sqlite3.Connection, days: int = 90) -> dict:
    """The free ECB feed used here (eurofxref-hist-90d.xml) only covers a rolling 90 days —
    fine for a job that runs at least that often. A one-time 10-year backfill uses
    EcbFxConnector.fetch_full_history instead (see scripts/backfill_fx_history.py)."""
    run_id = start_run(conn, "ecb_fx")
    connector = EcbFxConnector()
    written = 0
    try:
        end = date.today()
        start = end - timedelta(days=days)
        for rate_date, currency, rate in connector.fetch_rates(start.isoformat(), end.isoformat()):
            conn.execute(
                "INSERT OR REPLACE INTO fx_rates (rate_date, currency, eur_rate, source) VALUES (?, ?, ?, 'ecb')",
                (rate_date, currency, rate),
            )
            written += 1
        conn.commit()
        finish_run(conn, run_id, "ok", records_fetched=written, records_written=written)
        return {"written": written}
    except Exception as exc:  # noqa: BLE001 — this is a job boundary, log and record, don't crash the scheduler
        conn.rollback()
        finish_run(conn, run_id, "error", error_message=str(exc))
        logger.exception("fx sync failed")
        return {"written": 0, "error": str(exc)}
    finally:
        connector.close()


def _import_from_connector(conn: sqlite3.Connection, source_id: str, connector) -> tuple[int, list[str]]:
    """Shared by both catalog connectors: fetch every set, then every card in each set. A set
    that fails (a transient error retries already exhausted, an id the connector mishandles,
    etc.) is recorded and skipped rather than aborting the whole source — losing every
    already-imported set because one later set failed was the actual bug behind the first real
    run's "0 cards" result."""
    card_count = 0
    set_errors: list[str] = []
    set_ids = ingest_catalog_sets(conn, connector.fetch_sets())
    for key in set_ids:
        _, source_set_id = key.split(":", 1)
        try:
            for card in connector.fetch_cards(source_set_id):
                upsert_card(conn, card, set_ids[key])
                card_count += 1
        except Exception as exc:  # noqa: BLE001 — one bad set must not lose every other set
            set_errors.append(f"{source_id}/{source_set_id}: {exc}")
            logger.warning("%s: failed to import set %s: %s", source_id, source_set_id, exc)
    return card_count, set_errors


def import_catalog(conn: sqlite3.Connection) -> dict:
    """Full catalog refresh across both catalog connectors. This is the heavy, infrequent job
    (Section 13 Phase 2/3) — new sets appear a handful of times a year, not daily."""
    totals = {"pokemontcg_io": 0, "tcgdex": 0, "errors": []}

    api_key = get_secret("pokemontcg_io_api_key")
    pk_connector = PokemonTcgIoConnector(api_key=api_key)
    run_id = start_run(conn, "pokemontcg_io")
    try:
        card_count, set_errors = _import_from_connector(conn, "pokemontcg_io", pk_connector)
        conn.commit()
        totals["pokemontcg_io"] = card_count
        totals["errors"].extend(set_errors)
        finish_run(
            conn, run_id, "ok" if not set_errors else "error",
            records_fetched=card_count, records_written=card_count,
            error_message="; ".join(set_errors) or None,
        )
    except Exception as exc:  # noqa: BLE001 — fetch_sets itself failed; nothing to salvage
        conn.rollback()
        finish_run(conn, run_id, "error", error_message=str(exc))
        totals["errors"].append(f"pokemontcg_io: {exc}")
        logger.exception("pokemontcg.io catalog import failed")
    finally:
        pk_connector.close()

    tcgdex_connector = TcgdexConnector()
    run_id = start_run(conn, "tcgdex")
    try:
        card_count, set_errors = _import_from_connector(conn, "tcgdex", tcgdex_connector)
        conn.commit()
        totals["tcgdex"] = card_count
        totals["errors"].extend(set_errors)
        finish_run(
            conn, run_id, "ok" if not set_errors else "error",
            records_fetched=card_count, records_written=card_count,
            error_message="; ".join(set_errors) or None,
        )
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        finish_run(conn, run_id, "error", error_message=str(exc))
        totals["errors"].append(f"tcgdex: {exc}")
        logger.exception("TCGdex catalog import failed")
    finally:
        tcgdex_connector.close()

    return totals


def poll_price_snapshots(conn: sqlite3.Connection) -> dict:
    """The frequent job: today's market-price snapshot for every catalogued English card
    (DATA_SOURCES.md §0). Run interval is a tradeoff against pokemontcg.io's free-tier daily
    request cap — see app/scheduler.py's module docstring for the reasoning behind the default."""
    run_id = start_run(conn, "pokemontcg_io")
    api_key = get_secret("pokemontcg_io_api_key")
    connector = PokemonTcgIoConnector(api_key=api_key)
    try:
        observations = list(connector.fetch_observations())
        written = ingest_price_observations(conn, "pokemontcg_io", observations)
        conn.commit()
        finish_run(conn, run_id, "ok", records_fetched=len(observations), records_written=written)
        return {"fetched": len(observations), "written": written}
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        finish_run(conn, run_id, "error", error_message=str(exc))
        logger.exception("price snapshot poll failed")
        return {"fetched": 0, "written": 0, "error": str(exc)}
    finally:
        connector.close()


def recompute_top100(conn: sqlite3.Connection) -> dict:
    return compute_and_store_top100(conn)
