# apps/backend

Python + FastAPI backend (Section 10). Runs as a plain process in dev, and gets packaged by
PyInstaller into a Tauri sidecar binary for the shipped app (`apps/desktop/src-tauri`).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running

```bash
python -m app.entrypoint   # binds to 127.0.0.1:8756, see app/config.py
```

The database, image cache, logs, and backups live under
`~/Library/Application Support/Pokemon Card Tracker/` on macOS (a platform-appropriate
equivalent elsewhere — see `app/config.py:app_support_dir`). The schema (`app/schema.sql`) and
grading-company/grade seed data (`app/seed_grades.sql`) are applied automatically on first boot.

## Tests

```bash
pytest
```

40 tests: connector parsing against mocked HTTP responses (`respx`, never the real network),
currency normalization, the Top 100 ranking methodology, the DB ingest layer, the background
job functions (fx sync / catalog import / snapshot poll, each with their `connector_runs`
bookkeeping), the Top 100 background computation, scheduler job registration, and the
review-queue API.

## Layout

- `app/` — FastAPI app (`main.py`), SQLite schema/bootstrap (`db.py`, `schema.sql`,
  `seed_grades.sql`), non-secret config (`config.py`), macOS Keychain access for the one secret
  setting that exists so far, the pokemontcg.io API key (`secrets.py`, via the `keyring`
  package), APScheduler wiring (`scheduler.py`), the entry point (`entrypoint.py`).
- `connectors/` — one module per data source, behind the shared interface in
  `connectors/base.py`. See `connectors/README.md` before adding a new one.
- `services/` — logic that doesn't belong to a connector or a route: currency conversion
  (`currency.py`), the Top 100 ranking methodology (`top100.py`) and its DB-facing job
  (`top100_job.py`), writing connector output into SQLite (`ingest.py`), connector-run
  bookkeeping (`connector_runs.py`), and the actual scheduled/manual job bodies (`jobs.py`).
- `scripts/` — one-off CLI entry points for the same jobs `app/scheduler.py` runs on a timer
  (`import_catalog.py`, `sync_fx.py`, `poll_snapshots.py`), a 10-year FX history backfill
  (`backfill_fx_history.py`), and the PyInstaller sidecar builder (`build_sidecar.py`).
- `tests/` — mirrors the above; `conftest.py`'s `db_conn` fixture is an in-memory SQLite DB
  with the schema and seed data pre-loaded.

## Background collection

`app/scheduler.py` runs three APScheduler jobs inside the FastAPI process (so they can push
WebSocket events directly): daily FX sync, weekly catalog refresh, and a snapshot poll every 6
hours (interval reasoning is in that file's docstring — it's a real tradeoff against
pokemontcg.io's free-tier daily request cap). None of this starts automatically — Section 7
asks for background collection to be an explicit, user-controlled setting, so the scheduler only
starts when the local `scheduler_enabled` setting is true (`PUT /settings`), and can also be
kicked off once via `POST /jobs/import-catalog`, `/jobs/poll-snapshots`, `/jobs/recompute-top100`.

## What's not here yet

The matching/cleaning pipeline for free-text listing titles (Section 8) has nothing to operate
on yet — see `DATA_SOURCES.md` §0 for why — so `listing_matches`/`/review-queue` exist and are
wired into the UI but stay empty until a real listing-based sale connector is added. Also still
open: a real Section-6-style backfill (there's no deep price history to backfill, only FX), the
frontend actually subscribing to `/ws` instead of just polling on tab change, and everything in
Phase 7/10/11 (charts, dashboard/search/watchlist, macOS packaging). See the top-level README's
phase tracker.
