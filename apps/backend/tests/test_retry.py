import httpx
import pytest
import respx

from connectors._retry import get_with_retry

URL = "https://example.test/thing"


@respx.mock
def test_returns_immediately_on_success():
    respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    client = httpx.Client()
    resp = get_with_retry(client, URL, sleep=lambda _: None)
    assert resp.status_code == 200


@respx.mock
def test_retries_on_transient_5xx_then_succeeds():
    respx.get(URL).mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json={"ok": True})]
    )
    client = httpx.Client()
    resp = get_with_retry(client, URL, sleep=lambda _: None)
    assert resp.status_code == 200


@respx.mock
def test_does_not_retry_a_404():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(404)

    respx.get(URL).mock(side_effect=handler)
    client = httpx.Client()
    resp = get_with_retry(client, URL, sleep=lambda _: None)
    assert resp.status_code == 404
    assert calls["n"] == 1  # not retried — a 404 won't change on retry


@respx.mock
def test_raises_after_exhausting_retries_on_persistent_5xx():
    respx.get(URL).mock(return_value=httpx.Response(503))
    client = httpx.Client()
    with pytest.raises(httpx.HTTPStatusError):
        get_with_retry(client, URL, max_attempts=3, sleep=lambda _: None)


@respx.mock
def test_backoff_delay_grows_between_attempts():
    respx.get(URL).mock(
        side_effect=[httpx.Response(500), httpx.Response(500), httpx.Response(200)]
    )
    delays = []
    client = httpx.Client()
    get_with_retry(client, URL, base_delay=1.0, sleep=delays.append)
    assert delays == [1.0, 2.0]
