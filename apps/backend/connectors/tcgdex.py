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
"""
from __future__ import annotations

import logging
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
            yield CatalogSet(
                source=self.source_id,
                source_set_id=f"{locale}:{raw['id']}",
                name=raw.get("name", raw["id"]),
                language=language,
                total_cards=(raw.get("cardCount", {}) or {}).get("official") or (raw.get("cardCount", {}) or {}).get("total"),
                release_date=raw.get("releaseDate"),
                set_code=raw.get("id"),
            )

    def fetch_cards(self, set_source_set_id: str) -> Iterable[CatalogCard]:
        locale, tcgdex_set_id = set_source_set_id.split(":", 1)
        language = next(lang for lang, loc in LANGUAGE_TO_TCGDEX.items() if loc == locale)
        resp = get_with_retry(self._client, f"/{locale}/sets/{quote(tcgdex_set_id, safe='')}")
        resp.raise_for_status()
        raw_set = resp.json()
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


def _observations_from_card_detail(source_card_id: str, raw: dict, observed_at: str) -> Iterable[PriceObservation]:
    pricing = raw.get("pricing") or {}

    cardmarket = pricing.get("cardmarket") or {}
    trend = cardmarket.get("trend")
    if trend is not None:
        yield PriceObservation(
            source="tcgdex",
            card_source_id=source_card_id,
            observed_at=observed_at,
            price_amount=float(trend),
            price_currency="EUR",
            price_kind="market",
        )

    tcgplayer = pricing.get("tcgplayer") or {}
    for finish, prices in tcgplayer.items():
        if not isinstance(prices, dict):
            continue  # 'unit'/'updated' are sibling string fields alongside the per-finish dicts
        market = prices.get("marketPrice")
        if market is not None:
            yield PriceObservation(
                source="tcgdex",
                card_source_id=source_card_id,
                observed_at=observed_at,
                price_amount=float(market),
                price_currency="USD",
                price_kind="market",
            )


def _infer_variant(raw: dict) -> str | None:
    variants = raw.get("variants") or {}
    if variants.get("firstEdition"):
        return "1st-edition"
    if variants.get("holo"):
        return "holo"
    if variants.get("reverse"):
        return "reverse-holo"
    return None
