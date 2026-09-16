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
