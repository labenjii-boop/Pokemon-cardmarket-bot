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
def test_fetch_observations_emits_only_the_cardmarket_trend_point():
    # Real bug: tcgplayer.prices breaks price down per print variant (holofoil, reverse-holofoil,
    # etc — separate physical products). Looping over all of them used to emit multiple
    # conflicting "market price" points for the same card_id at the same instant. Only
    # Cardmarket's single trendPrice is unambiguous.
    respx.get(f"{BASE_URL}/cards").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "base1-4",
                            "tcgplayer": {"prices": {"holofoil": {"market": 250.0}, "reverseHolofoil": {"market": 300.0}}},
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
    assert len(observations) == 1
    assert observations[0].price_currency == "EUR"
    assert observations[0].price_amount == 210.5
    assert observations[0].is_transaction is False
