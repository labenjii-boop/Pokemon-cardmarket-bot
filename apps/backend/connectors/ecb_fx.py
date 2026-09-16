"""ECB reference-rate connector (DATA_SOURCES.md §2). Free, no key.

Uses the ECB's published daily/historical XML feeds directly (source of record per Section 8),
not the Frankfurter mirror — DATA_SOURCES.md documents Frankfurter as a fallback only, so the
`fx_rates.source` column can always say 'ecb' honestly. XML over the SDMX JSON API because the
feed is small, stable, and needs no query building for "give me every currency, every day."
"""
from __future__ import annotations

from typing import Iterable
from xml.etree import ElementTree

import httpx

from connectors._retry import get_with_retry
from connectors.base import FxConnector

HIST_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

# ECB's namespace prefixes in the feed XML.
_NS = {
    "gesmes": "http://www.gesmes.org/xml/2002-08-01",
    "ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref",
}


class EcbFxConnector(FxConnector):
    source_id = "ecb_fx"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=30.0)

    def close(self) -> None:
        self._client.close()

    def fetch_rates(self, start_date: str, end_date: str) -> Iterable[tuple[str, str, float]]:
        """The free daily/90-day feeds are all ECB publishes for free XML download; a full
        10-year backfill (Section 6) needs the SDMX historical series endpoint instead — see
        `fetch_full_history`. This method serves the common case (recent rates for the currently
        running app) from the lightweight feed.
        """
        resp = get_with_retry(self._client, HIST_URL)
        resp.raise_for_status()
        yield from _parse_feed(resp.text, start_date, end_date)

    def fetch_full_history(self, currencies: list[str]) -> Iterable[tuple[str, str, float]]:
        """10-year+ backfill via the ECB Statistical Data Warehouse SDMX 2.1 REST API — one
        series per currency, e.g. .../D.USD.EUR.SP00.A, going back to 1999. Kept separate from
        `fetch_rates` because it is a heavier, one-time-per-currency backfill job (Section 6),
        not something to call on every poll cycle.
        """
        for currency in currencies:
            url = (
                "https://sdw-wsrest.ecb.europa.eu/service/data/EXR/"
                f"D.{currency}.EUR.SP00.A?format=csvdata"
            )
            resp = get_with_retry(self._client, url, headers={"Accept": "text/csv"})
            if resp.status_code == 404:
                continue  # currency not published by ECB (e.g. currency retired before 1999)
            resp.raise_for_status()
            yield from _parse_sdmx_csv(resp.text, currency)


def _parse_feed(xml_text: str, start_date: str, end_date: str) -> Iterable[tuple[str, str, float]]:
    root = ElementTree.fromstring(xml_text)
    for day_node in root.iter(f"{{{_NS['ecb']}}}Cube"):
        date = day_node.attrib.get("time")
        if date is None:
            continue
        if not (start_date <= date <= end_date):
            continue
        for rate_node in day_node.findall(f"{{{_NS['ecb']}}}Cube"):
            currency = rate_node.attrib.get("currency")
            rate = rate_node.attrib.get("rate")
            if currency and rate:
                yield (date, currency, float(rate))


def _parse_sdmx_csv(csv_text: str, currency: str) -> Iterable[tuple[str, str, float]]:
    lines = csv_text.strip().splitlines()
    if not lines:
        return
    header = lines[0].split(",")
    try:
        date_idx = header.index("TIME_PERIOD")
        value_idx = header.index("OBS_VALUE")
    except ValueError:
        return
    for line in lines[1:]:
        fields = line.split(",")
        if len(fields) <= max(date_idx, value_idx):
            continue
        date, value = fields[date_idx], fields[value_idx]
        if date and value:
            try:
                yield (date, currency, float(value))
            except ValueError:
                continue
