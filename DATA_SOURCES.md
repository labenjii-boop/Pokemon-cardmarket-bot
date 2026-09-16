# DATA_SOURCES.md — Free Data Source Research (Phase 1)

Researched: 2026-09-16. Budget is **€0** (Section 1 of the build spec): only sources that are
free to access, and only accessed in ways each source's terms of service / robots.txt allow, are
used by the app. This document is the source of truth for what each connector is allowed to do.
It will go stale — API terms change — so re-verify a source here before relying on it for a
release.

Legend for **Status**:
- ✅ **Free & compliant — used** — a connector for this exists or is planned.
- ⚠️ **Free but limited** — usable, but the free tier is narrow enough to change what the app can promise.
- 🚫 **Blocked for v1** — no free, ToS-compliant, automatable path was found. Documented so the
  gap is explicit rather than silently missing.
- 💰 **Paid — not used** — a free tier does not exist; excluded per the €0 budget rule.

---

## 0. Headline finding — read this first

The spec's data model is built around **individual completed-sale records** (Section 5a: eBay,
Yahoo Japan, Mercari, SNKRDUNK, TCGplayer, Cardmarket, auction houses). After researching every
source in that list, **none of them currently offers a free, ToS-compliant, automatable feed of
individual sold-item prices**:

- eBay retired the only API that ever exposed sold/completed listings (Finding API, dead since
  Feb 2025). Its replacement, the Marketplace Insights API, is real but is a **Limited Release**
  gated behind eBay Business-team approval — not something a personal developer account can get.
  eBay's Browse API is free and open, but by design returns **active listings only**, never sold
  prices. Scraping eBay's own "completed/sold" search pages (`LH_Complete=1&LH_Sold=1`) would
  work technically, but eBay's User Agreement prohibits automated scraping of the site — so per
  Section 5c rule 4 ("do not build anything that bypasses... anti-bot protections" / only ToS-
  permitted access), that path is **not used**.
- Mercari, SNKRDUNK, and Yahoo! Auctions Japan (as far as could be confirmed for the buyer/read
  side) have no self-serve public developer API. Mercari's API is confirmed partner-only, gated
  by direct business agreements.
- TCGplayer closed its official API to new developer applications; existing keys keep working,
  but the app cannot get one.
- Cardmarket's API requires an approved developer application and is oriented at shop/seller
  order management, not general read access to sale history.
- The big auction houses (Goldin, Heritage, Fanatics Collect/PWCC) publish no public API; any
  access would mean per-site scraping, which was not verified as ToS-compliant for any of them.

**What this means for the build (per Section 5c rule 7):** the app **cannot**, for €0, assemble
the kind of true "every completed sale, every marketplace" ledger the spec describes for eBay,
Yahoo Japan, Mercari, SNKRDUNK, TCGplayer, Cardmarket, or the auction houses. This affects
Sections 5a, 6 (10-year backfill), 7 (real-time sales feed), and — most importantly — **Section 2
(Top 100 Hottest Cards)**, whose ranking is defined in terms of sale prices.

**The adaptation used throughout this build:** two free, official, ToS-compliant sources —
**pokemontcg.io** and **TCGdex** — republish aggregated *current market price* data that they in
turn source from TCGplayer (USD) and Cardmarket (EUR) for each card. This is not an individual
sale record, but it **is** a legitimate, free, regularly-refreshed price observation per
card/variant. The app treats each fetch as a **price snapshot** (a `price_snapshots` connector,
see `apps/backend`), building its own time series forward from day one — exactly what Section 6
says to do where deep history isn't available ("the app builds its own history going forward by
recording every new observation it detects"). The Top 100 ranking (Section 2) is computed from
these snapshots instead of raw sales counts; "number of sales in the period" is reinterpreted as
"number of price snapshots / observed price points" until a compliant sales feed exists. This is
called out again in the ranking-methodology doc once that phase is built, and the UI must label
data as "market price" rather than "sale price" so it isn't misread as transaction data.

If, later, the user obtains paid/approved access to eBay Marketplace Insights, an official
Cardmarket seller account, or a TCGplayer key from before the shutdown, the connector interface
(Section 5c rule 6) is designed so a real sold-price connector can be dropped in without touching
the rest of the system — see `apps/backend/connectors/README.md`.

---

## 1. Card catalog sources

