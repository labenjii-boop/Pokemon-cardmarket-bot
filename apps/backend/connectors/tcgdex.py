"""TCGdex connector — multi-language catalog (English, Japanese, Traditional & Simplified
Chinese; DATA_SOURCES.md §1). Free, no API key required.

TCGdex serves one REST tree per language, `/v2/{lang}/...`. This module is the primary source
for the Japanese and Chinese catalog scope required by Section 3; pokemontcg.io only covers
English. Chinese coverage varies per set (see the module docstring in DATA_SOURCES.md §1), so
`fetch_sets` for a Chinese locale can legitimately return an empty list for a given language —
callers must not treat that as an error.

Field names were verified against a real response during the first live run (2026-09):
`GET /v2/ja/sets` returns e.g. `{"id":"neo1","name":"...","cardCount":{"total":96,"official":96}}`
— matching what this module already parsed. The one real bug that first run surfaced: some set
ids contain a literal `+` (e.g. the real Japanese set `SM1+`), which needs percent-encoding
before going into a URL path — see `quote()` in `fetch_cards` below. An unencoded `+` 404s
against TCGdex's API even though a literal `+` is technically legal in a URL path per RFC 3986;
their server evidently decodes it as a space before route-matching.
"""
from __future__ import annotations

from typing import Iterable, Literal
from urllib.parse import quote

import httpx

from connectors._retry import get_with_retry
from connectors.base import CatalogCard, CatalogConnector, CatalogSet

BASE_URL = "https://api.tcgdex.net/v2"

# Maps our internal language codes to TCGdex's locale codes.
LANGUAGE_TO_TCGDEX = {
    "en": "en",
    "ja": "ja",
    "zh-tw": "zh-tw",
    "zh-cn": "zh-cn",
}


class TcgdexConnector(CatalogConnector):
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


def _infer_variant(raw: dict) -> str | None:
    variants = raw.get("variants") or {}
    if variants.get("firstEdition"):
        return "1st-edition"
    if variants.get("holo"):
        return "holo"
    if variants.get("reverse"):
        return "reverse-holo"
    return None
