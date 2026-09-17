import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from connectors.tcgdex import BASE_URL


@pytest.fixture
def client():
    tmpdir = tempfile.mkdtemp()
    import app.config as config

    new_settings = config.Settings(app_support_dir=Path(tmpdir))
    config.settings = new_settings

    import app.db as db
    import app.main as main

    db.settings = new_settings
    main.settings = new_settings
    with TestClient(main.app) as c:
        yield c, main


def _seed_card(main):
    from connectors.base import CatalogCard, CatalogSet
    from services.ingest import upsert_card, upsert_set

    with main.get_connection() as conn:
        set_id = upsert_set(conn, CatalogSet(source="tcgdex", source_set_id="en:base1", name="Base Set", language="en"))
        card_id = upsert_card(
            conn,
            CatalogCard(
                source="tcgdex", source_card_id="en:base1-4", set_source_set_id="en:base1",
                name="Charizard", number="4", language="en", image_source_url="https://assets.tcgdex.net/en/base/base1/4",
            ),
            set_id,
        )
        conn.commit()
    return card_id


def test_get_card_returns_404_for_unknown_card(client):
    c, _ = client
    r = c.get("/cards/does-not-exist")
    assert r.status_code == 404


def test_get_card_returns_real_card(client):
    c, main = client
    card_id = _seed_card(main)
    r = c.get(f"/cards/{card_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Charizard"
    assert body["set_name"] == "Base Set"
    assert body["image_source_url"] == "https://assets.tcgdex.net/en/base/base1/4"


def test_get_card_prices_rejects_bad_time_range(client):
    c, main = client
    card_id = _seed_card(main)
    r = c.get(f"/cards/{card_id}/prices?time_range=nonsense")
    assert r.status_code == 400


def test_get_card_prices_returns_series_within_range(client):
    c, main = client
    card_id = _seed_card(main)
    now = datetime.now(timezone.utc)

    with main.get_connection() as conn:
        for i, price in enumerate([100.0, 110.0, 120.0]):
            observed_at = (now - timedelta(days=i)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            conn.execute(
                "INSERT INTO price_snapshots (card_id, grade_id, source_id, observed_at, price_amount, price_currency, price_eur) "
                "VALUES (?, 'raw-nm', 'tcgdex', ?, ?, 'EUR', ?)",
                (card_id, observed_at, price, price),
            )
        conn.commit()

    r = c.get(f"/cards/{card_id}/prices?time_range=7D")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 3
    assert body[0]["observed_at"] < body[-1]["observed_at"]  # ordered oldest first


@respx.mock
def test_get_card_prices_backfills_history_for_a_thin_card(client):
    # A card with 0-1 real snapshots gets one live TCGdex call to seed real (backdated) history
    # from Cardmarket's avg1/avg7/avg30 — so a chart isn't flat/empty the very first time it's
    # opened, without waiting for the background rotation to revisit this card.
    c, main = client
    card_id = _seed_card(main)
    respx.get(f"{BASE_URL}/en/cards/base1-4").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "base1-4",
                "pricing": {"cardmarket": {"unit": "EUR", "trend": 100.0, "avg1": 90.0, "avg7": 80.0, "avg30": 70.0}},
            },
        )
    )

    r = c.get(f"/cards/{card_id}/prices?time_range=1Y")
    assert r.status_code == 200
    body = r.json()
    prices = {row["price_eur"] for row in body}
    assert {90.0, 80.0, 70.0}.issubset(prices)


@respx.mock
def test_get_card_prices_does_not_backfill_once_there_is_real_history(client):
    # No respx route is registered for the TCGdex card-detail endpoint here — if the backend
    # tried to call it anyway, this test would fail with a connection error, which is exactly
    # the point: a card with enough real history shouldn't trigger a live backfill call at all.
    c, main = client
    card_id = _seed_card(main)
    now = datetime.now(timezone.utc)
    with main.get_connection() as conn:
        for i, price in enumerate([100.0, 110.0]):
            observed_at = (now - timedelta(days=i)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            conn.execute(
                "INSERT INTO price_snapshots (card_id, grade_id, source_id, observed_at, price_amount, price_currency, price_eur) "
                "VALUES (?, 'raw-nm', 'tcgdex', ?, ?, 'EUR', ?)",
                (card_id, observed_at, price, price),
            )
        conn.commit()

    r = c.get(f"/cards/{card_id}/prices?time_range=1Y")
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_get_card_variants_returns_404_for_unknown_card(client):
    c, _ = client
    r = c.get("/cards/does-not-exist/variants")
    assert r.status_code == 404


@respx.mock
def test_get_card_variants_returns_live_breakdown(client):
    # TCGplayer reports in USD; this app displays EUR everywhere else, so the endpoint converts
    # rather than handing back a second currency the caller would have to convert itself.
    c, main = client
    card_id = _seed_card(main)
    with main.get_connection() as conn:
        conn.execute("INSERT INTO fx_rates (rate_date, currency, eur_rate) VALUES ('2000-01-01', 'USD', 1.10)")
        conn.commit()
    respx.get(f"{BASE_URL}/en/cards/base1-4").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "base1-4",
                "pricing": {
                    "cardmarket": {"unit": "EUR", "trend": 100.0, "trend-holo": 250.0},
                    "tcgplayer": {"unit": "USD", "holofoil": {"marketPrice": 330.0}},
                },
            },
        )
    )

    r = c.get(f"/cards/{card_id}/variants")
    assert r.status_code == 200
    body = r.json()
    assert body["cardmarket_eur"]["normal"] == 100.0
    assert body["cardmarket_eur"]["holo"] == 250.0
    assert body["tcgplayer_eur"] == {"holofoil": 300.0}  # 330 USD / 1.10 -> 300 EUR


@respx.mock
def test_get_card_variants_omits_tcgplayer_row_with_no_fx_rate_yet(client):
    # No fx_rates row is seeded here — a missing USD rate must not crash the endpoint or show a
    # wrong number, it should just leave that side out until the rate syncs.
    c, main = client
    card_id = _seed_card(main)
    respx.get(f"{BASE_URL}/en/cards/base1-4").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "base1-4",
                "pricing": {
                    "cardmarket": {"unit": "EUR", "trend": 100.0},
                    "tcgplayer": {"unit": "USD", "holofoil": {"marketPrice": 330.0}},
                },
            },
        )
    )

    r = c.get(f"/cards/{card_id}/variants")
    assert r.status_code == 200
    body = r.json()
    assert body["cardmarket_eur"]["normal"] == 100.0
    assert body["tcgplayer_eur"] == {}
