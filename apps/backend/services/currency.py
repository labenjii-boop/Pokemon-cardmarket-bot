"""Currency normalization (Section 8): convert any observed price to EUR and DKK using the
ECB reference rate for the *sale/observation date*, never today's rate — a card that sold for
$100 a year ago is converted at the exchange rate from a year ago.

ECB rates are EUR-based: `eur_rate` is "units of `currency` per 1 EUR". So converting X units of
`currency` to EUR is `X / eur_rate`, and EUR to DKK is `eur_amount * dkk_rate`.
"""
from __future__ import annotations

import sqlite3


class MissingFxRateError(Exception):
    pass


def _lookup_rate(conn: sqlite3.Connection, date: str, currency: str) -> float:
    """Look up the ECB rate for `currency` on `date`, falling back to the most recent rate on
    or before that date (ECB doesn't publish on weekends/holidays — ~2-3 gap days is normal)."""
    row = conn.execute(
        """
        SELECT eur_rate FROM fx_rates
        WHERE currency = ? AND rate_date <= ?
        ORDER BY rate_date DESC
        LIMIT 1
        """,
        (currency, date),
    ).fetchone()
    if row is None:
        raise MissingFxRateError(f"no fx rate for {currency} on or before {date}")
    return row["eur_rate"]


def to_eur(conn: sqlite3.Connection, amount: float, currency: str, date: str) -> float:
    if currency == "EUR":
        return amount
    rate = _lookup_rate(conn, date, currency)
    return amount / rate


def to_dkk(conn: sqlite3.Connection, amount: float, currency: str, date: str) -> float:
    if currency == "DKK":
        return amount
    eur_amount = to_eur(conn, amount, currency, date)
    dkk_rate = _lookup_rate(conn, date, "DKK")
    return eur_amount * dkk_rate


def normalize(conn: sqlite3.Connection, amount: float, currency: str, date: str) -> tuple[float | None, float | None]:
    """Returns (eur_amount, dkk_amount). The two are looked up independently — a missing DKK
    rate must not blank out an EUR amount that was perfectly computable (and vice versa); the
    caller (services/ingest.py) writes whichever of the two came back, and a later backfill can
    fill in the other once its rate lands."""
    try:
        eur_amount = amount if currency == "EUR" else to_eur(conn, amount, currency, date)
    except MissingFxRateError:
        eur_amount = None

    try:
        if currency == "DKK":
            dkk_amount = amount
        elif eur_amount is not None:
            dkk_amount = eur_amount * _lookup_rate(conn, date, "DKK")
        else:
            dkk_amount = to_dkk(conn, amount, currency, date)
    except MissingFxRateError:
        dkk_amount = None

    return (eur_amount, dkk_amount)
