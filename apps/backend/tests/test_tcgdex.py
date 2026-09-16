import httpx
import respx

from connectors.tcgdex import BASE_URL, TcgdexConnector


@respx.mock
def test_fetch_sets_covers_all_languages():
    respx.get(f"{BASE_URL}/en/sets").mock(return_value=httpx.Response(200, json=[{"id": "base1", "name": "Base Set"}]))
    respx.get(f"{BASE_URL}/ja/sets").mock(return_value=httpx.Response(200, json=[{"id": "s1a", "name": "VMAXライジング"}]))
    respx.get(f"{BASE_URL}/zh-tw/sets").mock(return_value=httpx.Response(404))
    respx.get(f"{BASE_URL}/zh-cn/sets").mock(return_value=httpx.Response(200, json=[]))

    connector = TcgdexConnector()
    sets = list(connector.fetch_sets())

    languages = {s.language for s in sets}
    assert languages == {"en", "ja"}
    assert any(s.source_set_id == "en:base1" for s in sets)


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
