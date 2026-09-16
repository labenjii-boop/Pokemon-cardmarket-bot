from datetime import datetime, timedelta, timezone

from services.top100 import CardSeries, Observation, RankingSettings, compute_entry, rank_top100

START = datetime(2026, 9, 1, tzinfo=timezone.utc)
END = datetime(2026, 9, 8, tzinfo=timezone.utc)  # 7-day period


def _series(card_id: str, prices: list[float], grade_id: str = "raw-nm") -> CardSeries:
    step = (END - START) / max(len(prices) - 1, 1)
    obs = tuple(
        Observation(observed_at=START + step * i, price_eur=p) for i, p in enumerate(prices)
    )
    return CardSeries(card_id=card_id, grade_id=grade_id, observations=obs)


def test_disqualifies_below_min_observations():
    series = _series("card-a", [100.0, 150.0])  # only 2 points, default min is 3
    assert compute_entry(series, START, END) is None


def test_computes_pct_and_abs_change():
    series = _series("card-a", [100.0, 100.0, 200.0, 200.0])
    entry = compute_entry(series, START, END, RankingSettings(min_observations=3, edge_fraction=0.1))
    assert entry is not None
    assert entry.start_price_eur == 100.0
    assert entry.end_price_eur == 200.0
    assert entry.change_pct == 100.0
    assert entry.change_abs_eur == 100.0


def test_median_smooths_a_single_outlier_at_the_edge():
    # Last two observations are both near the end window; one is a wild outlier.
    obs = (
        Observation(START, 100.0),
        Observation(START + timedelta(days=2), 100.0),
        Observation(START + timedelta(days=3), 100.0),
        Observation(END - timedelta(hours=12), 100.0),
        Observation(END, 9999.0),  # outlier sale
    )
    series = CardSeries(card_id="card-a", grade_id="raw-nm", observations=obs)
    entry = compute_entry(series, START, END, RankingSettings(min_observations=3, edge_fraction=0.2))
    assert entry is not None
    # median of the end window (last ~20% = last ~1.4 days: the 100.0 and the 9999.0 outlier)
    # should sit well below the outlier itself.
    assert entry.end_price_eur < 9999.0


def test_min_price_filters_low_value_cards():
    series = _series("card-a", [1.0, 1.0, 2.0, 2.0])
    entry = compute_entry(series, START, END, RankingSettings(min_observations=3, min_price_eur=5.0))
    assert entry is None


def test_rank_top100_sorts_by_pct_change_desc():
    series_list = [
        _series("small-gain", [100.0, 100.0, 110.0, 110.0]),
        _series("big-gain", [100.0, 100.0, 300.0, 300.0]),
    ]
    ranked = rank_top100(series_list, START, END, sort_key="change_pct")
    assert [e.card_id for e in ranked] == ["big-gain", "small-gain"]


def test_rank_top100_sorts_by_volume():
    series_list = [
        _series("few-obs", [100.0, 100.0, 110.0]),
        _series("many-obs", [100.0, 105.0, 108.0, 110.0, 112.0, 115.0]),
    ]
    ranked = rank_top100(series_list, START, END, sort_key="volume")
    assert ranked[0].card_id == "many-obs"


def test_rank_top100_respects_limit():
    series_list = [_series(f"card-{i}", [100.0, 100.0, 110.0]) for i in range(5)]
    ranked = rank_top100(series_list, START, END, limit=2)
    assert len(ranked) == 2
