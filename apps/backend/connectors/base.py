"""Shared connector interface (Section 5c rule 6).

Every data source — free or, one day, paid — implements one of the two small ABCs below and
nothing else in the app talks to `httpx`/HTML directly. That's the whole swappability contract:
`services/` and the API routes call `Connector.run()` and read the rows it returns; they don't
know or care whether the source is a REST API, a scraped page, or a paid vendor's SDK.

Two connector shapes cover everything in DATA_SOURCES.md:
  * `CatalogConnector`  — yields CatalogCard rows (card + set metadata).
  * `SnapshotConnector` — yields PriceObservation rows (a price at a point in time; this is
    also the shape a future real *sales* connector would use — a completed sale is just a price
    observation with `is_transaction=True`).

Each connector owns its own rate limiting/backoff/caching (Section 5c rule 5); `run()` is the
only method the rest of the app calls, and it must be safe to call repeatedly (idempotent
upserts on the DB side handle re-fetched data).
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Literal


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class CatalogSet:
    source: str
    source_set_id: str
    name: str
    language: Literal["en", "ja", "zh-cn", "zh-tw"]
    name_original: str | None = None
    series: str | None = None
    era: str | None = None
    total_cards: int | None = None
    release_date: str | None = None
    set_code: str | None = None


@dataclass(frozen=True)
class CatalogCard:
    source: str
    source_card_id: str
    set_source_set_id: str
    name: str
    number: str
    language: Literal["en", "ja", "zh-cn", "zh-tw"]
    name_original: str | None = None
    name_en: str | None = None
    set_total: int | None = None
    rarity: str | None = None
    variant: str | None = None
    release_date: str | None = None
    image_source_url: str | None = None


@dataclass(frozen=True)
class PriceObservation:
    """A single price data point for a card (+ optional grade) at a point in time.

    `is_transaction=False` means this is a market-price snapshot (Section 0 of
    DATA_SOURCES.md's adaptation); a future sold-price connector sets it True and the row is
    written into `sales` instead of `price_snapshots` — same dataclass, different destination
    table, decided by the caller in services/ingest.py, not by the connector.
    """

    source: str
    card_source_id: str
    observed_at: str
    price_amount: float
    price_currency: str
    grade_label: str | None = None  # None => ungraded/raw market price
    price_kind: Literal["market", "low", "mid", "high"] = "market"
    is_transaction: bool = False
    source_listing_id: str | None = None
    listing_title: str | None = None


class CatalogConnector(abc.ABC):
    source_id: str

    @abc.abstractmethod
    def fetch_sets(self) -> Iterable[CatalogSet]:
        ...

    @abc.abstractmethod
    def fetch_cards(self, set_source_set_id: str) -> Iterable[CatalogCard]:
        ...


class SnapshotConnector(abc.ABC):
    source_id: str

    @abc.abstractmethod
    def fetch_observations(self, since: str | None = None) -> Iterable[PriceObservation]:
        """`since`: ISO timestamp cursor for incremental polling; None means "everything this
        source currently exposes" (there is no deep history behind these sources — see
        DATA_SOURCES.md §0 — so a full fetch is just "today's snapshot", not a backfill)."""
        ...


class FxConnector(abc.ABC):
    source_id: str

    @abc.abstractmethod
    def fetch_rates(self, start_date: str, end_date: str) -> Iterable[tuple[str, str, float]]:
        """Yields (date, currency, eur_rate) tuples."""
        ...
