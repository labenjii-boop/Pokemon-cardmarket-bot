"""pokemontcg.io v2 connector — English catalog + embedded market-price snapshot.

Free tier: 1,000 requests/day without a key, 20,000/day with a free key (DATA_SOURCES.md §1/§5).
The API embeds current TCGplayer (USD) and Cardmarket (EUR) aggregate pricing on every card
response — that pricing is what `fetch_observations` turns into `PriceObservation` rows, since
no free/compliant per-sale feed exists for TCGplayer or Cardmarket (DATA_SOURCES.md §0).
"""
from __future__ import annotations

from typing import Iterable

import httpx

from connectors._retry import get_with_retry
from connectors.base import CatalogCard, CatalogConnector, CatalogSet, PriceObservation, SnapshotConnector, utcnow_iso

BASE_URL = "https://api.pokemontcg.io/v2"
# 250 (the API's max) turned out to trigger 500s on the free tier in practice; 100 is the safer
# default this connector was actually observed working reliably at.
PAGE_SIZE = 100


class PokemonTcgIoConnector(CatalogConnector, SnapshotConnector):
    source_id = "pokemontcg_io"

    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None):
        headers = {"X-Api-Key": api_key} if api_key else {}
        self._client = client or httpx.Client(base_url=BASE_URL, headers=headers, timeout=30.0)

    def close(self) -> None:
        self._client.close()

    # -- CatalogConnector -----------------------------------------------------------------

    def fetch_sets(self) -> Iterable[CatalogSet]:
        page = 1
        while True:
            resp = get_with_retry(self._client, "/sets", params={"page": page, "pageSize": PAGE_SIZE})
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if not data:
                return
            for raw in data:
                yield CatalogSet(
                    source=self.source_id,
                    source_set_id=raw["id"],
                    name=raw["name"],
                    language="en",
                    series=raw.get("series"),
                    total_cards=(raw.get("printedTotal") or raw.get("total")),
                    release_date=raw.get("releaseDate"),
                    set_code=raw.get("ptcgoCode"),
                )
            page += 1

    def fetch_cards(self, set_source_set_id: str) -> Iterable[CatalogCard]:
        page = 1
        while True:
            resp = get_with_retry(
                self._client,
                "/cards",
                params={"q": f"set.id:{set_source_set_id}", "page": page, "pageSize": PAGE_SIZE},
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if not data:
                return
            for raw in data:
                yield CatalogCard(
                    source=self.source_id,
                    source_card_id=raw["id"],
                    set_source_set_id=set_source_set_id,
                    name=raw["name"],
                    name_en=raw["name"],
                    number=raw.get("number", ""),
                    language="en",
                    set_total=(raw.get("set", {}).get("printedTotal")),
                    rarity=raw.get("rarity"),
                    variant=_infer_variant(raw),
                    release_date=raw.get("set", {}).get("releaseDate"),
                    image_source_url=(raw.get("images", {}) or {}).get("large") or (raw.get("images", {}) or {}).get("small"),
                )
            page += 1

    # -- SnapshotConnector ------------------------------------------------------------------

    def fetch_observations(
        self, since: str | None = None, card_ids: list[str] | None = None
    ) -> Iterable[PriceObservation]:
        """Iterates every card and emits one market-price observation per pricing point the API
        reports (TCGplayer 'market' price in USD, Cardmarket 'trend' price in EUR). `since` and
        `card_ids` are accepted for interface parity but unused: this endpoint has no incremental
        cursor and paging through the whole catalog is cheap here (unlike TCGdex — see
        connectors/base.py), so a full fetch is always "everything, right now."
        """
        page = 1
        observed_at = utcnow_iso()
        while True:
            resp = get_with_retry(self._client, "/cards", params={"page": page, "pageSize": PAGE_SIZE})
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if not data:
                return
            for raw in data:
                yield from _observations_from_card(raw, observed_at)
            page += 1


def _infer_variant(raw: dict) -> str | None:
    subtypes = raw.get("subtypes") or []
    if "1st Edition" in (raw.get("name", "") or ""):
        return "1st-edition"
    if any(s.lower() == "vmax" or s.lower() == "vstar" for s in subtypes):
        return None
    tcgplayer = raw.get("tcgplayer", {}).get("prices", {}) or {}
    if "1stEditionHolofoil" in tcgplayer:
        return "1st-edition-holo"
    if "reverseHolofoil" in tcgplayer:
        return "reverse-holo"
    if "holofoil" in tcgplayer:
        return "holo"
    return None


def _observations_from_card(raw: dict, observed_at: str) -> Iterable[PriceObservation]:
    """Yields at most ONE observation per card per poll — see the near-identical fix and full
    explanation in connectors/tcgdex.py's _observations_from_card_detail: `tcgplayer.prices`
    breaks its price down per print variant (holofoil, reverseHolofoil, etc — separate physical
    products), and looping over all of them used to emit several conflicting "market price"
    observations for the same card_id at the same instant. Cardmarket's single trendPrice avoids
    that ambiguity and matches this app's own EUR/DKK display currency (Section 1)."""
    card_id = raw["id"]
    trend = ((raw.get("cardmarket") or {}).get("prices") or {}).get("trendPrice")
    if trend is not None:
        yield PriceObservation(
            source="pokemontcg_io",
            card_source_id=card_id,
            observed_at=observed_at,
            price_amount=float(trend),
            price_currency="EUR",
            price_kind="market",
        )
