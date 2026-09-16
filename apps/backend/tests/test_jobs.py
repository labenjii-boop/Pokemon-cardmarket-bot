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
