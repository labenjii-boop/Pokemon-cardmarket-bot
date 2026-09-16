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
  backend wired as a Tauri sidecar; full SQLite schema (`apps/backend/app/schema.sql`);
  grading companies/grades seeded as data, not code (Section 4); the first three connectors
  (pokemontcg.io, TCGdex, ECB FX) built against the shared connector interface, with tests
  mocking every HTTP call; a Top 100 screen and Source Status screen wired end-to-end against
  real (currently empty) backend endpoints. 27/27 backend tests passing.
- ⬜ **Phase 3 onward** — not started: the matching/cleaning pipeline and review queue, running
  the scheduler and an actual backfill, the Top 100 background computation job, real-time
  WebSocket pushes, the remaining screens, and macOS packaging. See "What's next" below.

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
python -m app.entrypoint            # http://127.0.0.1:8756

# Terminal 2 — desktop shell
cd apps/desktop
npm install
npm run tauri dev                   # opens the native window, talks to the backend above
```

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

Phase 3 (adapted) is effectively done as a byproduct of Phase 2 — the next real milestone is
**Phase 4**: the matching/cleaning pipeline (only meaningful once real listing titles exist to
parse; today's snapshot connectors already resolve to a specific `card_id`, so most of Phase 4's
work is the *future* sale-listing matcher) and the review queue UI, followed by wiring
APScheduler to actually run the connectors on a schedule and compute `top100_snapshots`
(Phase 6, the first fully end-to-end feature).
