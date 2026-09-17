"""TCGdex connector — multi-language catalog (English, Japanese, Traditional & Simplified
Chinese; DATA_SOURCES.md §1). Free, no API key required.

TCGdex serves one REST tree per language, `/v2/{lang}/...`. This module is the primary source
for the Japanese and Chinese catalog scope required by Section 3; pokemontcg.io only covers
English. Chinese coverage varies per set (see the module docstring in DATA_SOURCES.md §1), so
`fetch_sets` for a Chinese locale can legitimately return an empty list for a given language —
callers must not treat that as an error.

Field names were verified against real responses during the first live run (2026-09):
`GET /v2/ja/sets` returns e.g. `{"id":"neo1","name":"...","cardCount":{"total":96,"official":96}}`
— matching what this module already parsed. The one real bug that first run surfaced: some set
ids contain a literal `+` (e.g. the real Japanese set `SM1+`), which needs percent-encoding
before going into a URL path — see `quote()` in `fetch_cards` below. An unencoded `+` 404s
against TCGdex's API even though a literal `+` is technically legal in a URL path per RFC 3986;
their server evidently decodes it as a space before route-matching.

Pricing (used by `fetch_observations` below) only appears on the per-card detail endpoint
(`GET /v2/{lang}/cards/{id}`) — the brief per-card entries returned inside a set listing (what
`fetch_cards` reads) are just `{id, image, localId, name}`, no pricing. A real per-card response
looks like:
    "pricing": {
      "cardmarket": {"unit": "EUR", "trend": 3687.39, "avg": 1566.65, "low": 420, ...},
      "tcgplayer": {"unit": "USD", "holofoil": {"marketPrice": 1500, ...}, "reverse-holofoil": {...}}
    }
`cardmarket`/`tcgplayer` (or the whole `pricing` object) can be missing/null when a card isn't
listed on that marketplace — treated as "no observation from that source," not an error.

TCGdex also catalogs **Pokémon TCG Pocket** — a separate, digital-only mobile game — through the
same `/sets` and `/cards` endpoints as the physical trading card game this app tracks. Pocket
cards can never have TCGplayer/Cardmarket pricing (they're not physical objects anyone buys or
sells), which is exactly what a real price poll surfaced: a 300-card batch that returned zero
prices, all from set "A1" ("Genetic Apex"). Confirmed via the set detail endpoint
(`GET /v2/en/sets/A1`) that Pocket sets carry `"serie": {"id": "tcgp", ...}`, vs. a physical set
like Base Set's `"serie": {"id": "base", ...}` — the set-*list* endpoint doesn't expose `serie`
at all, so `fetch_sets` below fetches each set's detail (one extra request per set, during the
weekly catalog refresh, not the frequent price poll) specifically to capture this and
`releaseDate` (also list-endpoint-absent). Pocket sets are still recorded in `sets` (so they're
visible/traceable), but `fetch_cards` skips importing any of their cards — see the `serie` check
there — so nothing Pocket-sourced ever reaches price polling in the first place.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable, Literal
from urllib.parse import quote

import httpx

from connectors._retry import get_with_retry
from connectors.base import CatalogCard, CatalogConnector, CatalogSet, PriceObservation, SnapshotConnector, utcnow_iso

logger = logging.getLogger(__name__)

BASE_URL = "https://api.tcgdex.net/v2"

# Maps our internal language codes to TCGdex's locale codes.
LANGUAGE_TO_TCGDEX = {
    "en": "en",
    "ja": "ja",
    "zh-tw": "zh-tw",
    "zh-cn": "zh-cn",
}


class TcgdexConnector(CatalogConnector, SnapshotConnector):
    source_id = "tcgdex"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=30.0)

    def close(self) -> None:
        self._client.close()

    def fetch_sets(self) -> Iterable[CatalogSet]:
        for lang in LANGUAGE_TO_TCGDEX:
            yield from self._fetch_sets_for_language(lang)

    def _fetch_sets_for_language(self, language: Literal["en", "ja", "zh-cn", "zh-tw"]) -> Iterable[CatalogSet]:
        locale = LANGUAGE_TO_TCGDEX[language]
        resp = get_with_retry(self._client, f"/{locale}/sets")
        if resp.status_code == 404:
            return  # this language has no sets in TCGdex yet — not an error (see module docstring)
        resp.raise_for_status()
        for raw in resp.json():
            detail = self._fetch_set_detail(locale, raw["id"])
            yield CatalogSet(
                source=self.source_id,
                source_set_id=f"{locale}:{raw['id']}",
                name=raw.get("name", raw["id"]),
                language=language,
                total_cards=(raw.get("cardCount", {}) or {}).get("official") or (raw.get("cardCount", {}) or {}).get("total"),
                release_date=(detail or {}).get("releaseDate"),
                set_code=raw.get("id"),
                series=((detail or {}).get("serie") or {}).get("id"),
            )

    def _fetch_set_detail(self, locale: str, tcgdex_set_id: str) -> dict | None:
        """`releaseDate` and `serie` (used to filter out Pokémon TCG Pocket — see module
        docstring) only exist here, not on the cheap set-list response `fetch_sets` starts from.
        Returns None on a transient failure rather than raising, so one bad set doesn't abort
        the whole catalog refresh — see `_import_from_connector` in services/jobs.py for the
        equivalent pattern at the per-set-cards level."""
        resp = get_with_retry(self._client, f"/{locale}/sets/{quote(tcgdex_set_id, safe='')}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def fetch_cards(self, set_source_set_id: str) -> Iterable[CatalogCard]:
        locale, tcgdex_set_id = set_source_set_id.split(":", 1)
        language = next(lang for lang, loc in LANGUAGE_TO_TCGDEX.items() if loc == locale)
        resp = get_with_retry(self._client, f"/{locale}/sets/{quote(tcgdex_set_id, safe='')}")
        resp.raise_for_status()
        raw_set = resp.json()
        if (raw_set.get("serie") or {}).get("id") == "tcgp":
            return  # Pokémon TCG Pocket (digital-only) — see module docstring; catalogued as a
            # set for visibility, but its cards are never imported, so they never reach pricing.
        for raw in raw_set.get("cards", []):
            yield CatalogCard(
                source=self.source_id,
                source_card_id=f"{locale}:{raw['id']}",
                set_source_set_id=set_source_set_id,
                name=raw.get("name", raw["id"]),
                name_original=raw.get("name") if language != "en" else None,
                number=raw.get("localId", raw["id"]),
                language=language,
                rarity=raw.get("rarity"),
                variant=_infer_variant(raw),
                image_source_url=raw.get("image"),
            )

    # -- SnapshotConnector ------------------------------------------------------------------

    def fetch_observations(
        self, since: str | None = None, card_ids: list[str] | None = None
    ) -> Iterable[PriceObservation]:
        """Pricing only lives on the per-card detail endpoint (see module docstring) — one
        request per id in `card_ids`, so unlike pokemontcg.io this can't cheaply do "everything."
        `card_ids` is required, not optional in practice; services/jobs.py is what decides which
        ids to pass (a rotating batch — see its module docstring for why)."""
        if not card_ids:
            raise ValueError(
                "TcgdexConnector.fetch_observations requires card_ids: pricing only exists on "
                "the per-card detail endpoint, so there is no cheap 'fetch everything' here."
            )
        observed_at = utcnow_iso()
        for source_card_id in card_ids:
            locale, tcgdex_id = source_card_id.split(":", 1)
            try:
                resp = get_with_retry(self._client, f"/{locale}/cards/{quote(tcgdex_id, safe='')}")
                if resp.status_code == 404:
                    continue  # card id we catalogued no longer resolves upstream — skip, not fatal
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                # One card in a 300-card batch failing (after retries already exhausted in
                # get_with_retry) must not throw away the other 299 — log it and keep going.
                logger.warning("skipping %s after a persistent error: %s", source_card_id, exc)
                continue
            yield from _observations_from_card_detail(source_card_id, resp.json(), observed_at)

    def fetch_price_history_backfill(self, source_card_id: str) -> list[PriceObservation]:
        """A brand-new card only polled once or twice looks like a flat, pointless chart until
        the rotation revisits it enough times over real elapsed hours/days for a shape to emerge
        (see _select_cards_for_tcgdex_poll in services/jobs.py). Cardmarket's per-card response
        already carries its own rolling historical averages — avg1/avg7/avg30 — right alongside
        the current 'trend' price, in the exact same request `fetch_observations` already makes.
        This turns those into backdated PriceObservations so a card's chart has real (if
        approximate — a rolling average isn't literally "the price on that exact day") shape the
        first time anyone actually looks at it, instead of making them wait for the background
        rotation. Called on demand from GET /cards/{id}/prices (app/main.py) the first time a
        card with thin history is opened — not part of the regular poll, which would otherwise
        reinsert the same three backdated points every run for no benefit."""
        locale, tcgdex_id = source_card_id.split(":", 1)
        resp = get_with_retry(self._client, f"/{locale}/cards/{quote(tcgdex_id, safe='')}")
        resp.raise_for_status()
        return _backfill_observations_from_card_detail(source_card_id, resp.json())

    def fetch_card_variant_pricing(self, source_card_id: str) -> dict[str, dict[str, float]]:
        """Live, on-demand breakdown of a card's price *per physical print variant* (holo,
        reverse holo, 1st edition, etc) — the exact data `_observations_from_card_detail`
        deliberately does NOT turn into stored PriceObservations (see its docstring: mixing
        variants into one time series was the bug behind a chart that looked like noise). This
        is the correct place for that per-variant breakdown to live: a live snapshot for the
        card detail page's "variant pricing" section, not a stored series, so it can't collide
        with — or reintroduce the bug in — the main price history.
        """
        locale, tcgdex_id = source_card_id.split(":", 1)
        resp = get_with_retry(self._client, f"/{locale}/cards/{quote(tcgdex_id, safe='')}")
        resp.raise_for_status()
        pricing = resp.json().get("pricing") or {}
        return {
            "cardmarket_eur": _parse_cardmarket_variants(pricing.get("cardmarket") or {}),
            "tcgplayer_usd": _parse_tcgplayer_variants(pricing.get("tcgplayer") or {}),
        }


# Cardmarket has no variant *list* — each variant's price is just a separate flat key, named
# "<metric>" (the base/normal variant) or "<metric>-<variant>" (e.g. "trend-holo"). Preferring
# 'trend' over the avg* fields mirrors what _observations_from_card_detail already treats as the
# canonical "current price" signal.
_CARDMARKET_METRIC_PREFIXES = ("trend", "avg30", "avg7", "avg1", "avg", "low")


def _parse_cardmarket_variants(cardmarket: dict) -> dict[str, float]:
    # Pass 1: which variants exist at all, from whichever keys are present (dict iteration
    # order is arbitrary, so this can't also pick *values* — see pass 2).
    variant_names: set[str] = set()
    for key in cardmarket:
        for prefix in _CARDMARKET_METRIC_PREFIXES:
            if key == prefix:
                variant_names.add("normal")
                break
            if key.startswith(prefix + "-"):
                variant_names.add(key[len(prefix) + 1 :])
                break

    # Pass 2: for each variant, walk the prefixes in *preference* order (trend beats avg beats
    # low) and take the first one that's actually present — independent of dict key order, which
    # a naive single-pass setdefault() got wrong (whichever key the dict happened to yield first
    # would win, not whichever metric this module treats as canonical).
    variants: dict[str, float] = {}
    for variant in variant_names:
        for prefix in _CARDMARKET_METRIC_PREFIXES:
            key = prefix if variant == "normal" else f"{prefix}-{variant}"
            value = cardmarket.get(key)
            if isinstance(value, (int, float)):
                variants[variant] = float(value)
                break
    return variants


def _parse_tcgplayer_variants(tcgplayer: dict) -> dict[str, float]:
    variants: dict[str, float] = {}
    for finish, prices in tcgplayer.items():
        if not isinstance(prices, dict):
            continue  # 'unit'/'updated' are sibling string fields alongside the per-finish dicts
        market = prices.get("marketPrice")
        if market is not None:
            variants[finish] = float(market)
    return variants


def _observations_from_card_detail(source_card_id: str, raw: dict, observed_at: str) -> Iterable[PriceObservation]:
    """Yields at most ONE observation per card per poll — a real bug surfaced by a live chart
    that looked like noise instead of a trend: `pricing.tcgplayer` breaks its price down *per
    print variant* (e.g. "holofoil", "reverse-holofoil" can both exist for the same card id, as
    separate physical products with genuinely different values), and the original code emitted
    one PriceObservation per variant, all stamped with the same observed_at and all landing in
    the same ungraded 'raw-nm' bucket for this one `card_id` — three or more conflicting prices
    at the same instant, exactly the kind of outlier-prone signal Section 2 asks the app to
    resist, not manufacture. Our catalog doesn't model print variants as separate rows (a
    card_id is one row), so there's no correct per-variant destination to split them into yet;
    until there is, Cardmarket's `trend` is used because it's already a single, unambiguous
    number per card — no variant-picking heuristic needed — and EUR is this app's own display
    currency (Section 1), unlike TCGplayer's USD breakdown.
    """
    trend = ((raw.get("pricing") or {}).get("cardmarket") or {}).get("trend")
    if trend is not None:
        yield PriceObservation(
            source="tcgdex",
            card_source_id=source_card_id,
            observed_at=observed_at,
            price_amount=float(trend),
            price_currency="EUR",
            price_kind="market",
        )


# Cardmarket's own rolling averages, backdated to roughly the window each one covers. Ordered
# oldest-offset first purely for readability; ingest order doesn't matter (see ingest.py).
_CARDMARKET_HISTORY_OFFSETS: tuple[tuple[str, timedelta], ...] = (
    ("avg30", timedelta(days=30)),
    ("avg7", timedelta(days=7)),
    ("avg1", timedelta(days=1)),
)


def _backfill_observations_from_card_detail(source_card_id: str, raw: dict) -> list[PriceObservation]:
    cardmarket = (raw.get("pricing") or {}).get("cardmarket") or {}
    now = datetime.now(timezone.utc)
    observations: list[PriceObservation] = []
    for key, offset in _CARDMARKET_HISTORY_OFFSETS:
        value = cardmarket.get(key)
        if not isinstance(value, (int, float)):
            continue
        observations.append(
            PriceObservation(
                source="tcgdex",
                card_source_id=source_card_id,
                observed_at=(now - offset).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                price_amount=float(value),
                price_currency="EUR",
                price_kind="market",
            )
        )
    return observations


def _infer_variant(raw: dict) -> str | None:
    variants = raw.get("variants") or {}
    if variants.get("firstEdition"):
        return "1st-edition"
    if variants.get("holo"):
        return "holo"
    if variants.get("reverse"):
        return "reverse-holo"
    return None
