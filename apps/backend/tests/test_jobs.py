import httpx
import respx

from connectors.ecb_fx import HIST_URL
from connectors.pokemontcg_io import BASE_URL as PK_BASE_URL
from connectors.tcgdex import BASE_URL as TCGDEX_BASE_URL
from services import jobs

SAMPLE_FX_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-09-15">
      <Cube currency="USD" rate="1.0850"/>
      <Cube currency="DKK" rate="7.4600"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""


@respx.mock
def test_sync_fx_rates_writes_rows_and_records_run(db_conn):
    respx.get(HIST_URL).mock(return_value=httpx.Response(200, text=SAMPLE_FX_FEED))

    result = jobs.sync_fx_rates(db_conn, days=30)
    assert result["written"] == 2

    count = db_conn.execute("SELECT COUNT(*) AS c FROM fx_rates").fetchone()["c"]
    assert count == 2

    run = db_conn.execute("SELECT status FROM connector_runs WHERE source_id = 'ecb_fx'").fetchone()
    assert run["status"] == "ok"


@respx.mock
def test_sync_fx_rates_records_error_run_on_failure(db_conn):
    respx.get(HIST_URL).mock(return_value=httpx.Response(500))

    result = jobs.sync_fx_rates(db_conn, days=30)
    assert "error" in result

    run = db_conn.execute("SELECT status, error_message FROM connector_runs WHERE source_id = 'ecb_fx'").fetchone()
    assert run["status"] == "error"
    assert run["error_message"]


@respx.mock
def test_poll_price_snapshots_ingests_and_records_run(db_conn):
    from connectors.base import CatalogCard, CatalogSet
    from services.ingest import upsert_card, upsert_set

    set_id = upsert_set(db_conn, CatalogSet(source="pokemontcg_io", source_set_id="base1", name="Base Set", language="en"))
    upsert_card(
        db_conn,
        CatalogCard(source="pokemontcg_io", source_card_id="base1-4", set_source_set_id="base1", name="Charizard", number="4", language="en"),
        set_id,
    )
    db_conn.commit()

    respx.get(f"{PK_BASE_URL}/cards").mock(
        side_effect=[
            httpx.Response(200, json={"data": [{"id": "base1-4", "tcgplayer": {"prices": {"holofoil": {"market": 250.0}}}}]}),
            httpx.Response(200, json={"data": []}),
        ]
    )

    result = jobs.poll_price_snapshots(db_conn)
    assert result["written"] == 1

    run = db_conn.execute("SELECT status, records_written FROM connector_runs WHERE source_id = 'pokemontcg_io'").fetchone()
    assert run["status"] == "ok"
    assert run["records_written"] == 1


@respx.mock
def test_poll_price_snapshots_keeps_earlier_pages_after_a_later_page_fails(db_conn):
    # Real regression: pokemontcg.io failed on page 2 of a live run. list(fetch_observations())
    # would have discarded page 1's already-successful observations along with it.
    from connectors.base import CatalogCard, CatalogSet
    from services.ingest import upsert_card, upsert_set

    set_id = upsert_set(db_conn, CatalogSet(source="pokemontcg_io", source_set_id="base1", name="Base Set", language="en"))
    upsert_card(
        db_conn,
        CatalogCard(source="pokemontcg_io", source_card_id="base1-4", set_source_set_id="base1", name="Charizard", number="4", language="en"),
        set_id,
    )
    db_conn.commit()

    respx.get(f"{PK_BASE_URL}/cards").mock(
        side_effect=[
            httpx.Response(200, json={"data": [{"id": "base1-4", "tcgplayer": {"prices": {"holofoil": {"market": 250.0}}}}]}),
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(500),  # get_with_retry exhausts its attempts and raises
        ]
    )

    result = jobs.poll_price_snapshots(db_conn)
    assert result["written"] == 1  # page 1's observation, not lost
    assert "error" in result

    run = db_conn.execute("SELECT status, records_written FROM connector_runs WHERE source_id = 'pokemontcg_io'").fetchone()
    assert run["status"] == "error"  # honest: the run didn't fully complete
    assert run["records_written"] == 1  # but what it did get is still there


@respx.mock
def test_import_catalog_writes_cards_from_both_sources(db_conn):
    respx.get(f"{PK_BASE_URL}/sets").mock(
        side_effect=[
            httpx.Response(200, json={"data": [{"id": "base1", "name": "Base Set"}]}),
            httpx.Response(200, json={"data": []}),
        ]
    )
    respx.get(f"{PK_BASE_URL}/cards").mock(
        side_effect=[
            httpx.Response(200, json={"data": [{"id": "base1-4", "name": "Charizard", "number": "4"}]}),
            httpx.Response(200, json={"data": []}),
        ]
    )
    respx.get(f"{TCGDEX_BASE_URL}/en/sets").mock(return_value=httpx.Response(200, json=[{"id": "base1", "name": "Base Set"}]))
    respx.get(f"{TCGDEX_BASE_URL}/ja/sets").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{TCGDEX_BASE_URL}/zh-tw/sets").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{TCGDEX_BASE_URL}/zh-cn/sets").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{TCGDEX_BASE_URL}/en/sets/base1").mock(
        return_value=httpx.Response(200, json={"id": "base1", "cards": [{"id": "base1-4", "localId": "4", "name": "Charizard"}]})
    )

    result = jobs.import_catalog(db_conn)
    assert result["pokemontcg_io"] == 1
    assert result["tcgdex"] == 1
    assert result["errors"] == []

    count = db_conn.execute("SELECT COUNT(*) AS c FROM cards").fetchone()["c"]
    assert count == 2  # one from each source, distinct internal ids


