import httpx
import pytest
import respx

from connectors.tcgdex import BASE_URL, TcgdexConnector


@respx.mock
def test_fetch_sets_covers_all_languages():
    respx.get(f"{BASE_URL}/en/sets").mock(return_value=httpx.Response(200, json=[{"id": "base1", "name": "Base Set"}]))
    respx.get(f"{BASE_URL}/en/sets/base1").mock(
        return_value=httpx.Response(200, json={"id": "base1", "releaseDate": "1999-01-09", "serie": {"id": "base", "name": "Base"}})
    )
    respx.get(f"{BASE_URL}/ja/sets").mock(return_value=httpx.Response(200, json=[{"id": "s1a", "name": "VMAXライジング"}]))
    respx.get(f"{BASE_URL}/ja/sets/s1a").mock(
        return_value=httpx.Response(200, json={"id": "s1a", "releaseDate": "2020-06-12", "serie": {"id": "sm", "name": "Sun & Moon"}})
    )
    respx.get(f"{BASE_URL}/zh-tw/sets").mock(return_value=httpx.Response(404))
    respx.get(f"{BASE_URL}/zh-cn/sets").mock(return_value=httpx.Response(200, json=[]))

    connector = TcgdexConnector()
    sets = list(connector.fetch_sets())

    languages = {s.language for s in sets}
    assert languages == {"en", "ja"}
    base_set = next(s for s in sets if s.source_set_id == "en:base1")
    assert base_set.release_date == "1999-01-09"
    assert base_set.series == "base"


@respx.mock
def test_fetch_sets_still_yields_a_set_whose_detail_fetch_fails():
    # _fetch_set_detail returning None (a transient failure) shouldn't drop the set entirely —
    # just leave release_date/series unset for it until a later refresh picks it up.
    respx.get(f"{BASE_URL}/en/sets").mock(return_value=httpx.Response(200, json=[{"id": "base1", "name": "Base Set"}]))
    respx.get(f"{BASE_URL}/en/sets/base1").mock(return_value=httpx.Response(404))
    respx.get(f"{BASE_URL}/ja/sets").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{BASE_URL}/zh-tw/sets").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{BASE_URL}/zh-cn/sets").mock(return_value=httpx.Response(200, json=[]))

    connector = TcgdexConnector()
    sets = list(connector.fetch_sets())
    assert len(sets) == 1
    assert sets[0].release_date is None
    assert sets[0].series is None


@respx.mock
def test_zh_tw_404_is_not_an_error():
    respx.get(f"{BASE_URL}/en/sets").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{BASE_URL}/ja/sets").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{BASE_URL}/zh-tw/sets").mock(return_value=httpx.Response(404))
    respx.get(f"{BASE_URL}/zh-cn/sets").mock(return_value=httpx.Response(200, json=[]))

    connector = TcgdexConnector()
    sets = list(connector.fetch_sets())  # must not raise
    assert sets == []


@respx.mock
def test_fetch_cards_infers_variant():
    respx.get(f"{BASE_URL}/en/sets/base1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "base1",
                "cards": [
                    {"id": "base1-4", "localId": "4", "name": "Charizard", "rarity": "Rare Holo", "variants": {"holo": True}},
                ],
            },
        )
    )
    connector = TcgdexConnector()
    cards = list(connector.fetch_cards("en:base1"))
    assert len(cards) == 1
    assert cards[0].variant == "holo"
    assert cards[0].language == "en"
    assert cards[0].source_card_id == "en:base1-4"


@respx.mock
def test_fetch_cards_skips_pokemon_tcg_pocket_sets():
    # Real bug: TCGdex catalogs Pokémon TCG Pocket (a separate digital-only mobile game) through
    # the same endpoints as the physical TCG. Confirmed via a real GET /v2/en/sets/A1 ("Genetic
    # Apex") that Pocket sets carry serie.id == "tcgp" — those cards can never have
    # TCGplayer/Cardmarket pricing since they aren't physical objects, so don't import them.
    respx.get(f"{BASE_URL}/en/sets/A1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "A1", "name": "Genetic Apex", "serie": {"id": "tcgp", "name": "Pokémon TCG Pocket"},
                "cards": [{"id": "A1-001", "localId": "001", "name": "Bulbasaur"}],
            },
        )
    )
    connector = TcgdexConnector()
    cards = list(connector.fetch_cards("en:A1"))
    assert cards == []


@respx.mock
def test_fetch_cards_percent_encodes_a_plus_in_the_set_id():
    # Real bug from the first live run: the Japanese set id "SM1+" contains a literal '+',
    # which 404s against TCGdex's API unencoded (their server decodes an unencoded '+' in a
    # path as a space before route-matching). Must be sent as "%2B".
    route = respx.get(f"{BASE_URL}/ja/sets/SM1%2B").mock(
        return_value=httpx.Response(200, json={"id": "SM1+", "cards": [{"id": "SM1+-1", "localId": "1", "name": "Pikachu"}]})
    )
    connector = TcgdexConnector()
    cards = list(connector.fetch_cards("ja:SM1+"))
    assert route.called
    assert len(cards) == 1
    assert cards[0].name == "Pikachu"


