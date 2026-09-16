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
    observations = []
    fetch_error: str | None = None
    try:
        # Consumed one page at a time (not list(connector.fetch_observations())) so a page
        # failing partway through a run — this API has genuinely been flaky in practice, see
        # DATA_SOURCES.md §1 — keeps whatever earlier pages already succeeded instead of
        # discarding the whole run. Same bug class import_catalog had before it was fixed.
        for obs in connector.fetch_observations():
            observations.append(obs)
    except Exception as exc:  # noqa: BLE001 — stop paging, but keep what already came in
        fetch_error = str(exc)
        logger.warning("pokemontcg.io: stopped early after %d observations: %s", len(observations), exc)
    finally:
        connector.close()

    try:
        written = ingest_price_observations(conn, "pokemontcg_io", observations)
        conn.commit()
        finish_run(
            conn, run_id, "ok" if not fetch_error else "error",
            records_fetched=len(observations), records_written=written, error_message=fetch_error,
        )
        result = {"fetched": len(observations), "written": written}
        if fetch_error:
            result["error"] = fetch_error
        return result
    except Exception as exc:  # noqa: BLE001 — the DB write itself failed, not the fetch
        conn.rollback()
        finish_run(conn, run_id, "error", error_message=str(exc))
        logger.exception("price snapshot poll failed")
        return {"fetched": len(observations), "written": 0, "error": str(exc)}


def _select_cards_for_tcgdex_poll(conn: sqlite3.Connection, limit: int) -> list[str]:
    """TCGdex pricing costs one HTTP request per card (connectors/tcgdex.py), so a single run
    can't cover the whole catalog — this picks a rotating batch instead: cards with no
    tcgdex-sourced snapshot yet first, then whichever were observed longest ago. Run this
    regularly and coverage builds evenly across the whole catalog over many runs, rather than
    the same first N cards getting polled forever while the rest never get touched.

    Among "never observed yet" cards, newest sets first — not because older cards matter less,
    but because a real run surfaced 300 consecutive polls returning zero pricing: with no
    explicit tiebreaker, SQLite fell back to insertion order, i.e. whatever order the catalog
    import happened to process sets in, which has nothing to do with which cards are actually
    listed on TCGplayer/Cardmarket. Recently released cards are far likelier to have an active
    market listing than a 25-year-old set nobody's tracking prices for, so this at least biases
    early rotation batches toward cards likely to actually produce a price."""
    rows = conn.execute(
        """
        SELECT c.source_card_id
        FROM cards c
        JOIN sets s ON s.id = c.set_id
        LEFT JOIN (
            SELECT card_id, MAX(observed_at) AS last_observed
            FROM price_snapshots
            WHERE source_id = 'tcgdex'
            GROUP BY card_id
        ) ps ON ps.card_id = c.id
        WHERE c.source = 'tcgdex'
        ORDER BY ps.last_observed IS NOT NULL, s.release_date DESC, ps.last_observed ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [row["source_card_id"] for row in rows]


def poll_tcgdex_price_snapshots(conn: sqlite3.Connection, batch_size: int = 300) -> dict:
    """The TCGdex counterpart to poll_price_snapshots — same idea (today's market-price
    snapshot), different shape, because TCGdex's pricing lives on a per-card endpoint rather
    than something pageable in bulk. See _select_cards_for_tcgdex_poll for how the batch is
    chosen and connectors/tcgdex.py's module docstring for the API shape."""
    run_id = start_run(conn, "tcgdex")
    connector = TcgdexConnector()
    try:
        card_ids = _select_cards_for_tcgdex_poll(conn, limit=batch_size)
        observations = list(connector.fetch_observations(card_ids=card_ids))
        written = ingest_price_observations(conn, "tcgdex", observations)
        conn.commit()
        finish_run(conn, run_id, "ok", records_fetched=len(observations), records_written=written)
        return {"cards_polled": len(card_ids), "fetched": len(observations), "written": written}
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        finish_run(conn, run_id, "error", error_message=str(exc))
        logger.exception("tcgdex price snapshot poll failed")
        return {"cards_polled": 0, "fetched": 0, "written": 0, "error": str(exc)}
    finally:
        connector.close()


def recompute_top100(conn: sqlite3.Connection) -> dict:
    return compute_and_store_top100(conn)
