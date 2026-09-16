# Pokémon Card Price & Sales Tracker

A local, single-user macOS desktop app that tracks prices and price movement for Pokémon
trading cards across English, Japanese, and Chinese print lines, raw and graded. Built to run
entirely on one Mac for €0 — no paid data vendors, no cloud hosting, no accounts.

**Start here if you're new to this repo:** [`DATA_SOURCES.md`](./DATA_SOURCES.md) — it documents
every data source considered and, critically, **why most raw-sale marketplaces (eBay sold
prices, Mercari, SNKRDUNK, TCGplayer, Cardmarket, auction houses) have no free, ToS-compliant
API for an individual developer today**, and how this app adapts to that (tracking its own
market-price-snapshot history going forward, per Section 6 of the build spec, rather than a
sold-sale ledger it cannot legally/freely assemble). Read that before assuming the app does
something it structurally can't.

## Status

This repo is being built in phases (see "Build phases" below), stopping after each one for
review rather than attempting the whole spec in one pass.

- ✅ **Phase 1 — Research:** [`DATA_SOURCES.md`](./DATA_SOURCES.md) complete.
- ✅ **Phase 2 — Foundation:** Tauri + React + TS + Vite + Tailwind shell; Python/FastAPI
  backend wired as a Tauri sidecar (PyInstaller packaging verified end-to-end); full SQLite
  schema (`apps/backend/app/schema.sql`); grading companies/grades seeded as data, not code
  (Section 4); the first three connectors (pokemontcg.io, TCGdex, ECB FX) built against the
  shared connector interface, with tests mocking every HTTP call.
- ✅ **Phase 3 (adapted) — First connectors:** pokemontcg.io/TCGdex/ECB FX are already the best
  free coverage available (DATA_SOURCES.md §0) and were built in Phase 2.
- ✅ **Phase 4 (adapted) — Review queue:** `listing_matches` + `/review-queue` (confirm/reject)
  exist and are wired into the UI; empty today by construction, not by omission — no connector
  yet produces free-text listing titles that need fuzzy matching (see the screen's own
  in-app explanation).
- ✅ **Phase 6 (first pass) — Top 100 end-to-end:** APScheduler jobs (`apps/backend/app/scheduler.py`)
  poll connectors, sync FX rates, and recompute `top100_snapshots`
  (`services/top100_job.py`) on a schedule, gated behind an explicit, off-by-default
  "background collection" setting (Section 7). Manual triggers
  (`POST /jobs/import-catalog`, `/jobs/poll-snapshots`, `/jobs/recompute-top100`) and one-off
  CLI scripts (`apps/backend/scripts/`) exist for the first run, so the Top 100 screen has real
  data without waiting for the first scheduled cycle. WebSocket broadcasts fire on new
  snapshots/recomputation. 40/40 backend tests passing.
- ⬜ **Not yet built:** real-time WebSocket *consumption* in the frontend (events are broadcast
  but the UI still polls on tab/range change, not yet subscribed to `/ws`), the Dashboard/
  Search/Charts/Sales/Watchlist/Compare screens, a real 10-year backfill run, and macOS
  packaging (the `.dmg` build itself must run on an actual Mac — see "Packaging" below).

## Prerequisites (install these on your Mac first — Section 15)

```bash
# Xcode Command Line Tools (Rust/Tauri needs a C toolchain)
xcode-select --install

# Homebrew, if you don't already have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Node.js (LTS) and Python 3.11+
brew install node python@3.11

# Rust (Tauri's runtime is a Rust binary)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

Verify with `node -v`, `python3 --version`, `cargo --version`.

## Running it in development

```bash
# Terminal 1 — backend
cd apps/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# first run only: seed the catalog, FX rates, and one price-snapshot poll so the Top 100
# screen has something to show immediately, instead of waiting for the scheduler's first cycle
python scripts/import_catalog.py
python scripts/sync_fx.py
python scripts/poll_snapshots.py

python -m app.entrypoint            # http://127.0.0.1:8756

