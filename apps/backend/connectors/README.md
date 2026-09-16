# Connectors

Every data source the app talks to lives here as one module, implementing one of the
interfaces in `base.py`:

- `CatalogConnector` — card/set metadata (`fetch_sets`, `fetch_cards`).
- `SnapshotConnector` — price observations (`fetch_observations`). A future real sold-price
  connector also implements this, setting `PriceObservation.is_transaction=True`; the ingest
  layer (`services/ingest.py`) is what decides that flag routes the row to `sales` instead of
  `price_snapshots` — the connector itself doesn't know which table it feeds.
- `FxConnector` — exchange rates (`fetch_rates`).

Nothing outside `connectors/` imports `httpx` or parses HTML/XML directly — `services/ingest.py`
and the FastAPI routes only ever call these three methods, so a source can be added, replaced,
or removed without touching ranking, currency, or the API layer (Section 5c rule 6).

## Existing connectors

| Module | Interface | Source |
|---|---|---|
| `pokemontcg_io.py` | Catalog + Snapshot | pokemontcg.io v2 (English catalog + embedded TCGplayer/Cardmarket market price) |
| `tcgdex.py` | Catalog | TCGdex (multi-language catalog: en/ja/zh-tw/zh-cn) |
| `ecb_fx.py` | Fx | European Central Bank reference rates |

See `../../DATA_SOURCES.md` for why this list doesn't (yet) include eBay, Mercari, TCGplayer
sold prices, Cardmarket, or the auction houses — none currently offer free, ToS-compliant
automated access to individual sale prices.

## Adding a new source

1. Research it first and add a row to `DATA_SOURCES.md` — free/paid, rate limits, ToS,
   historical coverage. Don't write code before that row exists.
2. Create `connectors/<source_name>.py`, implement the interface that matches what the source
   provides (catalog / snapshot / fx — or a new interface in `base.py` if it's a genuinely new
   shape, e.g. a real `SaleConnector` once one becomes available).
3. Add a row to `app/seed_grades.sql`'s `sources` insert block so it shows up in the Source
   Status Panel (Section 11.9).
4. Write tests under `tests/test_<source_name>.py` using `respx` to mock HTTP responses —
   never hit the real network in the test suite (Section 14: "integration tests for connectors
   with mocked responses").
5. Wire it into the scheduler (Phase 8/9 work) once it's ready to run unattended.

## Optional API key

`pokemontcg_io.py` accepts an optional key (raises the free rate limit from 1,000 to 20,000
requests/day — see `DATA_SOURCES.md` §5 for how to get one). It's passed in by whatever wires
the connector up (the scheduler or an import script), read from the macOS Keychain / local
settings — never hardcoded and never committed.
