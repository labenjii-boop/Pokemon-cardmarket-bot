import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    tmpdir = tempfile.mkdtemp()
    import app.config as config

    new_settings = config.Settings(app_support_dir=Path(tmpdir))
    config.settings = new_settings

    # app.db and app.main each did `from app.config import settings` at import time, which
    # binds their own module-level name — reassigning app.config.settings doesn't reach either
    # of those once the modules are cached (e.g. by an earlier test in this same session), so
    # every module holding that binding needs to be repointed explicitly.
    import app.db as db
    import app.main as main

    db.settings = new_settings
    main.settings = new_settings
    with TestClient(main.app) as c:
        yield c, main


def test_review_queue_empty_by_default(client):
    c, _ = client
    r = c.get("/review-queue")
    assert r.status_code == 200
    assert r.json() == []


def test_review_queue_confirm_and_reject(client):
    c, main = client
    from app.db import get_connection

    with get_connection(main.settings.db_path) as conn:
        conn.execute(
            "INSERT INTO listing_matches (source_id, raw_title, confidence) VALUES ('pokemontcg_io', 'Test listing', 0.4)"
        )
        conn.commit()
        match_id = conn.execute("SELECT id FROM listing_matches").fetchone()["id"]

    r = c.get("/review-queue")
    assert len(r.json()) == 1

    r = c.post(f"/review-queue/{match_id}/confirm")
    assert r.status_code == 200
    assert r.json()["status"] == "confirmed"

    r = c.get("/review-queue")
    assert r.json() == []  # confirmed rows drop out of the pending queue
