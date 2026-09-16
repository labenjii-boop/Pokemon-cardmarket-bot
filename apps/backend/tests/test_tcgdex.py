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

    by_currency = {o.price_currency: [] for o in observations}
    for o in observations:
        by_currency[o.price_currency].append(o.price_amount)

    assert by_currency["EUR"] == [3687.39]  # cardmarket 'trend', not 'avg'/'low'
    assert sorted(by_currency["USD"]) == [1500.0, 2999.99]  # one per tcgplayer finish
    assert all(o.card_source_id == "en:ecard3-146" for o in observations)


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
