"""Tests the /settings <-> Keychain wiring in app/main.py. Uses a small in-memory fake in place
of app.secrets' get/set/delete (this sandbox has no real OS keyring — see test_secrets.py, which
covers the no-backend fallback itself) so these tests verify main.py's plumbing: that GET never
echoes a raw secret and that PUT routes secret keys away from the plaintext settings file.
"""
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    import app.config as config

    new_settings = config.Settings(app_support_dir=Path(tmpdir))
    config.settings = new_settings

    import app.db as db
    import app.main as main

    db.settings = new_settings
    main.settings = new_settings

    fake_store: dict[str, str] = {}
    monkeypatch.setattr(main, "get_secret", lambda key: fake_store.get(key))
    monkeypatch.setattr(main, "set_secret", lambda key, value: fake_store.__setitem__(key, value) or True)
    monkeypatch.setattr(main, "delete_secret", lambda key: fake_store.pop(key, None))

    with TestClient(main.app) as c:
        yield c, fake_store


def test_settings_get_reports_unset_key_by_default(client):
    c, _ = client
    r = c.get("/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["pokemontcg_io_api_key_set"] is False
    assert "pokemontcg_io_api_key" not in body


def test_put_settings_stores_key_via_keychain_not_plaintext_file(client):
    c, fake_store = client
    import app.main as main

    r = c.put("/settings", json={"pokemontcg_io_api_key": "super-secret-123"})
    assert r.status_code == 200
    body = r.json()

    # never echoed back
    assert "pokemontcg_io_api_key" not in body
    assert body["pokemontcg_io_api_key_set"] is True

    # went through app.secrets, not the plaintext local settings file
    assert fake_store["pokemontcg_io_api_key"] == "super-secret-123"
    assert "pokemontcg_io_api_key" not in main.settings.load_local_settings()


def test_put_settings_empty_value_deletes_key(client):
    c, fake_store = client
    c.put("/settings", json={"pokemontcg_io_api_key": "abc"})
    assert fake_store.get("pokemontcg_io_api_key") == "abc"

    c.put("/settings", json={"pokemontcg_io_api_key": ""})
    assert "pokemontcg_io_api_key" not in fake_store

    body = c.get("/settings").json()
    assert body["pokemontcg_io_api_key_set"] is False


def test_non_secret_settings_still_round_trip_through_the_plaintext_file(client):
    c, _ = client
    c.put("/settings", json={"scheduler_enabled": False, "top100_min_observations": 5})
    body = c.get("/settings").json()
    assert body["scheduler_enabled"] is False
    assert body["top100_min_observations"] == 5
