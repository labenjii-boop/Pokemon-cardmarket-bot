-- Pokémon Card Price & Sales Tracker — SQLite schema (Section 12 of the build spec).
--
-- Design notes:
--   * SQLite, single local file (Section 10). Foreign keys are ON by default via db.py.
--   * Every "time-series" table is indexed for the query pattern the app actually runs:
--     "give me rows for this card+grade+language within [start, end], ordered by time" —
--     that's what the Top 100 ranking (Section 2) and the chart screens (Section 11.5) do.
--   * `sales` exists per Section 12 for when a real, ToS-compliant sold-price connector
--     becomes available (see DATA_SOURCES.md §0). Until then it stays empty/near-empty and
--     `price_snapshots` (not in the spec's minimum list, added because of the sourcing gap
--     documented in DATA_SOURCES.md) is what the ranking and charts actually read from.
--   * Grades are config/database-driven (Section 4: "new grading companies and label types can
--     be added without code changes") — `grading_companies` and `grades` are plain data, and
--     nothing in application code hardcodes "PSA 10" as a special case.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------------------------
-- Catalog
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sets (
    id              TEXT PRIMARY KEY,              -- internal id, e.g. "en-base1", "jp-s1a"
    source_set_id   TEXT NOT NULL,                  -- id as reported by the catalog source
    source          TEXT NOT NULL,                  -- 'pokemontcg.io' | 'tcgdex' | ...
    name            TEXT NOT NULL,
    name_original   TEXT,                           -- name in the set's own language, if different
    series          TEXT,
    era             TEXT,
    language        TEXT NOT NULL CHECK (language IN ('en', 'ja', 'zh-cn', 'zh-tw')),
    total_cards     INTEGER,
    release_date    TEXT,                           -- ISO 8601 date
    set_code        TEXT,
    UNIQUE (source, source_set_id)
);
CREATE INDEX IF NOT EXISTS idx_sets_language ON sets (language);

CREATE TABLE IF NOT EXISTS cards (
    id                  TEXT PRIMARY KEY,           -- internal id: "<set_id>-<number>"
    set_id              TEXT NOT NULL REFERENCES sets (id) ON DELETE CASCADE,
    source              TEXT NOT NULL,
    source_card_id      TEXT NOT NULL,
    name                TEXT NOT NULL,
    name_original       TEXT,                       -- name in the card's own language
    name_en             TEXT,                       -- English translation, where known
    number              TEXT NOT NULL,               -- printed number, e.g. "025", "SV049"
    set_total           INTEGER,
    rarity              TEXT,
    variant             TEXT,                       -- holo | reverse-holo | 1st-edition |
                                                      -- shadowless | unlimited | promo-stamp |
                                                      -- alt-art | special-illustration-rare | ...
    language            TEXT NOT NULL CHECK (language IN ('en', 'ja', 'zh-cn', 'zh-tw')),
    release_date        TEXT,
    image_local_path    TEXT,                       -- path under the image cache folder
    image_source_url    TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (source, source_card_id)
);
CREATE INDEX IF NOT EXISTS idx_cards_set ON cards (set_id);
CREATE INDEX IF NOT EXISTS idx_cards_language ON cards (language);
CREATE INDEX IF NOT EXISTS idx_cards_name ON cards (name);

-- Cross-language links: symmetric pairing between equivalent cards, e.g. a Japanese card and
-- its English counterpart. Stored as directed edges; the app reads both directions.
CREATE TABLE IF NOT EXISTS card_translations (
    card_id             TEXT NOT NULL REFERENCES cards (id) ON DELETE CASCADE,
    related_card_id     TEXT NOT NULL REFERENCES cards (id) ON DELETE CASCADE,
    relationship        TEXT NOT NULL DEFAULT 'language_equivalent',
    confidence          REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (card_id, related_card_id)
);

-- FTS5 search index over card names (English/original/translated) and set names.
-- Uses the unicode61 tokenizer with a wide `separators` set so CJK text is indexed as
-- overlapping trigrams (bigram/trigram-style matching for Japanese/Chinese), configured in
-- db.py's index-build step rather than here, since FTS5 tokenizer args are set at CREATE time
-- per the app's `content_rowid` scheme documented in db.py.

-- ---------------------------------------------------------------------------------------------
-- Grading (config/database-driven per Section 4)
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS grading_companies (
    id              TEXT PRIMARY KEY,               -- 'psa' | 'bgs' | 'cgc' | 'sgc' | 'tag' | 'ace' | 'ars' | ...
    name            TEXT NOT NULL,
    region          TEXT,                           -- 'US' | 'UK' | 'JP' | 'CN' | ...
    is_raw          INTEGER NOT NULL DEFAULT 0       -- 1 for the synthetic "raw/ungraded" pseudo-company
);

CREATE TABLE IF NOT EXISTS grades (
    id                  TEXT PRIMARY KEY,           -- "psa-10", "bgs-9.5", "raw-nm"
    grading_company_id  TEXT NOT NULL REFERENCES grading_companies (id) ON DELETE CASCADE,
    label               TEXT NOT NULL,               -- "10", "9.5", "Black Label Pristine 10", "Near Mint"
    numeric_value       REAL,                        -- sortable value where one exists, else NULL
    is_special_label    INTEGER NOT NULL DEFAULT 0,   -- Pristine/Gold Label/Black Label/etc.
    sort_order          INTEGER NOT NULL DEFAULT 0,
    UNIQUE (grading_company_id, label)
);
CREATE INDEX IF NOT EXISTS idx_grades_company ON grades (grading_company_id);

-- ---------------------------------------------------------------------------------------------
-- Sources & connector health
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sources (
    id                  TEXT PRIMARY KEY,           -- 'pokemontcg_io' | 'tcgdex' | 'ecb_fx' | ...
    name                TEXT NOT NULL,
    kind                TEXT NOT NULL CHECK (kind IN ('catalog', 'price_snapshot', 'sale', 'fx', 'population')),
    is_free             INTEGER NOT NULL DEFAULT 1,
    base_url            TEXT,
    notes               TEXT                         -- short pointer back to the DATA_SOURCES.md section
);

CREATE TABLE IF NOT EXISTS connector_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id           TEXT NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    status              TEXT NOT NULL CHECK (status IN ('running', 'ok', 'error', 'rate_limited')),
    records_fetched     INTEGER NOT NULL DEFAULT 0,
    records_written     INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT
);
CREATE INDEX IF NOT EXISTS idx_connector_runs_source ON connector_runs (source_id, started_at);