| Source | Status | Access method | Notes |
|---|---|---|---|
| **pokemontcg.io (v2)** | ✅ | REST, no key: 1,000 req/day. Free key (self-serve signup): 20,000 req/day. | English-only catalog. Each card response embeds current TCGplayer (USD) and Cardmarket (EUR) aggregate pricing — this is a price-snapshot source, not a sales feed. **Risk confirmed in practice**, not just in the docs: during the first real run (2026-09) this API returned repeated `502 Bad Gateway` on its `/cards` endpoint while TCGdex and ECB were both fine — consistent with the in-progress migration of the free v2 tier to a paid "Scrydex" product mentioned in its docs. Treat it as the less reliable of the two price sources; TCGdex is the one to lean on. |
| **TCGdex** | ✅ | REST + GraphQL, **no key required**, generous/unthrottled-by-default free tier. Official SDKs (Python, JS/TS, PHP, Java/Kotlin, Rust). | Multi-language: 130k+ cards across 10+ languages including Japanese and Chinese (Traditional confirmed; Simplified coverage varies by set and must be verified card-by-card — see Section 3 note below). This is the primary source for the Japanese and Chinese catalog scope required by Section 3, **and** — confirmed via a real card response — a second price-snapshot source (`pricing.cardmarket.trend` EUR, `pricing.tcgplayer.<finish>.marketPrice` USD). Unlike pokemontcg.io, pricing only lives on the per-card detail endpoint (not the set-listing one), so it's polled in rotating batches rather than all at once — see `apps/backend/connectors/tcgdex.py` and `services/jobs.py`. |
| Bulbapedia / Serebii | ✅ (manual/reference) | Public wiki pages, no API. Usable for backfilling metadata gaps (translations, release dates) via occasional, low-volume, robots.txt-respecting fetches — not a bulk connector. | Used as a fallback enrichment source, not a primary connector. |
| Official Pokémon TCG regional sites | ⚠️ | No structured API; would require per-region scraping. | Not built as a connector in v1; flagged for manual research if TCGdex has catalog gaps in a specific region. |

**Simplified vs Traditional Chinese (Section 3 requirement):** TCGdex's Chinese coverage needs to
be checked per-set at import time — the importer records which of `zh-cn` / `zh-tw` (or
equivalent locale codes) actually returned data for each set, and the catalog schema keeps them
as fully separate `sets`/`cards` rows (never merged), per the spec's explicit requirement.

**Pokémon TCG Pocket is out of scope and excluded (confirmed 2026-09):** TCGdex catalogs
**Pokémon TCG Pocket** — a separate, digital-only mobile game — through the same `/sets` and
`/cards` endpoints as the physical trading card game this app tracks (set ids like `A1`,
`serie.id == "tcgp"`). This surfaced as a real bug: a price-poll batch came back with 300/300
zero-price cards, all Pocket cards, because they're not physical objects and can never have a
TCGplayer/Cardmarket listing. The catalog importer (`connectors/tcgdex.py`) now records Pocket
sets (for visibility/traceability) but never imports their cards, so nothing Pocket-sourced ever
reaches price polling. If TCG Pocket tracking is ever wanted, it needs its own explicit scope
decision (Section 1) and its own ranking treatment — it doesn't fit the physical-card pricing
model (Section 2's "start price"/"current price" concept) at all.

## 2. Foreign exchange rates

| Source | Status | Access method | Notes |
|---|---|---|---|
| **ECB (European Central Bank) reference rates** | ✅ | Two equivalent free paths: (1) direct daily/historical XML feed (`eurofxref-daily.xml` / `eurofxref-hist.xml`), no key; (2) ECB Statistical Data Warehouse SDMX 2.1 REST API, no key. | EUR-based rates including DKK, back to 1999 — comfortably covers the 10-year backfill window (Section 6). This is the authoritative source named in Section 8. |
| Frankfurter API | ✅ (mirror) | Free, no key, re-publishes ECB reference rates as simple JSON. | Used only as a convenience/fallback mirror of the same ECB data — the connector's source-of-record stays the ECB feed for the `fx_rates.source` column. |

## 3. Marketplaces — completed sales (Section 5a)

| Source | Status | Details |
|---|---|---|
| eBay (.com, .co.uk, .de, .com.au, etc.) | 🚫 (sold data) / ✅ (active listings only) | Developer Program signup is free (see Section 4 below for the step-by-step). Browse API is free and gives active-listing search/price — usable for a "currently listed at" reference point, not a sale. Marketplace Insights API (sold prices, 90-day lookback) requires eBay Business-team approval; not obtainable as a personal free-tier developer. Finding API (the old sold-listings API) was decommissioned Feb 2025. **No connector for actual sold prices in v1.** |
| Yahoo! Auctions Japan | 🚫 (to re-verify) | An official Yahoo! JAPAN Webasa API for auctions was historically documented at `developer.yahoo.co.jp/webapi/auctions/`. Current status/coverage for sold-price history could not be confirmed as still live and free during this research pass — treat as **unverified**, not confirmed free, until someone actually completes Yahoo JAPAN developer registration and checks the current ToS/scope. Not built as a connector until that verification happens. |
| Mercari (US & Japan) | 🚫 | Confirmed: no public self-serve developer API. Mercari's API surface is partner-only (shipping/payment partners under direct agreement). Mercari Shops has a separate, unrelated shop-management API, not a market data feed. |
| SNKRDUNK | 🚫 | No public developer API found. |
| Card Rush / other Japanese card shops | 🚫 | Not individually researched (long tail of sites); would each need its own robots.txt/ToS review before a connector could be built. Flagged for future research, not attempted in v1. |
| TCGplayer | 🚫 | Official API is closed to new developer applications ("no price published — because it isn't available at any price for new developers"). Existing partners' keys still work, but this project has none. |
| Cardmarket | 🚫 | Official REST API (OAuth 1.0) exists but requires an approved developer application and is scoped for shop/order management; not confirmed as grantable for a personal, read-only, non-seller use case. Flagged for the user to apply for directly if they want to pursue it (Section 5c rule 3 process) — not assumed available. |
| Goldin, Heritage Auctions, Fanatics Collect (ex-PWCC) | 🚫 | No public API for any of the three. Each publishes historical results on its own site; scraping ToS was not verified for any of them in this pass. |
| Chinese-market platforms (Xianyu/闲鱼, Youpin/得物, TCG-specific marketplaces) | 🚫 | Not yet researched in depth. Xianyu (Alibaba/Taobao-affiliated) and similar platforms are known to have strict anti-bot measures and no public sales API; flagged for dedicated research before any connector is attempted. |

## 4. Existing trackers / aggregators (Section 5b — cross-reference only, not primary ingestion)

| Source | Status | Details |
|---|---|---|
| PriceCharting | 💰 | API has **no free tier** at all (paid key required for any programmatic access); historical sales are explicitly out of scope even on paid plans ("only current item values"). Not used. |
| 130point | 🚫 | No official public developer API. It is itself a third party that pulls from eBay's official APIs plus scraping/heuristics — i.e., exactly the kind of derived-data source Section 5c rule 4 tells us not to build on top of without independent compliant access. |
| Card Ladder, Alt, Collectr | 🚫 | Consumer apps/products, not public data APIs. Not researched further — no indication of a free public API. |
| PSA Auction Prices Realized / Population Report | ⚠️ | PSA's *official* public API is cert-number verification only, and as of mid-2026 is rate-limited to roughly 1 call/day even for a registered free token — population and price-guide data now sit behind a paid PSA API plan. The free-to-browse website (`psacard.com/auctionprices`) has no accompanying API. **Not built as an automated connector**; certificate-number lookups (Section 8, "certificate data") could use the ~1/day free cert-verification endpoint opportunistically, but that's too thin to rely on. |
| CGC / BGS population data | 🚫 | No free public API for either; population figures are only available via the companies' own websites (manual lookup) or paid third-party scraper products. |

## 5. Step-by-step: the one account worth creating now

Only **pokemontcg.io**'s optional free API key is worth setting up before Phase 3 (TCGdex needs
no key at all):

