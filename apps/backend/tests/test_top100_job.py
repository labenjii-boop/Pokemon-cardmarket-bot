from datetime import datetime, timedelta, timezone

from connectors.base import CatalogCard, CatalogSet
from services.ingest import upsert_card, upsert_set
from services.top100_job import compute_and_store_top100, load_card_series, load_ranking_settings


def _seed_card(conn, card_number="4") -> str:
    set_id = upsert_set(conn, CatalogSet(source="pokemontcg_io", source_set_id="base1", name="Base Set", language="en"))
    return upsert_card(
        conn,
        CatalogCard(
            source="pokemontcg_io", source_card_id=f"base1-{card_number}", set_source_set_id="base1",
            name="Charizard", number=card_number, language="en",
        ),
        set_id,
    )


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def test_load_card_series_groups_by_card_and_grade(db_conn):
    card_id = _seed_card(db_conn)
    now = datetime.now(timezone.utc)
    db_conn.execute(
        "INSERT INTO price_snapshots (card_id, grade_id, source_id, observed_at, price_amount, price_currency, price_eur) VALUES (?, 'raw-nm', 'pokemontcg_io', ?, 100, 'EUR', 100)",
        (card_id, _iso(now - timedelta(days=1))),
    )
    db_conn.execute(
        "INSERT INTO price_snapshots (card_id, grade_id, source_id, observed_at, price_amount, price_currency, price_eur) VALUES (?, 'raw-nm', 'pokemontcg_io', ?, 120, 'EUR', 120)",
        (card_id, _iso(now)),
    )
    db_conn.commit()

    series = load_card_series(db_conn, now - timedelta(days=7), now + timedelta(hours=1))
    assert len(series) == 1
    assert series[0].card_id == card_id
    assert series[0].grade_id == "raw-nm"
    assert len(series[0].observations) == 2


def test_load_card_series_excludes_null_price_eur(db_conn):
    card_id = _seed_card(db_conn)
    now = datetime.now(timezone.utc)
    db_conn.execute(
        "INSERT INTO price_snapshots (card_id, grade_id, source_id, observed_at, price_amount, price_currency, price_eur) VALUES (?, 'raw-nm', 'pokemontcg_io', ?, 100, 'USD', NULL)",
        (card_id, _iso(now)),
    )
    db_conn.commit()
    series = load_card_series(db_conn, now - timedelta(days=1), now + timedelta(hours=1))
    assert series == []


def test_load_ranking_settings_defaults_when_unset(db_conn):
    settings = load_ranking_settings(db_conn)
    assert settings.min_observations == 3


def test_load_ranking_settings_reads_overrides(db_conn):
    db_conn.execute("INSERT INTO settings (key, value) VALUES ('top100_min_observations', '5')")
    db_conn.execute("INSERT INTO settings (key, value) VALUES ('top100_min_price_eur', '10.0')")
    db_conn.commit()
    settings = load_ranking_settings(db_conn)
    assert settings.min_observations == 5
    assert settings.min_price_eur == 10.0


def test_compute_and_store_top100_writes_rows_for_every_range_and_sort(db_conn):
    card_id = _seed_card(db_conn)
    now = datetime.now(timezone.utc)
    # 3 observations spread over the last 6 days -> qualifies for 7D/30D/6M/1Y (min_observations=3 default)
    for i, price in enumerate([100, 100, 150]):
        db_conn.execute(
            "INSERT INTO price_snapshots (card_id, grade_id, source_id, observed_at, price_amount, price_currency, price_eur) VALUES (?, 'raw-nm', 'pokemontcg_io', ?, ?, 'EUR', ?)",
            (card_id, _iso(now - timedelta(days=6 - i * 3)), price, price),
        )
    db_conn.commit()

    result = compute_and_store_top100(db_conn, now=now)
    assert result["rows_written"] > 0

    row = db_conn.execute(
        "SELECT rank, change_pct FROM top100_snapshots WHERE time_range = '7D' AND sort_key = 'change_pct'"
    ).fetchone()
    assert row is not None
    assert row["rank"] == 1
    assert row["change_pct"] == 50.0


def test_compute_and_store_top100_latest_computed_at_supersedes_old_batch(db_conn):
    card_id = _seed_card(db_conn)
    now = datetime.now(timezone.utc)
    for i in range(3):
        db_conn.execute(
            "INSERT INTO price_snapshots (card_id, grade_id, source_id, observed_at, price_amount, price_currency, price_eur) VALUES (?, 'raw-nm', 'pokemontcg_io', ?, 100, 'EUR', 100)",
            (card_id, _iso(now - timedelta(days=i))),
        )
    db_conn.commit()

    first = compute_and_store_top100(db_conn, now=now)
    second = compute_and_store_top100(db_conn, now=now)
    assert first["computed_at"] != second["computed_at"]

    count = db_conn.execute(
        "SELECT COUNT(*) AS c FROM top100_snapshots WHERE time_range='7D' AND sort_key='change_pct'"
    ).fetchone()["c"]
    assert count == 2  # both batches kept, API layer picks the latest computed_at
