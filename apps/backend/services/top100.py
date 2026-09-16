"""Top 100 Hottest Cards ranking (Section 2). Pure functions over already-fetched observation
rows — no DB or HTTP here — so the ranking rules are unit-testable in isolation and the
methodology is documented once, in code, rather than split across a query and a doc.

Methodology (Section 2's "define and document" requirement):

  * "Start price" = the MEDIAN of every price observation in the first `edge_fraction` (default
    10%) of the selected time range, clamped to at least `min_edge_days` (default 1 day) so a
    1-day range still has a sensible window. Same for "end price", mirrored at the other edge.
    Using the median of a window instead of a single first/last sale is exactly what Section 2
    asks for: "so single outlier sales don't distort the ranking."
  * A card+grade+language entry only qualifies if it has at least `min_observations` price
    points in the *whole* selected range (Section 2: "require a minimum number of sales in the
    period... adjustable in settings"). This repo currently populates `price_snapshots`, not
    `sales` — see DATA_SOURCES.md §0 — so "observations" here means price-snapshot points until
    a real sold-price connector exists; the ranking code itself is agnostic to which table fed
    it, so it needs no change on that day.
  * Rows already excluded by the cleaning pipeline (`is_excluded` on `sales`, Section 8) must be
    filtered out by the caller before building a `CardSeries` — this module trusts its input.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

SortKey = Literal["change_pct", "change_abs", "volume"]


@dataclass(frozen=True)
class RankingSettings:
    min_observations: int = 3
    edge_fraction: float = 0.1
    min_edge: timedelta = timedelta(days=1)
    min_price_eur: float = 0.0


@dataclass(frozen=True)
class Observation:
    observed_at: datetime
    price_eur: float


@dataclass(frozen=True)
class CardSeries:
    card_id: str
    grade_id: str
    observations: tuple[Observation, ...]


@dataclass(frozen=True)
class RankedEntry:
    card_id: str
    grade_id: str
    start_price_eur: float
    end_price_eur: float
    change_pct: float
    change_abs_eur: float
    observation_count: int


def _edge_window(period_start: datetime, period_end: datetime, settings: RankingSettings) -> timedelta:
    span = period_end - period_start
    return max(span * settings.edge_fraction, settings.min_edge)


def compute_entry(
    series: CardSeries,
    period_start: datetime,
    period_end: datetime,
    settings: RankingSettings = RankingSettings(),
) -> RankedEntry | None:
    in_range = [o for o in series.observations if period_start <= o.observed_at <= period_end]
    if len(in_range) < settings.min_observations:
        return None

    edge = _edge_window(period_start, period_end, settings)
    start_window = [o.price_eur for o in in_range if o.observed_at <= period_start + edge]
    end_window = [o.price_eur for o in in_range if o.observed_at >= period_end - edge]

    # Degenerate case: every observation falls in the overlap of both windows (very sparse data,
    # or a range shorter than 2x the edge window) — fall back to first/last single observation
    # rather than disqualifying the card outright.
    if not start_window:
        start_window = [in_range[0].price_eur]
    if not end_window:
        end_window = [in_range[-1].price_eur]

    start_price = statistics.median(start_window)
    end_price = statistics.median(end_window)

    if end_price < settings.min_price_eur:
        return None
    if start_price <= 0:
        return None

    change_abs = end_price - start_price
    change_pct = (change_abs / start_price) * 100.0

    return RankedEntry(
        card_id=series.card_id,
        grade_id=series.grade_id,
        start_price_eur=start_price,
        end_price_eur=end_price,
        change_pct=change_pct,
        change_abs_eur=change_abs,
        observation_count=len(in_range),
    )


def rank_top100(
    all_series: list[CardSeries],
    period_start: datetime,
    period_end: datetime,
    settings: RankingSettings = RankingSettings(),
    sort_key: SortKey = "change_pct",
    limit: int = 100,
) -> list[RankedEntry]:
    entries = [
        e
        for e in (compute_entry(s, period_start, period_end, settings) for s in all_series)
        if e is not None
    ]

    key_fn = {
        "change_pct": lambda e: e.change_pct,
        "change_abs": lambda e: e.change_abs_eur,
        "volume": lambda e: e.observation_count,
    }[sort_key]

    entries.sort(key=key_fn, reverse=True)
    return entries[:limit]


TIME_RANGE_TO_TIMEDELTA = {
    "1D": timedelta(days=1),
    "7D": timedelta(days=7),
    "30D": timedelta(days=30),
    "6M": timedelta(days=182),
    "1Y": timedelta(days=365),
}


def period_for_range(time_range: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    end = now or datetime.now(timezone.utc)
    start = end - TIME_RANGE_TO_TIMEDELTA[time_range]
    return start, end