1. Go to `https://pokemontcg.io/` and use "Get an API Key" (free, self-serve, email signup).
2. Copy the key.
3. In the running app: **Settings → API Keys → Pokémon TCG API**, paste it there. It is stored in
   the macOS Keychain (Section 10), never in a config file or in code.
4. Without a key the app still works, just capped at 1,000 requests/day instead of 20,000 —
   fine for catalog import, tight for frequent price-snapshot polling of a large catalog.

An eBay Developer Program account is optional and only unlocks the *active-listings* Browse API
(not sold prices); instructions are kept in `apps/backend/connectors/ebay/README.md` so they sit
next to the connector that would use them, rather than here.

## 6. Consequences for later phases (explicit, per Section 5c rule 7)

- **Section 2 (Top 100 Hottest Cards):** ranks by market-price-snapshot movement, not sale
  price movement. "Number of sales in the period" becomes "number of price observations."
  Labelled as such in the UI.
- **Section 6 (10-year backfill):** there is no free bulk historical *sales* archive anywhere in
  this list. FX rates get the full 10 years from ECB. Card catalog metadata (not prices) is
  backfillable in full since it's static. Price history only starts accumulating from the day the
  app is first run, via the snapshot connectors — there is no shortcut to a deep price history.
- **Section 7 (real-time tracking):** the "live sales feed" becomes a "live price-snapshot feed."
  No source here provides real-time sold-item pushes for free.
- **Section 8 (certificate data):** PSA cert lookups are possible but rate-capped to ~1/day free;
  not something to rely on for bulk cert linking.
- **Section 9 (analytics):** grade-to-grade and cross-language comparisons, set/market indexes,
  and biggest-movers lists all still work on snapshot data — they just describe price levels
  rather than realized transaction prices.

This is a foundational constraint, not a bug to fix later — it's what "free and ToS-compliant
only" actually buys in this market today. If priorities change, the connector architecture
(`apps/backend/connectors/`) is designed to slot a real sales connector in later without a rewrite.