# Terminal 2 — desktop shell
cd apps/desktop
npm install
npm run tauri dev                   # opens the native window, talks to the backend above
```

Background collection (scheduled re-polling while the app runs, Section 7) is **off by
default** — turn it on from the Settings screen, or `PUT /settings {"scheduler_enabled": true}`.

(`npm run dev` alone runs just the Vite dev server in a browser tab, without the native Tauri
window — useful for fast UI iteration; see `apps/desktop/README.md`.)

## Running the tests

```bash
cd apps/backend
source .venv/bin/activate
pytest
```

## Architecture

```
apps/
  desktop/            React + TypeScript + Vite + Tailwind + Lightweight Charts
    src/
      screens/        one component per core screen (Section 11)
      api/client.ts   the only module that talks HTTP to the backend
    src-tauri/         Rust shell: window config, spawns/kills the backend sidecar
  backend/            Python + FastAPI, packaged as the sidecar (PyInstaller)
    app/              FastAPI app, SQLite schema + bootstrap, config
    connectors/       one module per data source, behind a shared interface (see below)
    services/         currency normalization, Top 100 ranking methodology, DB ingest
DATA_SOURCES.md        research: what's free/compliant per source, and what isn't
```

**Why a Python sidecar instead of a Rust or Node backend:** the spec (Section 10) chose it for
fast iteration on data connectors/parsing (httpx, pandas-style analysis later) while keeping the
shell itself (Tauri) lightweight and native. The two talk over localhost HTTP + WebSocket; the
backend is never reachable outside the machine.

**Why SQLite with hand-written SQL, no ORM:** single local file, no server to run, and the
query patterns that actually matter (time-range aggregation over what should eventually be
millions of rows — Section 10's scale target) are easier to index and reason about directly.

## Adding a new data source

1. Research it and add a row to `DATA_SOURCES.md` first — free/paid, rate limits, ToS,
   historical coverage. Don't write a connector for something not documented there.
2. Implement `CatalogConnector`, `SnapshotConnector`, or `FxConnector` from
   `apps/backend/connectors/base.py` (or add a new interface there if the source is a genuinely
   new shape — e.g. a future real sold-price connector).
3. Add a row to `apps/backend/app/seed_grades.sql`'s `sources` insert block.
4. Write `apps/backend/tests/test_<source>.py` using `respx` to mock every HTTP call.

Full detail: `apps/backend/connectors/README.md`.

## Adding a new grading company or grade

Grading companies and grades are rows in `grading_companies` / `grades`
(`apps/backend/app/seed_grades.sql`), not code (Section 4's explicit requirement) — add rows
there. Nothing in the application special-cases a company or grade string.

## Build phases (Section 13)

1. Research → `DATA_SOURCES.md` ✅
2. Foundation: shell, schema, first connectors ✅
3. First connectors with the best free sales coverage — *adapted to price-snapshot connectors,
   see DATA_SOURCES.md §0; pokemontcg.io/TCGdex/ECB already built in Phase 2*
4. Matching and cleaning pipeline + review queue
5. Backfill (at least 1 year of price-snapshot history)
6. **Top 100 Hottest Cards, full feature end-to-end** — stop and test here
7. Card detail page and full charts
8. Real-time layer: live feed, live chart/Top 100 updates
9. Remaining connectors and extended history
10. Dashboard, search, compare, watchlist, alerts
11. Packaging: unsigned `.dmg` + Gatekeeper bypass instructions

## What's next

The core data loop (connectors → snapshots → ranking → UI) is now real and tested end-to-end.
What's left before this is genuinely usable day-to-day:

- **Frontend WebSocket subscription** — the backend already broadcasts `price_snapshots_ingested`
  and `top100_updated` over `/ws`; the Top 100 screen doesn't listen yet, so it still requires a
  tab switch or reload to pick up a background-collection update.
- **A real backfill run** — `scripts/backfill_fx_history.py` exists for FX; there is no
  analogous deep backfill for prices because none exists to backfill (DATA_SOURCES.md §0) —
  history only accumulates from whenever polling started.
- **Phase 7** — card detail page and full interactive charts (Lightweight Charts is installed
  but unused so far).
- **Phase 10** — Dashboard, Search, Sales Table, Watchlist/alerts, Compare — currently
  placeholder screens.
- **Phase 11** — packaging. Needs to run on an actual Mac (Apple Silicon and Intel each need
  their own PyInstaller sidecar build — see `apps/backend/scripts/build_sidecar.py`, which has
  been verified end-to-end on Linux and just needs the equivalent macOS run).
