"""APScheduler wiring (Section 10: "no Redis or external queue needed"). Runs entirely inside
the FastAPI process so job coroutines can call the WebSocket manager directly to push live
updates (Section 7) — a separate process (e.g. a CLI cron job) couldn't reach those open
connections.

Interval choices, and why they're conservative:
  * `sync_fx` — daily. ECB publishes once/business day; there is nothing to gain polling more
    often, and the free 90-day feed comfortably covers a once-a-day cadence with room to spare
    if the app is closed for a few days.
  * `refresh_catalog` — weekly. New Pokémon sets release a handful of times a year; this exists
    so a new set shows up within a week without the user doing anything, not because catalogs
    change daily.
  * `poll_snapshots` — every 6 hours. This is the one real rate-limit tradeoff: pokemontcg.io's
    free key allows 20,000 requests/day (1,000 without a key — DATA_SOURCES.md §5), and one full
    poll walks every card in the catalog at 250/page. Four times a day keeps comfortably inside
    that budget even for a catalog of several thousand cards while still giving the Top 100
    ranking fresh-enough data to be useful; tune via Settings once the Settings screen exists
    (Phase 10) — for now, change the `hours=` value below.
  * `recompute_top100` runs immediately after every successful snapshot poll (not on its own
    timer) so the ranking is never stale relative to the data it's ranking.

Section 7 also asks that background collection be an explicit, user-controlled setting rather
than something that just always runs — see `scheduler_enabled` in app/main.py's lifespan, which
is what actually decides whether this module's `build_scheduler()` ever gets called.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.db import get_connection
from app.ws import ConnectionManager
from services import jobs

logger = logging.getLogger("scheduler")


def build_scheduler(manager: ConnectionManager) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    async def run_sync_fx() -> None:
        with get_connection() as conn:
            result = await asyncio.to_thread(jobs.sync_fx_rates, conn)
        logger.info("fx sync: %s", result)

    async def run_refresh_catalog() -> None:
        with get_connection() as conn:
            result = await asyncio.to_thread(jobs.import_catalog, conn)
        logger.info("catalog refresh: %s", result)
        await manager.broadcast("catalog_refreshed", result)

    async def run_poll_snapshots() -> None:
        with get_connection() as conn:
            result = await asyncio.to_thread(jobs.poll_price_snapshots, conn)
        logger.info("snapshot poll: %s", result)
        if result.get("written"):
            await manager.broadcast("price_snapshots_ingested", result)
            with get_connection() as conn:
                top100_result = await asyncio.to_thread(jobs.recompute_top100, conn)
            await manager.broadcast(
                "top100_updated",
                {"computed_at": top100_result["computed_at"], "at": datetime.now(timezone.utc).isoformat()},
            )

    scheduler.add_job(run_sync_fx, "interval", hours=24, id="sync_fx", next_run_time=datetime.now())
    scheduler.add_job(run_refresh_catalog, "interval", days=7, id="refresh_catalog", next_run_time=datetime.now())
    scheduler.add_job(run_poll_snapshots, "interval", hours=6, id="poll_snapshots", next_run_time=datetime.now())

    return scheduler
