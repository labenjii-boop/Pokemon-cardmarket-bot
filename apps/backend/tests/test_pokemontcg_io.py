import httpx
import respx

from connectors.pokemontcg_io import BASE_URL, PokemonTcgIoConnector


@respx.mock
def test_fetch_sets_paginates_until_empty():
    respx.get(f"{BASE_URL}/sets").mock(
        side_effect=[
            httpx.Response(200, json={"data": [{"id": "base1", "name": "Base Set", "series": "Base", "total": 102, "releaseDate": "1999/01/09"}]}),
            httpx.Response(200, json={"data": []}),
        ]
    )
    connector = PokemonTcgIoConnector()
    sets = list(connector.fetch_sets())
    assert len(sets) == 1
    assert sets[0].source_set_id == "base1"
    assert sets[0].language == "en"
    assert sets[0].total_cards == 102


@respx.mock
def test_fetch_cards_maps_fields():
    respx.get(f"{BASE_URL}/cards").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "base1-4",
                            "name": "Charizard",
                            "number": "4",
                            "rarity": "Rare Holo",
                            "set": {"printedTotal": 102, "releaseDate": "1999/01/09"},
                            "images": {"small": "https://example/small.png", "large": "https://example/large.png"},
                            "tcgplayer": {"prices": {"holofoil": {"market": 250.0}}},
                        }
                    ]
                },
            ),
            httpx.Response(200, json={"data": []}),
        ]
    )
    connector = PokemonTcgIoConnector()
    cards = list(connector.fetch_cards("base1"))
    assert len(cards) == 1
    card = cards[0]
    assert card.source_card_id == "base1-4"
    assert card.name == "Charizard"
    assert card.variant == "holo"
    assert card.image_source_url == "https://example/large.png"


@respx.mock
def test_fetch_observations_emits_tcgplayer_and_cardmarket_points():
    respx.get(f"{BASE_URL}/cards").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "base1-4",
                            "tcgplayer": {"prices": {"holofoil": {"market": 250.0}}},
                            "cardmarket": {"prices": {"trendPrice": 210.5}},
                        }
                    ]
                },
            ),
            httpx.Response(200, json={"data": []}),
        ]
    )
    connector = PokemonTcgIoConnector()
    observations = list(connector.fetch_observations())
    assert len(observations) == 2
    currencies = {o.price_currency for o in observations}
    assert currencies == {"USD", "EUR"}
    assert all(o.is_transaction is False for o in observations)
