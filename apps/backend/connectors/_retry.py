"""Shared HTTP retry/backoff for connectors (Section 5c rule 5: "Respect all rate limits. Use
backoff, retries, and caching."). Only retries status codes that are plausibly transient —
retrying a 404 or 400 just burns calls against a free-tier daily cap for no reason, since
retrying won't change whether the resource exists.
"""
from __future__ import annotations

import time

import httpx

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def get_with_retry(
    client: httpx.Client,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    sleep=None,
) -> httpx.Response:
    # `sleep` defaults to None rather than `time.sleep` directly: a default argument value is
    # bound once, at function-definition time, so `sleep=time.sleep` would permanently capture
    # today's `time.sleep` and never see a test's `monkeypatch.setattr(time, "sleep", ...)`
    # (which reassigns the module attribute, not the already-bound default). Looking it up here,
    # inside the call, reads whatever `time.sleep` currently is.
    if sleep is None:
        sleep = time.sleep

    response: httpx.Response | None = None
    for attempt in range(max_attempts):
        response = client.get(url, params=params, headers=headers)
        if response.status_code not in RETRYABLE_STATUS:
            return response
        if attempt < max_attempts - 1:
            sleep(base_delay * (2**attempt))
    assert response is not None
    response.raise_for_status()
    return response  # pragma: no cover — raise_for_status() above always raises when we get here
