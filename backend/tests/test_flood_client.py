"""`infrastructure/flood_client.py`——指定河川洪水予報の全国の電文一覧を引き、電文の形を解く。

入口は`fetch_flood_documents`。網は respx の経路（`tests/fake_http.py: client_for`）で通す。
一覧はプロセス内のTTLキャッシュに残るので、テストごとに空から始める。

ここで見ないもの:
- コードの意味（発表・解除の区別）と出発地点への該当 → `test_flood_forecast_domain.py`
- キャッシュの期限切れ・失敗の記録の骨格 → `simple_api_client.py: cached_fetch`の持ち物で、
  期限そのものは`cachetools`が持つ
"""

import logging

import httpx
import pytest
import respx

from app.infrastructure import flood_client
from tests.fake_http import client_for

URL = "https://www.jma.go.jp/bosai/flood/data/r8/flood_xml.json"

KANDA = {
    "status": "通常",
    "reportDatetime": "2026-07-01T10:00:00+09:00",
    "riverCode": "8030100001",
    "riverName": "神田川",
    "class20Codes": ["1310100", "1310200"],
    "class10Codes": ["130011"],
    "item": {"code": "52", "condition": "氾濫危険情報"},
}


@pytest.fixture(autouse=True)
def _empty_bulletin_cache():
    flood_client.flood_cache.clear()
    yield
    flood_client.flood_cache.clear()


def answering(**response) -> tuple[httpx.AsyncClient, respx.Route]:
    router = respx.Router()
    route = router.get(URL).respond(**response)
    return client_for(router), route


async def test_an_operational_bulletin_is_read_into_its_fields():
    client, _ = answering(json=[KANDA])

    (bulletin,) = await flood_client.fetch_flood_documents(client)

    assert bulletin.code == "52"
    assert bulletin.condition == "氾濫危険情報"
    assert bulletin.class20_codes == ("1310100", "1310200")
    assert bulletin.class10_codes == ("130011",)
    assert bulletin.river_code == "8030100001"
    assert bulletin.river_name == "神田川"
    assert bulletin.report_datetime == "2026-07-01T10:00:00+09:00"


async def test_drills_and_entries_that_are_not_objects_are_left_out():
    client, _ = answering(json=[{**KANDA, "status": "訓練"}, "broken", KANDA])

    bulletins = await flood_client.fetch_flood_documents(client)

    assert [b.river_name for b in bulletins] == ["神田川"]


@pytest.mark.parametrize("missing", ["absent", "null"])
async def test_a_bulletin_missing_its_fields_is_still_read_with_empty_values(missing):
    """1件の欠けで、全国の一覧の取り出しごと落とさない。"""
    fields = ("reportDatetime", "riverCode", "riverName", "class20Codes", "class10Codes", "item")
    entry = {"status": "通常"} if missing == "absent" else {"status": "通常", **dict.fromkeys(fields)}
    client, _ = answering(json=[entry, KANDA])

    sparse, full = await flood_client.fetch_flood_documents(client)

    assert sparse.code is None
    assert sparse.class20_codes == sparse.class10_codes == ()
    assert sparse.river_code == sparse.river_name == sparse.condition == sparse.report_datetime == ""
    assert full.river_name == "神田川"


async def test_the_national_list_is_fetched_once_and_reused():
    client, route = answering(json=[KANDA])

    first = await flood_client.fetch_flood_documents(client)
    second = await flood_client.fetch_flood_documents(client)

    assert first == second
    assert route.call_count == 1


@pytest.mark.parametrize(
    "response",
    [{"status_code": 500}, {"json": {"rivers": []}}, {"text": "<html>maintenance</html>"}],
    ids=["server-error", "not-a-list", "not-json"],
)
async def test_an_unusable_answer_gives_nothing_and_is_logged(response, caplog, empty_debug_counters):
    client, _ = answering(**response)

    with caplog.at_level(logging.WARNING):
        assert await flood_client.fetch_flood_documents(client) is None

    assert [r for r in caplog.records if r.levelno >= logging.WARNING and "weather:jma-flood" in r.getMessage()]
