"""FastAPI backend, bundled as a Tauri sidecar (Section 10). Binds to localhost only.

Connectors, the matching/cleaning pipeline, and the scheduler are invoked from here but
implemented in `connectors/` and `services/` per the swappable-module design (Section 5c rule
6). The scheduler (app/scheduler.py) only starts when the `scheduler_enabled` local setting is
true — Section 7 asks background collection to be an explicit, off-by-default user choice, not
something that just always runs the moment the app opens.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware

# The frontend is a Tauri webview loading http://localhost:1420 in dev, and the app:// / tauri://
# scheme once bundled. CORSMiddleware below only guards plain HTTP routes — browsers don't apply
# CORS to WebSocket handshakes, so the /ws endpoint checks this same allowlist by hand (a page
# open in an unrelated browser tab can otherwise open a WS to any localhost port and read
# whatever it broadcasts, regardless of CORS).
ALLOWED_ORIGINS = ["http://localhost:1420", "tauri://localhost", "http://tauri.localhost"]

from app.config import settings
from app.db import get_connection, init_db
from app.scheduler import build_scheduler
from app.secrets import delete_secret, get_secret, set_secret
from app.ws import ConnectionManager
from connectors.tcgdex import TcgdexConnector
from services import jobs
from services.currency import MissingFxRateError, to_eur
from services.ingest import ingest_price_observations
from services.search import search_cards
from services.top100 import TIME_RANGE_TO_TIMEDELTA, period_for_range
from services.top100_job import format_query_bound

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend")

manager = ConnectionManager()
scheduler_state: dict = {"scheduler": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_directories()
    conn = init_db()
    conn.close()
    logger.info("database ready at %s", settings.db_path)

    if settings.load_local_settings().get("scheduler_enabled", False):
        _start_scheduler()

    yield

    if scheduler_state["scheduler"] is not None:
        scheduler_state["scheduler"].shutdown(wait=False)


def _start_scheduler() -> None:
    if scheduler_state["scheduler"] is not None:
        return
    scheduler = build_scheduler(manager)
    scheduler.start()
    scheduler_state["scheduler"] = scheduler
    logger.info("background collection scheduler started")


def _stop_scheduler() -> None:
    if scheduler_state["scheduler"] is None:
        return
    scheduler_state["scheduler"].shutdown(wait=False)
    scheduler_state["scheduler"] = None
    logger.info("background collection scheduler stopped")


app = FastAPI(title="Pokemon Card Tracker Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


# Settings keys that hold a secret: stored in the macOS Keychain via app/secrets.py, never in
# the plaintext local settings file. GET never echoes the value back — only whether one is set —
# so a secret typed once doesn't keep coming back over the local HTTP API on every read.
SECRET_SETTINGS_KEYS = ("pokemontcg_io_api_key",)


@app.get("/settings")
def get_settings() -> dict:
    current = settings.load_local_settings()
    for key in SECRET_SETTINGS_KEYS:
        current.pop(key, None)  # drop any leftover value from before the Keychain migration
        current[f"{key}_set"] = get_secret(key) is not None
    return current


@app.put("/settings")
def put_settings(payload: dict) -> dict:
    payload = dict(payload)
    for key in SECRET_SETTINGS_KEYS:
        if key in payload:
            value = payload.pop(key)
            if value:
                set_secret(key, value)
            else:
                delete_secret(key)

    current = settings.load_local_settings()
    current.update(payload)
    settings.save_local_settings(current)

    if "scheduler_enabled" in payload:
        if payload["scheduler_enabled"]:
            _start_scheduler()
        else:
            _stop_scheduler()

    return get_settings()


@app.post("/jobs/import-catalog")
def trigger_import_catalog() -> dict:
    """Manual trigger for the heavy one-off catalog import (Phase 2/3) — useful for the first
    run, before the weekly scheduled refresh would otherwise pick up a new set."""
    with get_connection() as conn:
        return jobs.import_catalog(conn)


@app.post("/jobs/poll-snapshots")
def trigger_poll_snapshots() -> dict:
    with get_connection() as conn:
        result = jobs.poll_price_snapshots(conn)
        if result.get("written"):
            jobs.recompute_top100(conn)
    return result


@app.post("/jobs/recompute-top100")
def trigger_recompute_top100() -> dict:
    with get_connection() as conn:
        return jobs.recompute_top100(conn)


@app.get("/sources/status")
def sources_status() -> list[dict]:
    """Feeds the Source Status Panel (Section 11.9): each source plus its most recent run."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.name, s.kind, s.is_free,
                   r.status AS last_status, r.started_at AS last_started_at,
                   r.finished_at AS last_finished_at, r.error_message AS last_error
            FROM sources s
            LEFT JOIN connector_runs r ON r.id = (
                SELECT id FROM connector_runs WHERE source_id = s.id ORDER BY started_at DESC LIMIT 1
            )
            """
        ).fetchall()
        return [dict(row) for row in rows]


@app.get("/cards/search")
def cards_search(q: str = "", limit: int = 60) -> list[dict]:
    """Section 11.3. Backed by the cards_fts index — works as soon as a catalog connector has
    run, independently of whether any price data exists yet (unlike Top 100, which needs both)."""
    with get_connection() as conn:
        return search_cards(conn, q, limit)


@app.get("/cards/{card_id}")
def get_card(card_id: str) -> dict:
    """Section 11.4 (card detail page) header info — name, image, set, language, etc."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT c.id, c.name, c.name_en, c.name_original, c.number, c.language, c.rarity,
                   c.variant, c.image_source_url, s.name AS set_name, s.language AS set_language
            FROM cards c
            JOIN sets s ON s.id = c.set_id
            WHERE c.id = ?
            """,
            (card_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="card not found")
        return dict(row)


def _backfill_thin_tcgdex_history(conn, card_id: str) -> None:
    """A card that's only ever been polled once or twice looks like a flat, pointless chart
    until the background rotation happens to revisit it enough times over real elapsed
    hours/days (see _select_cards_for_tcgdex_poll in services/jobs.py) — not something a user
    opening a card right now should have to wait on. When this card has fewer than 2 stored
    TCGdex snapshots, make one live call to seed real (if approximate) history from Cardmarket's
    own avg1/avg7/avg30 rolling averages — see TcgdexConnector.fetch_price_history_backfill.
    Best-effort: a failed live call here must not break loading whatever history already exists.
    """
    row = conn.execute("SELECT source, source_card_id FROM cards WHERE id = ?", (card_id,)).fetchone()
    if row is None or row["source"] != "tcgdex":
        return
    existing = conn.execute(
        "SELECT COUNT(*) AS n FROM price_snapshots WHERE card_id = ? AND source_id = 'tcgdex'", (card_id,)
    ).fetchone()["n"]
    if existing >= 2:
        return
    connector = TcgdexConnector()
    try:
        observations = connector.fetch_price_history_backfill(row["source_card_id"])
    except Exception:  # noqa: BLE001 — best-effort seed, never block the page over it
        logger.warning("tcgdex history backfill failed for %s", card_id, exc_info=True)
        return
    finally:
        connector.close()
    if observations:
        ingest_price_observations(conn, "tcgdex", observations)
        conn.commit()


@app.get("/cards/{card_id}/prices")
def get_card_prices(card_id: str, time_range: str = "30D") -> list[dict]:
    """Section 11.4/11.5: the raw series the card detail page's interactive chart plots. Every
    price_snapshots row for this card in the range (across sources/grades — today that's just
    the ungraded 'raw-nm' market-price snapshots, see DATA_SOURCES.md §0), oldest first."""
    if time_range not in TIME_RANGE_TO_TIMEDELTA:
        raise HTTPException(status_code=400, detail=f"time_range must be one of {sorted(TIME_RANGE_TO_TIMEDELTA)}")
    with get_connection() as conn:
        # Backfill (if it runs at all) happens before the range is computed, not after — its
        # "now" point must land inside `period_end`, not get excluded by a range boundary that
        # was already computed a moment earlier.
        _backfill_thin_tcgdex_history(conn, card_id)
        period_start, period_end = period_for_range(time_range, datetime.now(timezone.utc))
        rows = conn.execute(
            """
            SELECT observed_at, price_eur, grade_id, source_id
            FROM price_snapshots
            WHERE card_id = ? AND observed_at BETWEEN ? AND ? AND price_eur IS NOT NULL
            ORDER BY observed_at ASC
            """,
            (card_id, format_query_bound(period_start), format_query_bound(period_end)),
        ).fetchall()
        return [dict(row) for row in rows]


@app.get("/cards/{card_id}/variants")
def get_card_variants(card_id: str) -> dict:
    """Live, on-demand per-print-variant price breakdown (holo, reverse holo, etc) — one direct
    request to TCGdex right now, not something pre-computed or stored. Deliberately separate
    from /cards/{id}/prices: that endpoint's time series was the site of a real bug where mixing
    variant-specific prices together made the chart look like noise (see
    connectors/tcgdex.py's _observations_from_card_detail docstring) — this endpoint is where
    that same per-variant data belongs instead, as a live snapshot, not stored history.

    TCGplayer reports in USD; the rest of this app displays in EUR (Section 1) — converted here,
    not left as a second currency, so the section is one consistent number line instead of
    forcing whoever's looking at it to convert $ to € in their head to compare rows."""
    with get_connection() as conn:
        row = conn.execute("SELECT source, source_card_id FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="card not found")
        if row["source"] != "tcgdex":
            return {"cardmarket_eur": {}, "tcgplayer_eur": {}}  # only TCGdex-sourced cards support this today

        connector = TcgdexConnector()
        try:
            pricing = connector.fetch_card_variant_pricing(row["source_card_id"])
        finally:
            connector.close()

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tcgplayer_eur: dict[str, float] = {}
        for variant, usd_amount in pricing["tcgplayer_usd"].items():
            try:
                tcgplayer_eur[variant] = round(to_eur(conn, usd_amount, "USD", today), 2)
            except MissingFxRateError:
                continue  # no USD rate synced yet — omit rather than show a wrong/stale number
        return {"cardmarket_eur": pricing["cardmarket_eur"], "tcgplayer_eur": tcgplayer_eur}


@app.get("/top100")
def top100(
    time_range: str = "7D",
    sort_key: str = "change_pct",
    language: str | None = None,
    grading_company_id: str | None = None,
    min_price_eur: float | None = None,
    limit: int = 100,
) -> list[dict]:
    """Reads the latest pre-computed `top100_snapshots` row set for the given range/sort
    (Section 9: "pre-compute the aggregates... so switching time ranges is instant"). The
    background job that populates this table lives in services/top100.py + a scheduled task
    (APScheduler, Section 10) — wiring that scheduler in is Phase 6 work; this endpoint is ready
    for it and returns an empty list until the first computation has run.
    """
    with get_connection() as conn:
        query = [
            """
            SELECT t.rank, t.card_id, t.grade_id, t.start_price_eur, t.end_price_eur,
                   t.change_pct, t.change_abs_eur, t.observation_count,
                   c.name, c.name_en, c.number, c.language, c.image_source_url,
                   g.label AS grade_label, gc.name AS grading_company
            FROM top100_snapshots t
            JOIN cards c ON c.id = t.card_id
            JOIN grades g ON g.id = t.grade_id
            JOIN grading_companies gc ON gc.id = g.grading_company_id
            WHERE t.time_range = ? AND t.sort_key = ?
              AND t.computed_at = (
                  SELECT MAX(computed_at) FROM top100_snapshots WHERE time_range = ? AND sort_key = ?
              )
            """
        ]
        params: list = [time_range, sort_key, time_range, sort_key]
        if language:
            query.append("AND c.language = ?")
            params.append(language)
        if grading_company_id:
            query.append("AND gc.id = ?")
            params.append(grading_company_id)
        if min_price_eur is not None:
            query.append("AND t.end_price_eur >= ?")
            params.append(min_price_eur)
        query.append("ORDER BY t.rank LIMIT ?")
        params.append(limit)
        rows = conn.execute(" ".join(query), params).fetchall()
        return [dict(row) for row in rows]


@app.get("/review-queue")
def review_queue(limit: int = 100) -> list[dict]:
    """Section 11.10. Empty today by construction, not by bug: the connectors built so far
    (pokemontcg.io, TCGdex) are structured APIs that resolve straight to a `card_id` — there is
    no free-text listing title to parse, so nothing lands in `listing_matches`
    (DATA_SOURCES.md §0). The table, this endpoint, and the matching confidence score all
    already exist so the day a real listing-based sale connector is added (Section 8's title/
    item-specifics parsing), its low-confidence matches have somewhere to go without a schema
    change — only a new connector needs writing, not this endpoint.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT lm.id, lm.raw_title, lm.confidence, lm.status, lm.created_at,
                   lm.candidate_card_id, lm.candidate_grade_id, s.name AS source_name
            FROM listing_matches lm
            JOIN sources s ON s.id = lm.source_id
            WHERE lm.status = 'pending'
            ORDER BY lm.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


@app.post("/review-queue/{match_id}/confirm")
def confirm_match(match_id: int) -> dict:
    with get_connection() as conn:
        conn.execute("UPDATE listing_matches SET status = 'confirmed' WHERE id = ?", (match_id,))
        conn.commit()
    return {"id": match_id, "status": "confirmed"}


@app.post("/review-queue/{match_id}/reject")
def reject_match(match_id: int) -> dict:
    with get_connection() as conn:
        conn.execute("UPDATE listing_matches SET status = 'rejected' WHERE id = ?", (match_id,))
        conn.commit()
    return {"id": match_id, "status": "rejected"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Pushes live price-snapshot events and Top 100 recomputation notices to the UI
    (Section 7). Connectors call `manager.broadcast(...)` from services/ingest.py as they write
    new rows; no polling on the frontend side.

    Browsers don't apply CORS to WebSocket handshakes, so unlike the HTTP routes above this
    needs its own Origin check — otherwise any page open in the user's browser could connect
    here and read every broadcast (see ALLOWED_ORIGINS' docstring).
    """
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # client doesn't send anything meaningful yet; keeps the socket alive
    except WebSocketDisconnect:
        manager.disconnect(websocket)
