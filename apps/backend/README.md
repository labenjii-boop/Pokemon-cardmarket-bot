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

27 tests as of Phase 2: connector parsing against mocked HTTP responses (`respx`, never the real
network), currency normalization, the Top 100 ranking methodology, and the DB ingest layer.

## Layout

- `app/` — FastAPI app, SQLite schema/bootstrap, config, the entry point.
- `connectors/` — one module per data source, behind the shared interface in
  `connectors/base.py`. See `connectors/README.md` before adding a new one.
- `services/` — logic that doesn't belong to a connector or a route: currency conversion
  (`currency.py`), the Top 100 ranking methodology (`top100.py`), writing connector output into
  SQLite (`ingest.py`).
- `scripts/build_sidecar.py` — builds the PyInstaller binary the desktop shell spawns.
- `tests/` — mirrors the above; `conftest.py`'s `db_conn` fixture is an in-memory SQLite DB
  with the schema and seed data pre-loaded.

## What's not here yet

APScheduler wiring (recurring connector runs), the matching/cleaning pipeline (Section 8), the
review queue, and the `/top100` background recomputation job are Phase 4/6/8 work — the schema,
ranking methodology, and API route for Top 100 already exist so that work is additive, not a
rewrite. See the top-level README's phase tracker.
