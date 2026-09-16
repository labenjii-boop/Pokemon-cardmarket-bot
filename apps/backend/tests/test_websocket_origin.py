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

    import app.db as db
    import app.main as main

    db.settings = new_settings
    main.settings = new_settings
    with TestClient(main.app) as c:
        yield c


def test_websocket_accepts_allowed_origin(client):
    with client.websocket_connect("/ws", headers={"origin": "http://localhost:1420"}) as ws:
        ws.close()


def test_websocket_accepts_missing_origin(client):
    # non-browser clients (our own scripts, tests) typically send no Origin header at all
    with client.websocket_connect("/ws") as ws:
        ws.close()


def test_websocket_rejects_disallowed_origin(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"origin": "https://evil.example"}):
            pass
