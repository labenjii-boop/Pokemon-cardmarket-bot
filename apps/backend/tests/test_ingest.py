import pytest

from connectors.base import CatalogCard, CatalogSet, PriceObservation
from services.ingest import ingest_catalog_sets, ingest_price_observations, upsert_card, upsert_set


def _sample_set() -> CatalogSet:
    return CatalogSet(source="pokemontcg_io", source_set_id="base1", name="Base Set", language="en")


def _sample_card() -> CatalogCard:
    return CatalogCard(
        source="pokemontcg_io",
        source_card_id="base1-4",
        set_source_set_id="base1",
        name="Charizard",
        number="4",
        language="en",
    )


def test_upsert_set_is_idempotent(db_conn):
    s = _sample_set()
    id1 = upsert_set(db_conn, s)
    id2 = upsert_set(db_conn, s)
    assert id1 == id2
    count = db_conn.execute("SELECT COUNT(*) AS c FROM sets").fetchone()["c"]
    assert count == 1


def test_upsert_card_links_to_set_and_indexes_fts(db_conn):
    set_id = upsert_set(db_conn, _sample_set())
    card_id = upsert_card(db_conn, _sample_card(), set_id)

    row = db_conn.execute("SELECT set_id, name FROM cards WHERE id = ?", (card_id,)).fetchone()
    assert row["set_id"] == set_id
    assert row["name"] == "Charizard"

    fts_row = db_conn.execute("SELECT name FROM cards_fts WHERE card_id = ?", (card_id,)).fetchone()
    assert fts_row["name"] == "Charizard"


def test_ingest_catalog_sets_returns_id_map(db_conn):
    result = ingest_catalog_sets(db_conn, [_sample_set()])
    assert "pokemontcg_io:base1" in result


def test_ingest_price_observations_skips_cards_not_in_catalog(db_conn):
    obs = [
        PriceObservation(
            source="pokemontcg_io", card_source_id="does-not-exist",
            observed_at="2026-09-10T00:00:00.000000Z", price_amount=10.0, price_currency="USD",
        )
    ]
    written = ingest_price_observations(db_conn, "pokemontcg_io", obs)
    assert written == 0


def test_ingest_price_observations_writes_snapshot_without_fx_rate(db_conn):
    set_id = upsert_set(db_conn, _sample_set())
    upsert_card(db_conn, _sample_card(), set_id)

    obs = [
        PriceObservation(
            source="pokemontcg_io", card_source_id="base1-4",
            observed_at="2026-09-10T00:00:00.000000Z", price_amount=250.0, price_currency="USD",
        )
    ]
    written = ingest_price_observations(db_conn, "pokemontcg_io", obs)
    assert written == 1

    row = db_conn.execute("SELECT price_amount, price_eur FROM price_snapshots").fetchone()
    assert row["price_amount"] == 250.0
    assert row["price_eur"] is None  # no fx_rates row seeded -> normalization deferred, not a crash


def test_ingest_price_observations_normalizes_when_fx_rate_present(db_conn):
    set_id = upsert_set(db_conn, _sample_set())
    upsert_card(db_conn, _sample_card(), set_id)
    db_conn.execute("INSERT INTO fx_rates (rate_date, currency, eur_rate) VALUES ('2026-09-10', 'USD', 1.10)")

    obs = [
        PriceObservation(
            source="pokemontcg_io", card_source_id="base1-4",
            observed_at="2026-09-10T00:00:00.000000Z", price_amount=110.0, price_currency="USD",
        )
    ]
    ingest_price_observations(db_conn, "pokemontcg_io", obs)
    row = db_conn.execute("SELECT price_eur FROM price_snapshots").fetchone()
    assert row["price_eur"] == pytest.approx(100.0)
