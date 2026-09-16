from connectors.base import CatalogCard, CatalogSet
from services.ingest import upsert_card, upsert_set
from services.search import search_cards


def _seed(conn):
    set_id = upsert_set(conn, CatalogSet(source="tcgdex", source_set_id="en:base1", name="Base Set", language="en"))
    upsert_card(
        conn,
        CatalogCard(source="tcgdex", source_card_id="en:base1-4", set_source_set_id="en:base1", name="Charizard", number="4", language="en"),
        set_id,
    )
    upsert_card(
        conn,
        CatalogCard(source="tcgdex", source_card_id="en:base1-25", set_source_set_id="en:base1", name="Pikachu", number="25", language="en"),
        set_id,
    )


def test_empty_query_returns_recent_cards(db_conn):
    _seed(db_conn)
    results = search_cards(db_conn, "", limit=10)
    assert len(results) == 2


def test_query_matches_by_prefix(db_conn):
    _seed(db_conn)
    results = search_cards(db_conn, "char", limit=10)
    assert len(results) == 1
    assert results[0]["name"] == "Charizard"


def test_query_with_no_matches_returns_empty(db_conn):
    _seed(db_conn)
    results = search_cards(db_conn, "mewtwo", limit=10)
    assert results == []


def test_query_with_quote_character_does_not_raise(db_conn):
    _seed(db_conn)
    results = search_cards(db_conn, 'char"izard', limit=10)
    assert results == []  # no crash is the point; a literal stray quote just won't match anything
