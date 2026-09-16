-- Seed data for grading_companies / grades (Section 4). Idempotent: safe to re-run.
-- This is the *only* place grading companies and grades are defined — application code never
-- special-cases a company or grade string, so adding e.g. a new Chinese grading company later
-- is purely an INSERT here (or, eventually, a Settings-screen form that writes the same rows).

INSERT OR IGNORE INTO grading_companies (id, name, region, is_raw) VALUES
    ('raw', 'Raw (ungraded)', NULL, 1),
    ('psa', 'PSA', 'US', 0),
    ('bgs', 'BGS / Beckett', 'US', 0),
    ('cgc', 'CGC', 'US', 0),
    ('sgc', 'SGC', 'US', 0),
    ('tag', 'TAG', 'US', 0),
    ('ace', 'ACE Grading', 'UK', 0),
    ('ars', 'ARS', 'JP', 0),
    -- Major Chinese-market grading companies (Section 4 asks these be researched and listed).
    -- Coverage is preliminary — flagged in DATA_SOURCES.md as needing dedicated research; kept
    -- here as rows, not code, so refining this list never requires a code change.
    ('cse', 'CSG (Card Standard Evaluation)', 'CN', 0),
    ('gbca', 'GBCA (Global Brand Collectibles Authentication)', 'CN', 0);

INSERT OR IGNORE INTO grades (id, grading_company_id, label, numeric_value, is_special_label, sort_order) VALUES
    ('raw-nm', 'raw', 'Near Mint', NULL, 0, 5),
    ('raw-lp', 'raw', 'Lightly Played', NULL, 0, 4),
    ('raw-mp', 'raw', 'Moderately Played', NULL, 0, 3),
    ('raw-hp', 'raw', 'Heavily Played', NULL, 0, 2),
    ('raw-dmg', 'raw', 'Damaged', NULL, 0, 1);

-- PSA 1-10 including half grades (1.5, 2.5, ... 9.5)
INSERT OR IGNORE INTO grades (id, grading_company_id, label, numeric_value, is_special_label, sort_order)
SELECT 'psa-' || printf('%g', v), 'psa', printf('%g', v), v, 0, CAST(v * 2 AS INTEGER)
FROM (
    WITH RECURSIVE seq(v) AS (SELECT 1.0 UNION ALL SELECT v + 0.5 FROM seq WHERE v < 10.0)
    SELECT v FROM seq
);

-- BGS 1-10 including half grades, plus special labels
INSERT OR IGNORE INTO grades (id, grading_company_id, label, numeric_value, is_special_label, sort_order)
SELECT 'bgs-' || printf('%g', v), 'bgs', printf('%g', v), v, 0, CAST(v * 2 AS INTEGER)
FROM (
    WITH RECURSIVE seq(v) AS (SELECT 1.0 UNION ALL SELECT v + 0.5 FROM seq WHERE v < 10.0)
    SELECT v FROM seq
);
INSERT OR IGNORE INTO grades (id, grading_company_id, label, numeric_value, is_special_label, sort_order) VALUES
    ('bgs-black-label-10', 'bgs', 'Black Label Pristine 10', 10.0, 1, 21);

-- CGC 1-10 plus special labels
INSERT OR IGNORE INTO grades (id, grading_company_id, label, numeric_value, is_special_label, sort_order)
SELECT 'cgc-' || printf('%g', v), 'cgc', printf('%g', v), v, 0, CAST(v * 2 AS INTEGER)
FROM (
    WITH RECURSIVE seq(v) AS (SELECT 1.0 UNION ALL SELECT v + 0.5 FROM seq WHERE v < 10.0)
    SELECT v FROM seq
);
INSERT OR IGNORE INTO grades (id, grading_company_id, label, numeric_value, is_special_label, sort_order) VALUES
    ('cgc-pristine-10', 'cgc', 'Pristine 10', 10.0, 1, 21),
    ('cgc-gem-mint-10', 'cgc', 'Gem Mint 10', 10.0, 1, 22);

-- SGC 1-10 plus Pristine / Gold Label
INSERT OR IGNORE INTO grades (id, grading_company_id, label, numeric_value, is_special_label, sort_order)
SELECT 'sgc-' || printf('%g', v), 'sgc', printf('%g', v), v, 0, CAST(v * 2 AS INTEGER)
FROM (
    WITH RECURSIVE seq(v) AS (SELECT 1.0 UNION ALL SELECT v + 1.0 FROM seq WHERE v < 10.0)
    SELECT v FROM seq
);
INSERT OR IGNORE INTO grades (id, grading_company_id, label, numeric_value, is_special_label, sort_order) VALUES
    ('sgc-pristine-10', 'sgc', 'Pristine 10', 10.0, 1, 21),
    ('sgc-gold-label-10', 'sgc', 'Gold Label 10', 10.0, 1, 22);

-- TAG, ACE, ARS: 1-10, whole grades only (their published scales as of this research pass;
-- revisit if a company introduces half-grades or special labels).
INSERT OR IGNORE INTO grades (id, grading_company_id, label, numeric_value, is_special_label, sort_order)
SELECT 'tag-' || v, 'tag', CAST(v AS TEXT), v, 0, v
FROM (WITH RECURSIVE seq(v) AS (SELECT 1 UNION ALL SELECT v + 1 FROM seq WHERE v < 10) SELECT v FROM seq);

INSERT OR IGNORE INTO grades (id, grading_company_id, label, numeric_value, is_special_label, sort_order)
SELECT 'ace-' || v, 'ace', CAST(v AS TEXT), v, 0, v
FROM (WITH RECURSIVE seq(v) AS (SELECT 1 UNION ALL SELECT v + 1 FROM seq WHERE v < 10) SELECT v FROM seq);

INSERT OR IGNORE INTO grades (id, grading_company_id, label, numeric_value, is_special_label, sort_order)
SELECT 'ars-' || v, 'ars', CAST(v AS TEXT), v, 0, v
FROM (WITH RECURSIVE seq(v) AS (SELECT 1 UNION ALL SELECT v + 1 FROM seq WHERE v < 10) SELECT v FROM seq);

-- Sources (Section 12 `sources` table) — one row per connector this codebase ships, matching
-- DATA_SOURCES.md. Connectors not built (blocked sources) are intentionally absent here; add a
-- row only when a real connector module exists for it.
INSERT OR IGNORE INTO sources (id, name, kind, is_free, base_url, notes) VALUES
    ('pokemontcg_io', 'Pokémon TCG API', 'catalog', 1, 'https://api.pokemontcg.io/v2',
        'English catalog + embedded TCGplayer/Cardmarket market price snapshot. DATA_SOURCES.md §1/§5.'),
    ('tcgdex', 'TCGdex', 'catalog', 1, 'https://api.tcgdex.net/v2',
        'Multi-language catalog (en/ja/zh-tw/zh-cn). DATA_SOURCES.md §1.'),
    ('ecb_fx', 'European Central Bank reference rates', 'fx', 1, 'https://www.ecb.europa.eu/stats/eurofxref',
        'Daily/historical EUR reference rates since 1999. DATA_SOURCES.md §2.');