# Trimmed down from a real GET /v2/en/cards/ecard3-146 response captured during the second live
# run — the full response has far more fields (attacks, weaknesses, etc.) that fetch_observations
# doesn't touch, so only the parts it reads are kept here.
REAL_CARD_DETAIL_RESPONSE = {
    "id": "ecard3-146",
    "name": "Charizard",
    "pricing": {
        "cardmarket": {
            "updated": "2026-09-16T13:19:49.524Z",
            "unit": "EUR",
            "avg": 1566.65,
            "low": 420,
            "trend": 3687.39,
        },
        "tcgplayer": {
            "unit": "USD",
            "updated": "2026-09-16T13:19:52.446Z",
            "holofoil": {"lowPrice": 3500, "midPrice": 3500, "highPrice": 3500, "marketPrice": 1500, "directLowPrice": None},
            "reverse-holofoil": {"lowPrice": 3500, "midPrice": 3500, "highPrice": 3500, "marketPrice": 2999.99, "directLowPrice": None},
        },
    },
}


@respx.mock
def test_fetch_observations_requires_card_ids():
    connector = TcgdexConnector()
    with pytest.raises(ValueError):
        list(connector.fetch_observations())


@respx.mock
def test_fetch_observations_parses_real_pricing_shape():
    respx.get(f"{BASE_URL}/en/cards/ecard3-146").mock(return_value=httpx.Response(200, json=REAL_CARD_DETAIL_RESPONSE))
    connector = TcgdexConnector()
    observations = list(connector.fetch_observations(card_ids=["en:ecard3-146"]))

    assert len(observations) == 1
    assert observations[0].price_currency == "EUR"
    assert observations[0].price_amount == 3687.39  # cardmarket 'trend', not 'avg'/'low'
    assert observations[0].card_source_id == "en:ecard3-146"


@respx.mock
def test_fetch_observations_emits_only_one_point_even_with_multiple_tcgplayer_finishes():
    # Real bug from a live chart that looked like noise: REAL_CARD_DETAIL_RESPONSE's tcgplayer
    # block has two finishes (holofoil, reverse-holofoil) with different marketPrice values —
    # both used to become separate, conflicting "market price" observations for the same card
    # at the same instant.
    respx.get(f"{BASE_URL}/en/cards/ecard3-146").mock(return_value=httpx.Response(200, json=REAL_CARD_DETAIL_RESPONSE))
    connector = TcgdexConnector()
    observations = list(connector.fetch_observations(card_ids=["en:ecard3-146"]))
    assert len(observations) == 1


@respx.mock
def test_fetch_observations_skips_a_404_card_without_raising():
    respx.get(f"{BASE_URL}/en/cards/gone-1").mock(return_value=httpx.Response(404))
    respx.get(f"{BASE_URL}/en/cards/ecard3-146").mock(return_value=httpx.Response(200, json=REAL_CARD_DETAIL_RESPONSE))
    connector = TcgdexConnector()
    observations = list(connector.fetch_observations(card_ids=["en:gone-1", "en:ecard3-146"]))
    assert all(o.card_source_id == "en:ecard3-146" for o in observations)


@respx.mock
def test_fetch_observations_skips_a_persistently_failing_card_without_raising():
    # One card in a batch hitting a persistent 500 (after get_with_retry exhausts its attempts)
    # must not lose the other cards in the same batch — same bug class as the pokemontcg.io
    # pagination fix.
    respx.get(f"{BASE_URL}/en/cards/bad-1").mock(return_value=httpx.Response(500))
    respx.get(f"{BASE_URL}/en/cards/ecard3-146").mock(return_value=httpx.Response(200, json=REAL_CARD_DETAIL_RESPONSE))

    connector = TcgdexConnector()
    observations = list(connector.fetch_observations(card_ids=["en:bad-1", "en:ecard3-146"]))
    assert len(observations) > 0
    assert all(o.card_source_id == "en:ecard3-146" for o in observations)


@respx.mock
def test_fetch_observations_handles_card_with_no_marketplace_listing():
    respx.get(f"{BASE_URL}/en/cards/obscure-1").mock(
        return_value=httpx.Response(200, json={"id": "obscure-1", "pricing": {"cardmarket": None, "tcgplayer": None}})
    )
    connector = TcgdexConnector()
    observations = list(connector.fetch_observations(card_ids=["en:obscure-1"]))
    assert observations == []


