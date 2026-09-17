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
from services.top100_job import compute_and_store_top100, load_ranking_settings

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


def _select_cards_for_tcgdex_poll(conn: sqlite3.Connection, limit: int, min_observations: int = 3) -> list[str]:
    """TCGdex pricing costs one HTTP request per card (connectors/tcgdex.py), so a single run
    can't cover the whole catalog — this picks a rotating batch instead.

    Three lessons from real runs, all addressed here:
      1. Every card from TCGdex's Pokémon TCG Pocket sets (serie id "tcgp" — a separate
         digital-only mobile game TCGdex catalogs alongside the physical TCG) is excluded: those
         cards can never have TCGplayer/Cardmarket pricing because they aren't physical objects.
      2. Among the rest, recently released sets are biased towards first — more likely to have
         an active market listing than an obscure decades-old commons run.
      3. The deadlock this fixes: naively always preferring "never observed" cards means the
         rotation keeps fanning out to brand-new cards every run and no single card ever
         accumulates enough observations to be ranked at all (Top 100 needs `min_observations`
         real data points — a real run hit exactly this: three consecutive polls, ~2000 fresh
         observations written, Top 100 stayed at 0 rows the whole time). Cards sitting between 1
         and `min_observations - 1` observations are now the TOP priority — closest to
         qualifying, so they get finished before the rotation moves on to undiscovered cards.
         Cards that already have enough observations drop to lowest priority here (they're kept
         fresh separately, if currently ranked, by _select_watchlist_cards_for_tcgdex_poll).
      4. Within that top-priority group, highest observation count first (2 beats 1) — caught
         from the very next real run after lesson 3's fix landed: 1,468 cards sitting at 1
         observation and 800 at 2, with no count-based tiebreak the 800 closest to actually
         qualifying could easily lose out to the far larger pool of 1's on a tiebreak that only
         looked at release date and last-observed time, stalling right at the finish line
         instead of crossing it."""
    rows = conn.execute(
        """
        SELECT c.source_card_id
        FROM cards c
        JOIN sets s ON s.id = c.set_id
        LEFT JOIN (
            SELECT card_id, COUNT(*) AS obs_count, MAX(observed_at) AS last_observed
            FROM price_snapshots
            WHERE source_id = 'tcgdex'
            GROUP BY card_id
        ) ps ON ps.card_id = c.id
        WHERE c.source = 'tcgdex' AND (s.series IS NULL OR s.series != 'tcgp')
        ORDER BY
            CASE
                WHEN COALESCE(ps.obs_count, 0) = 0 THEN 1
                WHEN ps.obs_count < ? THEN 0
                ELSE 2
            END,
            COALESCE(ps.obs_count, 0) DESC,
            s.release_date DESC,
            ps.last_observed ASC
        LIMIT ?
        """,
        (min_observations, limit),
    ).fetchall()
    return [row["source_card_id"] for row in rows]


def _cards_without_tcgdex_history(conn: sqlite3.Connection, source_card_ids: list[str]) -> set[str]:
    """Which of `source_card_ids` have zero stored TCGdex snapshots yet — i.e. this poll is the
    very first time they're being observed. Used to decide which cards additionally get
    Cardmarket's avg1/avg7/avg30 backfilled as backdated points (see TcgdexConnector.fetch_observations'
    `backfill_ids`): without it, Top 100 needs `min_observations` *real, hours-apart* polls
    before a brand-new card can be ranked with a meaningful % change at all — a real run hit
    this exactly (thousands of fresh observations written, Top 100 still at 0 rows). Backfilling
    a card's first poll gets it past that threshold immediately instead of over real elapsed time."""
    if not source_card_ids:
        return set()
    placeholders = ",".join("?" for _ in source_card_ids)
    rows = conn.execute(
        f"""
        SELECT c.source_card_id
        FROM cards c
        LEFT JOIN price_snapshots ps ON ps.card_id = c.id AND ps.source_id = 'tcgdex'
        WHERE c.source = 'tcgdex' AND c.source_card_id IN ({placeholders})
        GROUP BY c.source_card_id
        HAVING COUNT(ps.id) = 0
        """,
        source_card_ids,
    ).fetchall()
    return {row["source_card_id"] for row in rows}


def _select_watchlist_cards_for_tcgdex_poll(conn: sqlite3.Connection) -> list[str]:
    """Cards worth refreshing on *every* run regardless of the discovery rotation: whatever's
    currently ranked in Top 100 (any time range/sort key), since that's what the user is
    actually looking at. Real problem this fixes: with a catalog of tens of thousands of cards
    and a rotation batch of a few hundred, a given card might not get revisited for days —
    fine for slowly building overall coverage, but it means a card the user has open right now
    could sit at a single observation (a flat, pointless "chart") for just as long. This runs
    first and is never subject to the "never observed yet" bias."""
    rows = conn.execute(
        """
        SELECT DISTINCT c.source_card_id
        FROM top100_snapshots t
        JOIN cards c ON c.id = t.card_id
        WHERE c.source = 'tcgdex'
          AND t.computed_at = (SELECT MAX(computed_at) FROM top100_snapshots)
        """
    ).fetchall()
    return [row["source_card_id"] for row in rows]


def poll_tcgdex_price_snapshots(conn: sqlite3.Connection, batch_size: int = 300) -> dict:
    """The TCGdex counterpart to poll_price_snapshots — same idea (today's market-price
    snapshot), different shape, because TCGdex's pricing lives on a per-card endpoint rather
    than something pageable in bulk. The batch is the current Top 100's cards (see
    _select_watchlist_cards_for_tcgdex_poll) plus, filling out the rest of batch_size, new/
    least-recently-seen cards from _select_cards_for_tcgdex_poll — see connectors/tcgdex.py's
    module docstring for the API shape."""
    run_id = start_run(conn, "tcgdex")
    connector = TcgdexConnector()
    try:
        min_observations = load_ranking_settings(conn).min_observations
        watchlist_ids = _select_watchlist_cards_for_tcgdex_poll(conn)
        rotation_ids = _select_cards_for_tcgdex_poll(
            conn, limit=max(batch_size - len(watchlist_ids), 0), min_observations=min_observations
        )
        seen: set[str] = set()
        card_ids = [cid for cid in watchlist_ids + rotation_ids if not (cid in seen or seen.add(cid))]
        backfill_ids = _cards_without_tcgdex_history(conn, card_ids)
        observations = list(connector.fetch_observations(card_ids=card_ids, backfill_ids=backfill_ids))
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