@respx.mock
def test_import_catalog_survives_one_set_failing(db_conn):
    # Real regression from the first live run: a persistent 500 on one set's /cards call used
    # to abort the entire pokemontcg.io import, losing every set that had already succeeded.
    respx.get(f"{PK_BASE_URL}/sets").mock(
        side_effect=[
            httpx.Response(200, json={"data": [{"id": "bad-set", "name": "Bad Set"}, {"id": "good-set", "name": "Good Set"}]}),
            httpx.Response(200, json={"data": []}),
        ]
    )

    def cards_handler(request):
        if "bad-set" in request.url.params.get("q", ""):
            return httpx.Response(500)
        if request.url.params.get("page") == "1":
            return httpx.Response(200, json={"data": [{"id": "good-set-1", "name": "Pikachu", "number": "1"}]})
        return httpx.Response(200, json={"data": []})  # page 2+: end pagination

    respx.get(f"{PK_BASE_URL}/cards").mock(side_effect=cards_handler)
    respx.get(f"{TCGDEX_BASE_URL}/en/sets").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{TCGDEX_BASE_URL}/ja/sets").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{TCGDEX_BASE_URL}/zh-tw/sets").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{TCGDEX_BASE_URL}/zh-cn/sets").mock(return_value=httpx.Response(200, json=[]))

    result = jobs.import_catalog(db_conn)

    assert result["pokemontcg_io"] == 1  # good-set's card still got imported
    assert len(result["errors"]) == 1
    assert "bad-set" in result["errors"][0]

    count = db_conn.execute("SELECT COUNT(*) AS c FROM cards WHERE source_card_id = 'good-set-1'").fetchone()["c"]
    assert count == 1

    run = db_conn.execute(
        "SELECT status, records_written FROM connector_runs WHERE source_id = 'pokemontcg_io'"
    ).fetchone()
    assert run["status"] == "error"  # honest: the run had a failure, even though it also made progress
    assert run["records_written"] == 1


def _seed_tcgdex_card(conn, number: str, set_source_set_id: str = "en:base1", release_date: str | None = None, series: str | None = None) -> str:
    from connectors.base import CatalogCard, CatalogSet
    from services.ingest import upsert_card, upsert_set

    set_id = upsert_set(
        conn,
        CatalogSet(source="tcgdex", source_set_id=set_source_set_id, name=set_source_set_id, language="en", release_date=release_date, series=series),
    )
    return upsert_card(
        conn,
        CatalogCard(source="tcgdex", source_card_id=f"{set_source_set_id}-{number}", set_source_set_id=set_source_set_id, name=f"Card {number}", number=number, language="en"),
        set_id,
    )


def test_select_cards_for_tcgdex_poll_prioritizes_never_observed(db_conn):
    _seed_tcgdex_card(db_conn, "1")
    _seed_tcgdex_card(db_conn, "2")
    db_conn.execute(
        "INSERT INTO price_snapshots (card_id, grade_id, source_id, observed_at, price_amount, price_currency) "
        "VALUES ((SELECT id FROM cards WHERE source_card_id='en:base1-1'), 'raw-nm', 'tcgdex', '2026-09-01T00:00:00.000000Z', 1, 'EUR')"
    )
    db_conn.commit()

    ordered = jobs._select_cards_for_tcgdex_poll(db_conn, limit=10)
    assert ordered == ["en:base1-2", "en:base1-1"]  # never-observed card first


def test_select_cards_for_tcgdex_poll_prefers_newer_sets_among_never_observed(db_conn):
    # Real regression: with no tiebreaker at all, a rotation batch of 300 came back with zero
    # pricing on every single card — SQLite fell back to insertion order, which tracked nothing
    # about whether a card is actually likely to have an active market listing. Newest-set-first
    # is a much better bet than "whatever order catalog import happened to process sets in."
    _seed_tcgdex_card(db_conn, "1", set_source_set_id="en:old-set", release_date="1999-01-09")
    _seed_tcgdex_card(db_conn, "1", set_source_set_id="en:new-set", release_date="2026-08-01")
    db_conn.commit()

    ordered = jobs._select_cards_for_tcgdex_poll(db_conn, limit=10)
    assert ordered == ["en:new-set-1", "en:old-set-1"]