-- ---------------------------------------------------------------------------------------------
-- Sales (Section 12 minimum table). Populated by a real sold-price connector when one becomes
-- available (see DATA_SOURCES.md §0) — the schema exists now so that day requires no migration.
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sales (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id             TEXT NOT NULL REFERENCES cards (id) ON DELETE CASCADE,
    grade_id            TEXT NOT NULL REFERENCES grades (id) ON DELETE RESTRICT,
    source_id           TEXT NOT NULL REFERENCES sources (id) ON DELETE RESTRICT,
    source_listing_id   TEXT NOT NULL,
    sale_date           TEXT NOT NULL,               -- ISO 8601 timestamp, UTC
    fetched_at          TEXT NOT NULL,
    price_amount        REAL NOT NULL,
    price_currency      TEXT NOT NULL,               -- ISO 4217 code as reported by the source
    price_eur           REAL,                         -- normalized at write time (Section 8)
    price_dkk           REAL,
    shipping_amount      REAL,
    shipping_currency    TEXT,
    price_hidden        INTEGER NOT NULL DEFAULT 0,   -- eBay "Best Offer accepted" etc.
    price_basis         TEXT,                         -- how price was determined if hidden/estimated
    certificate_number  TEXT,
    listing_url          TEXT,
    match_confidence     REAL NOT NULL DEFAULT 1.0,
    review_status        TEXT NOT NULL DEFAULT 'auto_accepted'
                          CHECK (review_status IN ('auto_accepted', 'needs_review', 'confirmed', 'rejected')),
    is_excluded          INTEGER NOT NULL DEFAULT 0,   -- cleaning pipeline flag (Section 7/8)
    exclusion_reason     TEXT,                         -- 'duplicate' | 'lot' | 'proxy' | 'empty_slab' |
                                                        -- 'shill_pattern' | 'cancelled' | 'outlier' | ...
    UNIQUE (source_id, source_listing_id)
);
CREATE INDEX IF NOT EXISTS idx_sales_card_grade_date ON sales (card_id, grade_id, sale_date);
CREATE INDEX IF NOT EXISTS idx_sales_date ON sales (sale_date);
CREATE INDEX IF NOT EXISTS idx_sales_review ON sales (review_status) WHERE review_status = 'needs_review';

-- ---------------------------------------------------------------------------------------------
-- Price snapshots — the app's real primary time series while no compliant sale-price connector
-- exists (DATA_SOURCES.md §0). One row per (card, grade, source, fetch). Grade is nullable
-- because catalog-embedded market prices (pokemontcg.io/TCGdex) are ungraded/raw by definition.
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS price_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id             TEXT NOT NULL REFERENCES cards (id) ON DELETE CASCADE,
    grade_id            TEXT REFERENCES grades (id) ON DELETE RESTRICT,
    source_id           TEXT NOT NULL REFERENCES sources (id) ON DELETE RESTRICT,
    observed_at         TEXT NOT NULL,               -- ISO 8601 timestamp, UTC
    price_amount        REAL NOT NULL,
    price_currency      TEXT NOT NULL,
    price_eur           REAL,
    price_dkk           REAL,
    price_kind          TEXT NOT NULL DEFAULT 'market'
                          CHECK (price_kind IN ('market', 'low', 'mid', 'high'))
);
CREATE INDEX IF NOT EXISTS idx_snapshots_card_grade_date
    ON price_snapshots (card_id, grade_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_date ON price_snapshots (observed_at);

-- ---------------------------------------------------------------------------------------------
-- Listing matches — review queue for low-confidence matches (Section 8)
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS listing_matches (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id             INTEGER REFERENCES sales (id) ON DELETE CASCADE,
    source_id           TEXT NOT NULL REFERENCES sources (id) ON DELETE RESTRICT,
    raw_title            TEXT NOT NULL,
    raw_item_specifics    TEXT,                       -- JSON blob as text
    candidate_card_id    TEXT REFERENCES cards (id) ON DELETE SET NULL,
    candidate_grade_id   TEXT REFERENCES grades (id) ON DELETE SET NULL,
    confidence           REAL NOT NULL,
    status                TEXT NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'confirmed', 'rejected')),
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_listing_matches_status ON listing_matches (status);

