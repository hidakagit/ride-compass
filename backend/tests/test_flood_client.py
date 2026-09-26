"""`infrastructure/flood_client.py`——指定河川洪水予報の電文一覧を引き、電文の形を解く。

ここで見ないもの:
- TTLキャッシュの引き当てと、失敗をNoneへ倒す骨格 → `test_simple_api_client.py`
- 電文の解釈（発表か解除か・対象の区域か） → `test_flood_forecast_domain.py`
"""

import pytest

from app.domain.flood_forecast import FloodBulletin
from app.infrastructure import flood_client
from tests.fake_api_http import FakeHttpClient

#: flood_xml.jsonの1件。項目は実際の応答の形のまま。
KANDA_RIVER = {
    "status": "通常",
    "reportDatetime": "2026-08-22T17:50:00+09:00",
    "item": {"name": "レベル４氾濫危険警報", "code": "40", "condition": "レベル４氾濫危険警報（発表）"},
    "riverCode": "830304004400",
    "riverName": "神田川",
    "class20Codes": ["1310100", "1310400"],
    "class10Codes": ["130010"],
}


@pytest.fixture(autouse=True)
def _clear_cache():
    flood_client._flood_cache.clear()
    yield
    flood_client._flood_cache.clear()


async def test_a_bulletin_is_read_into_its_code_areas_and_texts():
    bulletins = await flood_client.fetch_flood_documents(FakeHttpClient([KANDA_RIVER]))

    assert bulletins == [
        FloodBulletin(
            code="40",
            class20_codes=("1310100", "1310400"),
            class10_codes=("130010",),
            river_code="830304004400",
            river_name="神田川",
            condition="レベル４氾濫危険警報（発表）",
            report_datetime="2026-08-22T17:50:00+09:00",
        )
    ]


@pytest.mark.parametrize("status", ["訓練", "試験"])
async def test_training_and_test_bulletins_are_not_passed_on(status):
    """訓練・試験の電文を渡すと、実際には出ていない氾濫予報が画面に出る。"""
    bulletins = await flood_client.fetch_flood_documents(FakeHttpClient([{**KANDA_RIVER, "status": status}]))

    assert bulletins == []


@pytest.mark.parametrize("absent", ["missing", "null"])
async def test_missing_or_null_texts_and_areas_read_as_empty(absent):
    """1件の欠けで取り出しごと落とさない。"""
    keys = ("riverCode", "riverName", "reportDatetime", "class20Codes", "class10Codes")
    if absent == "missing":
        entry = {key: value for key, value in KANDA_RIVER.items() if key not in keys}
        entry["item"] = {"code": "40"}
    else:
        entry = {**KANDA_RIVER, **dict.fromkeys(keys), "item": {"code": "40", "condition": None}}

    (bulletin,) = await flood_client.fetch_flood_documents(FakeHttpClient([entry]))

    assert bulletin == FloodBulletin(
        code="40", class20_codes=(), class10_codes=(), river_code="", river_name="", condition="", report_datetime=""
    )


async def test_a_bulletin_without_an_item_has_no_code():
    entry = {key: value for key, value in KANDA_RIVER.items() if key != "item"}

    (bulletin,) = await flood_client.fetch_flood_documents(FakeHttpClient([entry]))

    assert bulletin.code is None


async def test_non_list_response_yields_none():
    """配列でない応答をそのまま通すと、電文を1件ずつ読む呼び出し元が落ちる。"""
    client = FakeHttpClient({"message": "maintenance"})

    assert await flood_client.fetch_flood_documents(client) is None