def test_select_cards_for_tcgdex_poll_excludes_pokemon_tcg_pocket(db_conn):
    # Real regression, root cause: a rotation batch of 300 came back with zero prices because it
    # was entirely Pokémon TCG Pocket cards (serie id "tcgp") — a digital-only mobile game that
    # can never have physical-marketplace pricing. Must never be selected for a price poll.
    _seed_tcgdex_card(db_conn, "1", set_source_set_id="en:A1", series="tcgp")
    _seed_tcgdex_card(db_conn, "1", set_source_set_id="en:base1", series="base")
    db_conn.commit()

    ordered = jobs._select_cards_for_tcgdex_poll(db_conn, limit=10)
    assert ordered == ["en:base1-1"]


def test_select_cards_for_tcgdex_poll_respects_limit(db_conn):
    for i in range(5):
        _seed_tcgdex_card(db_conn, str(i))
    db_conn.commit()
    assert len(jobs._select_cards_for_tcgdex_poll(db_conn, limit=2)) == 2


def test_select_watchlist_cards_returns_cards_from_latest_top100_only(db_conn):
    _seed_tcgdex_card(db_conn, "1")
    _seed_tcgdex_card(db_conn, "2")
    card1 = db_conn.execute("SELECT id FROM cards WHERE source_card_id = 'en:base1-1'").fetchone()["id"]
    card2 = db_conn.execute("SELECT id FROM cards WHERE source_card_id = 'en:base1-2'").fetchone()["id"]

    def insert_snapshot(card_id, computed_at):
        db_conn.execute(
            "INSERT INTO top100_snapshots (time_range, computed_at, rank, card_id, grade_id, "
            "start_price_eur, end_price_eur, change_pct, change_abs_eur, observation_count, sort_key) "
            "VALUES ('7D', ?, 1, ?, 'raw-nm', 1, 1, 0, 0, 1, 'change_pct')",
            (computed_at, card_id),
        )

    insert_snapshot(card1, "2026-09-01T00:00:00.000000Z")  # older batch — must be ignored
    insert_snapshot(card2, "2026-09-02T00:00:00.000000Z")  # latest batch
    db_conn.commit()

    watchlist = jobs._select_watchlist_cards_for_tcgdex_poll(db_conn)
    assert watchlist == ["en:base1-2"]


@respx.mock
def test_poll_tcgdex_price_snapshots_ingests_and_records_run(db_conn):
    _seed_tcgdex_card(db_conn, "4")
    db_conn.commit()

    respx.get(f"{TCGDEX_BASE_URL}/en/cards/base1-4").mock(
        return_value=httpx.Response(
            200,
            json={"id": "base1-4", "pricing": {"cardmarket": {"trend": 100.0}, "tcgplayer": None}},
        )
    )

    result = jobs.poll_tcgdex_price_snapshots(db_conn, batch_size=10)
    assert result["cards_polled"] == 1
    assert result["written"] == 1

    run = db_conn.execute("SELECT status FROM connector_runs WHERE source_id = 'tcgdex'").fetchone()
    assert run["status"] == "ok"


@respx.mock
def test_poll_tcgdex_price_snapshots_always_includes_watchlist_cards(db_conn):
    # Real problem this fixes: the rotation alone would never re-select an already-observed
    # card until every other card in a potentially huge catalog had been touched first — a card
    # the user is actively looking at (i.e. ranked in Top 100) could go untouched for days.
    _seed_tcgdex_card(db_conn, "1", set_source_set_id="en:watched")
    watched_card_id = db_conn.execute("SELECT id FROM cards WHERE source_card_id = 'en:watched-1'").fetchone()["id"]
    db_conn.execute(
        "INSERT INTO price_snapshots (card_id, grade_id, source_id, observed_at, price_amount, price_currency, price_eur) "
        "VALUES (?, 'raw-nm', 'tcgdex', '2026-09-16T00:00:00.000000Z', 100, 'EUR', 100)",
        (watched_card_id,),
    )  # already observed -> the plain rotation query would deprioritize it
    db_conn.execute(
        "INSERT INTO top100_snapshots (time_range, computed_at, rank, card_id, grade_id, "
        "start_price_eur, end_price_eur, change_pct, change_abs_eur, observation_count, sort_key) "
        "VALUES ('7D', '2026-09-16T01:00:00.000000Z', 1, ?, 'raw-nm', 100, 100, 0, 0, 1, 'change_pct')",
        (watched_card_id,),
    )
    db_conn.commit()

    route = respx.get(f"{TCGDEX_BASE_URL}/en/cards/watched-1").mock(
        return_value=httpx.Response(200, json={"id": "watched-1", "pricing": {"cardmarket": {"trend": 105.0}, "tcgplayer": None}})
    )

    result = jobs.poll_tcgdex_price_snapshots(db_conn, batch_size=0)
    assert route.called
    assert result["cards_polled"] == 1
    assert result["written"] == 1
