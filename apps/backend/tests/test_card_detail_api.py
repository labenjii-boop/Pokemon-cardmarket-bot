import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


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
