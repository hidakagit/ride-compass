"""`infrastructure/wbgt_client.py`——情報提供地点マスタ（CSV）と暑さ指数予測値を引く。

ここで見ないもの:
- TTLキャッシュの引き当てと、失敗をNoneへ倒す骨格 → `test_simple_api_client.py`
- 最寄りの情報提供地点の選択 → `test_wbgt_points.py`
- 予測値列から発表回を選び、10で割って暑さ指数へ直す処理 → `test_wbgt_service.py`

マスタCSVの列の並び（緯度・経度が度と分の別列）は環境省の配布物が決めるもので、
検査はその並びに沿って行を組み立てて渡す。
"""

import pytest

from app.domain.wbgt_points import WbgtPoint
from app.infrastructure import wbgt_client
from tests.fake_api_http import FakeHttpClient

LIVE = "9999-99-99"


def master_row(
    *,
    no="44",
    name="東京",
    lat_deg="35",
    lat_min="30",
    lon_deg="139",
    lon_min="45",
    end_date=LIVE,
    columns=13,
):
    row = [""] * columns
    for index, value in ((2, no), (3, name), (7, lat_deg), (8, lat_min), (9, lon_deg), (10, lon_min), (12, end_date)):
        if index < columns:
            row[index] = value
    return ",".join(row)


def master_csv(*rows):
    return "\n".join([master_row(no="header", name="見出し"), *rows])


@pytest.fixture(autouse=True)
def _clear_caches():
    wbgt_client._point_master_cache.clear()
    wbgt_client._forecast_cache.clear()
    yield
    wbgt_client._point_master_cache.clear()
    wbgt_client._forecast_cache.clear()


async def test_degrees_and_minutes_become_decimal_degrees():
    client = FakeHttpClient(text=master_csv(master_row(lat_deg="35", lat_min="30", lon_deg="139", lon_min="45")))

    points = await wbgt_client.fetch_point_master(client)

    assert points == [WbgtPoint(no="44", name="東京", latitude=35.5, longitude=139.75)]


async def test_first_line_is_not_a_point():
    """見出し行を地点にすると、最寄り地点の探索が実在しない地点を選びうる。"""
    client = FakeHttpClient(text=master_csv(master_row(no="44")))

    points = await wbgt_client.fetch_point_master(client)

    assert [point.no for point in points] == ["44"]


async def test_retired_point_is_excluded():
    """運用の終わった地点を残すと、その地点の予測値が永久に空で返る。"""
    client = FakeHttpClient(
        text=master_csv(master_row(no="44"), master_row(no="45", end_date="2024-03-31")),
    )

    points = await wbgt_client.fetch_point_master(client)

    assert [point.no for point in points] == ["44"]


async def test_short_row_is_skipped_and_the_rest_survive():
    client = FakeHttpClient(text=master_csv(master_row(no="44", columns=12), master_row(no="45")))

    points = await wbgt_client.fetch_point_master(client)

    assert [point.no for point in points] == ["45"]


async def test_unparsable_coordinate_row_is_skipped_and_the_rest_survive():
    """1行の欠損でマスタ全体を落とすと、暑さ指数が全国どこでも出なくなる。"""
    client = FakeHttpClient(text=master_csv(master_row(no="44", lat_deg="-"), master_row(no="45")))

    points = await wbgt_client.fetch_point_master(client)

    assert [point.no for point in points] == ["45"]


async def test_surrounding_whitespace_is_trimmed():
    """空白付きの地点番号はそのままクエリへ載り、予測値が引けなくなる。"""
    client = FakeHttpClient(
        text=master_csv(master_row(no=" 44 ", name=" 東京 ", lat_deg=" 35 ", lat_min=" 30 ")),
    )

    points = await wbgt_client.fetch_point_master(client)

    assert points == [WbgtPoint(no="44", name="東京", latitude=35.5, longitude=139.75)]


async def test_forecast_query_carries_the_point_and_the_range():
    client = FakeHttpClient({"status": "success", "data": [{"wbgt_no": "44"}]})

    data = await wbgt_client.fetch_forecast(client, "44", "20260829090000", "20260829200000")

    assert data == [{"wbgt_no": "44"}]
    assert client.last_params["wbgt_nos"] == "44"
    assert client.last_params["range_date_from"] == "20260829090000"
    assert client.last_params["range_date_to"] == "20260829200000"


async def test_unsuccessful_status_yields_none():
    """失敗応答を予測値として扱うと、その内容がそのままキャッシュへ居座る。"""
    client = FakeHttpClient({"status": "error", "data": []})

    assert await wbgt_client.fetch_forecast(client, "44", "20260829090000", "20260829200000") is None


async def test_non_list_data_yields_none():
    """配列でない`data`をそのまま通すと、予測値を1件ずつ読む呼び出し元が落ちる。"""
    client = FakeHttpClient({"status": "success", "data": {"wbgt_no": "44"}})

    assert await wbgt_client.fetch_forecast(client, "44", "20260829090000", "20260829200000") is None


async def test_forecast_is_cached_per_point():
    """地点ごとに分けないと、全員が最初に引いた地点の暑さ指数を見ることになる。"""
    client = FakeHttpClient({"status": "success", "data": [{"wbgt_no": "44"}]})

    await wbgt_client.fetch_forecast(client, "44", "20260829090000", "20260829200000")
    await wbgt_client.fetch_forecast(client, "44", "20260829090000", "20260829200000")
    assert client.call_count == 1

    await wbgt_client.fetch_forecast(client, "45", "20260829090000", "20260829200000")
    assert client.call_count == 2