-- ---------------------------------------------------------------------------------------------
-- FX rates (Section 8) — ECB reference rates, EUR base
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fx_rates (
    rate_date           TEXT NOT NULL,               -- ISO 8601 date
    currency             TEXT NOT NULL,               -- ISO 4217, e.g. 'USD', 'DKK', 'JPY', 'GBP', 'CNY'
    eur_rate             REAL NOT NULL,               -- units of `currency` per 1 EUR (ECB convention)
    source               TEXT NOT NULL DEFAULT 'ecb',
    PRIMARY KEY (rate_date, currency)
);

-- ---------------------------------------------------------------------------------------------
-- Population reports (Section 9) — time series, freely-available data only (DATA_SOURCES.md §4)
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS population_reports (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id             TEXT NOT NULL REFERENCES cards (id) ON DELETE CASCADE,
    grade_id            TEXT NOT NULL REFERENCES grades (id) ON DELETE RESTRICT,
    observed_at          TEXT NOT NULL,
    population           INTEGER NOT NULL,
    source_id            TEXT NOT NULL REFERENCES sources (id) ON DELETE RESTRICT,
    UNIQUE (card_id, grade_id, observed_at, source_id)
);
CREATE INDEX IF NOT EXISTS idx_population_card_grade ON population_reports (card_id, grade_id);

-- ---------------------------------------------------------------------------------------------
-- Pre-computed aggregates (Section 9/2) — so switching time ranges in the UI is instant
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS aggregated_prices (
    card_id             TEXT NOT NULL REFERENCES cards (id) ON DELETE CASCADE,
    grade_id            TEXT NOT NULL REFERENCES grades (id) ON DELETE CASCADE,
    time_range           TEXT NOT NULL CHECK (time_range IN ('1D','7D','30D','6M','1Y','5Y','10Y','ALL')),
    computed_at           TEXT NOT NULL,
    start_price_eur       REAL,
    end_price_eur         REAL,
    low_price_eur         REAL,
    high_price_eur         REAL,
    avg_price_eur          REAL,
    median_price_eur       REAL,
    change_pct             REAL,
    change_abs_eur         REAL,
    observation_count      INTEGER NOT NULL DEFAULT 0, -- sales, or price_snapshots while sales is empty
    volatility              REAL,
    PRIMARY KEY (card_id, grade_id, time_range)
);

-- ---------------------------------------------------------------------------------------------
-- Top 100 snapshots (Section 2) — pre-computed rankings per time range
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS top100_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    time_range           TEXT NOT NULL CHECK (time_range IN ('1D','7D','30D','6M','1Y')),
    computed_at           TEXT NOT NULL,
    rank                  INTEGER NOT NULL,
    card_id               TEXT NOT NULL REFERENCES cards (id) ON DELETE CASCADE,
    grade_id              TEXT NOT NULL REFERENCES grades (id) ON DELETE CASCADE,
    start_price_eur        REAL NOT NULL,
    end_price_eur          REAL NOT NULL,
    change_pct              REAL NOT NULL,
    change_abs_eur          REAL NOT NULL,
    observation_count       INTEGER NOT NULL,
    sort_key                TEXT NOT NULL DEFAULT 'change_pct'
                            CHECK (sort_key IN ('change_pct', 'change_abs', 'volume'))
);
CREATE INDEX IF NOT EXISTS idx_top100_range_computed ON top100_snapshots (time_range, computed_at, sort_key, rank);

-- ---------------------------------------------------------------------------------------------
-- Watchlist & alerts (Section 11.7)
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS watchlist (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id             TEXT NOT NULL REFERENCES cards (id) ON DELETE CASCADE,
    grade_id            TEXT REFERENCES grades (id) ON DELETE CASCADE,
    added_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (card_id, grade_id)
);

CREATE TABLE IF NOT EXISTS alerts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    watchlist_id         INTEGER NOT NULL REFERENCES watchlist (id) ON DELETE CASCADE,
    condition             TEXT NOT NULL CHECK (condition IN ('price_above', 'price_below', 'pct_change_over')),
    threshold              REAL NOT NULL,
    time_range              TEXT,                     -- required for 'pct_change_over'
    is_active                INTEGER NOT NULL DEFAULT 1,
    last_triggered_at         TEXT
);

-- ---------------------------------------------------------------------------------------------
-- Settings (Section 11.11) — single-row key/value store, no `users` table (single local user)
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS settings (
    key                 TEXT PRIMARY KEY,
    value                TEXT NOT NULL                -- JSON-encoded
);
