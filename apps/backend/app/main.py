"""FastAPI backend, bundled as a Tauri sidecar (Section 10). Binds to localhost only.

This is Phase 2 scope: enough surface for the desktop shell to boot against a real backend and
for the Top 100 screen to be wired up end-to-end in Phase 6. Connectors, the matching/cleaning
pipeline, and the scheduler are invoked from here but implemented in `connectors/` and
`services/` per the swappable-module design (Section 5c rule 6).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import get_connection, init_db
from app.ws import ConnectionManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend")

manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_directories()
    conn = init_db()
    conn.close()
    logger.info("database ready at %s", settings.db_path)
    yield


app = FastAPI(title="Pokemon Card Tracker Backend", lifespan=lifespan)

# The frontend is a Tauri webview loading http://localhost:1420 in dev, and the app:// / tauri://
# scheme once bundled — both are local-only, but CORS still needs the dev origin allowed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1420", "tauri://localhost", "http://tauri.localhost"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/settings")
def get_settings() -> dict:
    return settings.load_local_settings()


@app.put("/settings")
def put_settings(payload: dict) -> dict:
    current = settings.load_local_settings()
    current.update(payload)
    settings.save_local_settings(current)
    return current


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
                   c.name, c.name_en, c.number, c.language, c.image_local_path,
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


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Pushes live price-snapshot events and Top 100 recomputation notices to the UI
    (Section 7). Connectors call `manager.broadcast(...)` from services/ingest.py as they write
    new rows; no polling on the frontend side.
    """
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # client doesn't send anything meaningful yet; keeps the socket alive
    except WebSocketDisconnect:
        manager.disconnect(websocket)
