import pytest

from services.currency import MissingFxRateError, normalize, to_dkk, to_eur


def _seed_rates(conn):
    conn.execute("INSERT INTO fx_rates (rate_date, currency, eur_rate) VALUES ('2026-09-10', 'USD', 1.10)")
    conn.execute("INSERT INTO fx_rates (rate_date, currency, eur_rate) VALUES ('2026-09-10', 'DKK', 7.46)")
    conn.commit()


def test_to_eur_uses_historical_rate(db_conn):
    _seed_rates(db_conn)
    assert to_eur(db_conn, 110.0, "USD", "2026-09-10") == pytest.approx(100.0)


def test_to_eur_passthrough_for_eur(db_conn):
    assert to_eur(db_conn, 42.0, "EUR", "2026-09-10") == 42.0


def test_to_dkk_chains_through_eur(db_conn):
    _seed_rates(db_conn)
    dkk = to_dkk(db_conn, 110.0, "USD", "2026-09-10")
    assert dkk == pytest.approx(100.0 * 7.46)


def test_falls_back_to_most_recent_prior_rate(db_conn):
    _seed_rates(db_conn)
    # no rate published for 2026-09-12 (weekend) -> should use 2026-09-10's rate
    assert to_eur(db_conn, 110.0, "USD", "2026-09-12") == pytest.approx(100.0)


def test_missing_rate_raises(db_conn):
    with pytest.raises(MissingFxRateError):
        to_eur(db_conn, 100.0, "JPY", "2026-09-10")


def test_normalize_returns_both_currencies(db_conn):
    _seed_rates(db_conn)
    eur, dkk = normalize(db_conn, 110.0, "USD", "2026-09-10")
    assert eur == pytest.approx(100.0)
    assert dkk == pytest.approx(746.0)
