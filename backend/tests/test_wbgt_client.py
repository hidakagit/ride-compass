"""`infrastructure/wbgt_client.py`——環境省 熱中症予防情報サイトの地点マスタ(CSV)と
暑さ指数予測値(JSON)の取得。

ここで見ないもの:
- キャッシュ参照・形の検査・例外をNoneへ倒す骨格 → `test_simple_api_client.py`
- 最寄り地点の選び方・予測値の読み替え（10倍された整数文字列の割り戻し・最新発表回の
  選択） → `domain/wbgt_points.py`・`wbgt_service.py`側
"""

import pytest
from cachetools import TTLCache

from app.infrastructure import wbgt_client
from tests.fake_api_http import FakeHttpClient, HttpStatusErrorHttpClient

#: 地点マスタCSVの列数（先頭行がヘッダー、使うのは地点番号・観測所名・緯度経度・終了日）。
_COLUMNS = 18
_ACTIVE = "9999-99-99"

#: 発表時刻の検索範囲。呼び出し元は「現在時刻を含む直近N時間」を渡す。
_RANGE_FROM = "20260701000000"
_RANGE_TO = "20260701090000"


@pytest.fixture(autouse=True)
def _clear_module_caches():
    """プロセス内TTLCacheはテスト間で持ち越される。モジュールが持つキャッシュを
    名前で並べずに走査して空にする（キャッシュが増えても取りこぼさない）。"""
    for value in vars(wbgt_client).values():
        if isinstance(value, TTLCache):
            value.clear()


def _row(no, name, lat_deg, lat_min, lon_deg, lon_min, end_date):
    row = [""] * _COLUMNS
    row[2] = no
    row[3] = name
    row[7] = lat_deg
    row[8] = lat_min
    row[9] = lon_deg
    row[10] = lon_min
    row[12] = end_date
    return ",".join(row)


def _csv(rows):
    header = ",".join(
        ["", "", "地点番号", "観測所名", "", "", "", "Latitude", "Latitude_3", "Longitude", "Longitude_4", "",
         "End Year-End Month-End Day", "", "", "", "", ""]
    )
    return "\n".join([header, *rows]) + "\n"


async def test_point_master_converts_degrees_and_minutes():
    client = FakeHttpClient(text=_csv([_row("11001", "宗谷岬", "45", "31.2", "141", "56.1", _ACTIVE)]))

    points = await wbgt_client.fetch_point_master(client)

    assert len(points) == 1
    assert points[0].no == "11001"
    assert points[0].name == "宗谷岬"
    assert points[0].latitude == pytest.approx(45 + 31.2 / 60.0)
    assert points[0].longitude == pytest.approx(141 + 56.1 / 60.0)


async def test_point_master_excludes_retired_points():
    client = FakeHttpClient(
        text=_csv(
            [
                _row("44132", "東京", "35", "41.4", "139", "45.6", _ACTIVE),
                _row("44166", "旧地点", "35", "30.0", "139", "30.0", "2025-03-31"),
            ]
        )
    )

    points = await wbgt_client.fetch_point_master(client)

    assert [point.no for point in points] == ["44132"]


async def test_point_master_skips_rows_without_the_end_date_column():
    """配布CSVの末尾の空行は列数を満たさない。1行でも落とすとマスタ全体がNoneになる。"""
    client = FakeHttpClient(
        text=_csv([_row("44132", "東京", "35", "41.4", "139", "45.6", _ACTIVE)]) + "\n"
    )

    points = await wbgt_client.fetch_point_master(client)

    assert [point.no for point in points] == ["44132"]


async def test_point_master_skips_rows_with_unparsable_coordinates():
    client = FakeHttpClient(
        text=_csv(
            [
                _row("44100", "座標欠損", "", "", "", "", _ACTIVE),
                _row("44132", "東京", "35", "41.4", "139", "45.6", _ACTIVE),
            ]
        )
    )

    points = await wbgt_client.fetch_point_master(client)

    assert [point.no for point in points] == ["44132"]


async def test_point_master_trims_surrounding_whitespace():
    """余白付きの地点番号はそのまま予測値APIのクエリへ載り、その地点の予測が引けなくなる。"""
    client = FakeHttpClient(
        text=_csv([_row(" 44132 ", " 東京 ", " 35 ", " 41.4 ", " 139 ", " 45.6 ", f" {_ACTIVE} ")])
    )

    points = await wbgt_client.fetch_point_master(client)

    assert [(point.no, point.name) for point in points] == [("44132", "東京")]


async def test_point_master_with_only_a_header_returns_no_points():
    client = FakeHttpClient(text=_csv([]))

    assert await wbgt_client.fetch_point_master(client) == []


async def test_point_master_is_cached_across_calls():
    client = FakeHttpClient(text=_csv([_row("44132", "東京", "35", "41.4", "139", "45.6", _ACTIVE)]))

    first = await wbgt_client.fetch_point_master(client)
    second = await wbgt_client.fetch_point_master(client)

    assert client.call_count == 1
    assert second == first


async def test_point_master_http_error_returns_none():
    assert await wbgt_client.fetch_point_master(HttpStatusErrorHttpClient()) is None


async def test_forecast_requests_a_continuous_range_and_returns_the_series():
    """`date_search_type=3`（特定時刻）は発表が無いと空を返すため、連続期間で引く。"""
    client = FakeHttpClient({"status": "success", "data": [{"forecast_val": "280"}]})

    result = await wbgt_client.fetch_forecast(client, "44132", _RANGE_FROM, _RANGE_TO)

    assert result == [{"forecast_val": "280"}]
    assert client.last_params == {
        "location_type": 1,
        "date_search_type": 1,
        "wbgt_nos": "44132",
        "range_date_from": _RANGE_FROM,
        "range_date_to": _RANGE_TO,
    }


async def test_forecast_rejects_unsuccessful_status():
    client = FakeHttpClient({"status": "error", "data": [{"forecast_val": "280"}]})

    assert await wbgt_client.fetch_forecast(client, "44132", _RANGE_FROM, _RANGE_TO) is None


async def test_forecast_without_a_data_series_returns_none():
    client = FakeHttpClient({"status": "success"})

    assert await wbgt_client.fetch_forecast(client, "44132", _RANGE_FROM, _RANGE_TO) is None


async def test_forecast_cache_key_is_the_point_number_only():
    """地点ごとに1時間キャッシュする。検索範囲を変えても、その間は同じ発表が返る。"""
    client = FakeHttpClient({"status": "success", "data": [{"forecast_val": "280"}]})

    await wbgt_client.fetch_forecast(client, "44132", _RANGE_FROM, _RANGE_TO)
    await wbgt_client.fetch_forecast(client, "44132", "20260701030000", "20260701120000")
    assert client.call_count == 1

    await wbgt_client.fetch_forecast(client, "44136", _RANGE_FROM, _RANGE_TO)
    assert client.call_count == 2