# The full real cardmarket block from the same live GET /v2/en/cards/ecard3-146 response as
# REAL_CARD_DETAIL_RESPONSE above (trimmed there to just what fetch_observations reads) — this
# one keeps the '-holo' suffixed fields fetch_card_variant_pricing is actually for.
REAL_CARD_DETAIL_WITH_VARIANTS = {
    "id": "ecard3-146",
    "name": "Charizard",
    "pricing": {
        "cardmarket": {
            "unit": "EUR",
            "avg": 1566.65, "low": 420, "trend": 3687.39,
            "avg1": 2599.95, "avg7": 2705.71, "avg30": 3398,
            "avg-holo": 3544.5, "low-holo": 420, "trend-holo": 1973.13,
            "avg1-holo": 3950, "avg7-holo": 2059.14, "avg30-holo": 1168.34,
        },
        "tcgplayer": {
            "unit": "USD",
            "holofoil": {"marketPrice": 1500},
            "reverse-holofoil": {"marketPrice": 2999.99},
        },
    },
}


@respx.mock
def test_fetch_card_variant_pricing_parses_real_shape():
    respx.get(f"{BASE_URL}/en/cards/ecard3-146").mock(return_value=httpx.Response(200, json=REAL_CARD_DETAIL_WITH_VARIANTS))
    connector = TcgdexConnector()
    result = connector.fetch_card_variant_pricing("en:ecard3-146")

    assert result["cardmarket_eur"]["normal"] == 3687.39  # 'trend', preferred over avg/avg30/etc
    assert result["cardmarket_eur"]["holo"] == 1973.13  # 'trend-holo'
    assert result["tcgplayer_usd"] == {"holofoil": 1500.0, "reverse-holofoil": 2999.99}


@respx.mock
def test_fetch_card_variant_pricing_handles_missing_pricing():
    respx.get(f"{BASE_URL}/en/cards/obscure-1").mock(return_value=httpx.Response(200, json={"id": "obscure-1"}))
    connector = TcgdexConnector()
    result = connector.fetch_card_variant_pricing("en:obscure-1")
    assert result == {"cardmarket_eur": {}, "tcgplayer_usd": {}}


@respx.mock
def test_fetch_price_history_backfill_uses_cardmarket_rolling_averages():
    # A brand-new card only ever polled once looks like a flat chart until the rotation revisits
    # it enough times over real elapsed hours/days. Cardmarket's avg1/avg7/avg30 rolling averages
    # (present in the same response fetch_observations already reads) give real, backdated shape
    # immediately instead of making the user wait — plus the current 'trend' price at "now", so a
    # short (e.g. 1-day) range isn't left empty.
    respx.get(f"{BASE_URL}/en/cards/ecard3-146").mock(return_value=httpx.Response(200, json=REAL_CARD_DETAIL_WITH_VARIANTS))
    connector = TcgdexConnector()
    observations = connector.fetch_price_history_backfill("en:ecard3-146")

    assert len(observations) == 4
    by_amount = {o.price_amount: o for o in observations}
    assert 3687.39 in by_amount  # trend, "now"
    assert 3398.0 in by_amount  # avg30
    assert 2705.71 in by_amount  # avg7
    assert 2599.95 in by_amount  # avg1
    assert all(o.card_source_id == "en:ecard3-146" and o.price_currency == "EUR" for o in observations)
    # Backdated, not all stamped "now" — otherwise they'd just be four more copies of today's price.
    timestamps = sorted(o.observed_at for o in observations)
    assert timestamps[0] < timestamps[-1]


@respx.mock
def test_fetch_price_history_backfill_handles_missing_pricing():
    respx.get(f"{BASE_URL}/en/cards/obscure-1").mock(return_value=httpx.Response(200, json={"id": "obscure-1"}))
    connector = TcgdexConnector()
    observations = connector.fetch_price_history_backfill("en:obscure-1")
    assert observations == []


@respx.mock
def test_fetch_observations_backfills_only_the_requested_ids():
    # backfill_ids lets services/jobs.py seed Cardmarket's rolling averages only for cards with
    # zero stored history yet — everything else in the same batch just gets the regular single
    # "trend" point, same as before backfill_ids existed.
    respx.get(f"{BASE_URL}/en/cards/ecard3-146").mock(return_value=httpx.Response(200, json=REAL_CARD_DETAIL_WITH_VARIANTS))
    connector = TcgdexConnector()
    observations = list(connector.fetch_observations(card_ids=["en:ecard3-146"], backfill_ids={"en:ecard3-146"}))
    assert len(observations) == 4  # 1 "now" trend point + 3 backfilled rolling averages


@respx.mock
def test_fetch_observations_does_not_backfill_ids_outside_backfill_ids():
    respx.get(f"{BASE_URL}/en/cards/ecard3-146").mock(return_value=httpx.Response(200, json=REAL_CARD_DETAIL_WITH_VARIANTS))
    connector = TcgdexConnector()
    observations = list(connector.fetch_observations(card_ids=["en:ecard3-146"], backfill_ids=set()))
    assert len(observations) == 1
