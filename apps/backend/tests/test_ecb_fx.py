import httpx
import respx

from connectors.ecb_fx import HIST_URL, EcbFxConnector

SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <Cube>
    <Cube time="2026-09-15">
      <Cube currency="USD" rate="1.0850"/>
      <Cube currency="DKK" rate="7.4600"/>
    </Cube>
    <Cube time="2026-09-12">
      <Cube currency="USD" rate="1.0820"/>
      <Cube currency="DKK" rate="7.4590"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""


@respx.mock
def test_fetch_rates_filters_by_date_range():
    respx.get(HIST_URL).mock(return_value=httpx.Response(200, text=SAMPLE_FEED))
    connector = EcbFxConnector()
    rates = list(connector.fetch_rates("2026-09-15", "2026-09-15"))
    assert rates == [("2026-09-15", "USD", 1.0850), ("2026-09-15", "DKK", 7.4600)]


@respx.mock
def test_fetch_rates_includes_full_range():
    respx.get(HIST_URL).mock(return_value=httpx.Response(200, text=SAMPLE_FEED))
    connector = EcbFxConnector()
    rates = list(connector.fetch_rates("2026-01-01", "2026-12-31"))
    dates = {r[0] for r in rates}
    assert dates == {"2026-09-15", "2026-09-12"}
