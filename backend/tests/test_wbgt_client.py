"""`infrastructure/wbgt_client.py`——環境省 熱中症予防情報サイトの地点マスタ(CSV)と
暑さ指数予測値(JSON)を取得し、形を解く。

ここで見ないもの:
- キャッシュ参照・形の検査・例外をNoneへ倒す骨格 → `test_simple_api_client.py`
- 最寄り地点の選び方・最新発表回の選択 → `test_geo.py`・`test_wbgt_service.py`
"""

import logging
from datetime import datetime

import pytest
import respx

from app.domain.time_zone import JST
from app.infrastructure import wbgt_client
from app.infrastructure.wbgt_client import new_forecast_cache, new_point_master_cache
from tests.fake_http import answering, client_for

#: 地点マスタCSVの列数（先頭行がヘッダー、使うのは地点番号・観測所名・緯度経度・終了日）。
_COLUMNS = 18
_ACTIVE = "9999-99-99"

#: 発表時刻の検索範囲。呼び出し元は「現在時刻を含む直近N時間」を渡す。
_RANGE_FROM = datetime(2026, 7, 1, 0, 0, tzinfo=JST)
_RANGE_TO = datetime(2026, 7, 1, 9, 0, tzinfo=JST)


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
    client = answering(text=_csv([_row("11001", "宗谷岬", "45", "31.2", "141", "56.1", _ACTIVE)]))

    points = await wbgt_client.fetch_point_master(client, new_point_master_cache())

    assert len(points) == 1
    assert points[0].no == "11001"
    assert points[0].name == "宗谷岬"
    assert points[0].latitude == pytest.approx(45 + 31.2 / 60.0)
    assert points[0].longitude == pytest.approx(141 + 56.1 / 60.0)


async def test_point_master_excludes_retired_points_without_counting_them_as_unreadable(caplog):
    """運用終了は配布元が宣言した除外で、読めなかったのではない。"""
    client = answering(
        text=_csv(
            [
                _row("44132", "東京", "35", "41.4", "139", "45.6", _ACTIVE),
                _row("44166", "旧地点", "35", "30.0", "139", "30.0", "2025-03-31"),
            ]
        )
    )

    with caplog.at_level(logging.WARNING, logger="ridecompass.wbgt_client"):
        points = await wbgt_client.fetch_point_master(client, new_point_master_cache())

    assert [point.no for point in points] == ["44132"]
    assert caplog.records == []


async def test_point_master_does_not_count_a_trailing_blank_line_as_unreadable(caplog):
    """配布CSVの末尾の空行はデータ行ではない。数えると取得のたびに警告が出て、本物が埋もれる。"""
    client = answering(
        text=_csv([_row("44132", "東京", "35", "41.4", "139", "45.6", _ACTIVE)]) + "\n"
    )

    with caplog.at_level(logging.WARNING, logger="ridecompass.wbgt_client"):
        points = await wbgt_client.fetch_point_master(client, new_point_master_cache())

    assert [point.no for point in points] == ["44132"]
    assert caplog.records == []


@pytest.mark.parametrize(
    "unreadable",
    ["44100,終了日の列が無い", _row("44100", "座標欠損", "", "", "", "", _ACTIVE)],
)
async def test_point_master_skips_unreadable_rows_and_says_so(caplog, unreadable):
    """列構成が変わると読める行だけが残り、遠い地点の値が何事もなく表示される。"""
    client = answering(text=_csv([unreadable, _row("44132", "東京", "35", "41.4", "139", "45.6", _ACTIVE)]))

    with caplog.at_level(logging.WARNING, logger="ridecompass.wbgt_client"):
        points = await wbgt_client.fetch_point_master(client, new_point_master_cache())

    assert [point.no for point in points] == ["44132"]
    assert "unreadable=1 rows=2" in caplog.text


async def test_point_master_trims_surrounding_whitespace():
    """余白付きの地点番号はそのまま予測値APIのクエリへ載り、その地点の予測が引けなくなる。"""
    client = answering(
        text=_csv([_row(" 44132 ", " 東京 ", " 35 ", " 41.4 ", " 139 ", " 45.6 ", f" {_ACTIVE} ")])
    )

    points = await wbgt_client.fetch_point_master(client, new_point_master_cache())

    assert [(point.no, point.name) for point in points] == [("44132", "東京")]


async def test_point_master_is_cached_across_calls():
    upstream = respx.Router()
    upstream.route().respond(text=_csv([_row("44132", "東京", "35", "41.4", "139", "45.6", _ACTIVE)]))
    client = client_for(upstream)

    cache = new_point_master_cache()

    await wbgt_client.fetch_point_master(client, cache)
    await wbgt_client.fetch_point_master(client, cache)

    assert upstream.calls.call_count == 1


async def test_point_master_http_error_returns_none():
    assert await wbgt_client.fetch_point_master(answering(500), new_point_master_cache()) is None


def _forecast_row(**overrides):
    """予測値APIの`data`の1件（項目は2026-09-27に取得した応答の形のまま）。"""
    row = {
        "reference_time": "2026/07/01 08:00:00",
        "wbgt_no": 44132,
        "forecast_val": "280",
        "forecast_time": "2026/07/01 09:00:00",
        "flag": 0,
    }
    row.update(overrides)
    return row


def _success_upstream(*rows) -> respx.Router:
    upstream = respx.Router()
    upstream.route().respond(json={"status": "success", "data": list(rows)})
    return upstream


def _success(*rows):
    return client_for(_success_upstream(*rows))


async def test_a_forecast_is_read_into_its_times_and_the_index_divided_by_ten():
    """配信元は暑さ指数を10倍した整数文字列で返す（"280"→28.0）。"""
    (forecast,) = await wbgt_client.fetch_forecast(
        _success(_forecast_row()), "44132", _RANGE_FROM, _RANGE_TO, new_forecast_cache()
    )

    assert forecast == wbgt_client.WbgtForecast(
        reference_time="2026/07/01 08:00:00",
        forecast_time=datetime(2026, 7, 1, 9, 0, 0),
        forecast_time_text="2026/07/01 09:00:00",
        wbgt=28.0,
    )


async def test_a_forecast_without_a_reference_time_is_left_out():
    result = await wbgt_client.fetch_forecast(
        _success(_forecast_row(reference_time=None)), "44132", _RANGE_FROM, _RANGE_TO, new_forecast_cache()
    )

    assert result == []


@pytest.mark.parametrize("forecast_time", [None, "2026-07-01T09:00:00"])
async def test_a_forecast_time_that_cannot_be_read_is_absent_but_the_row_stays(forecast_time):
    """行は最新の発表回を決めるのに数える。落とすと、古い発表回の値を今の値として選びうる。"""
    (forecast,) = await wbgt_client.fetch_forecast(
        _success(_forecast_row(forecast_time=forecast_time)), "44132", _RANGE_FROM, _RANGE_TO, new_forecast_cache()
    )

    assert forecast.forecast_time is None
    assert forecast.reference_time == "2026/07/01 08:00:00"


@pytest.mark.parametrize("value", [None, "abc"])
async def test_a_value_that_cannot_be_read_is_absent(value):
    (forecast,) = await wbgt_client.fetch_forecast(
        _success(_forecast_row(forecast_val=value)), "44132", _RANGE_FROM, _RANGE_TO, new_forecast_cache()
    )

    assert forecast.wbgt is None


async def test_forecast_requests_a_continuous_range():
    """`date_search_type=3`（特定時刻）は発表が無いと空を返すため、連続期間で引く。"""
    upstream = _success_upstream(_forecast_row())

    await wbgt_client.fetch_forecast(client_for(upstream), "44132", _RANGE_FROM, _RANGE_TO, new_forecast_cache())

    assert dict(upstream.calls.last.request.url.params) == {
        "location_type": "1",
        "date_search_type": "1",
        "wbgt_nos": "44132",
        "range_date_from": "20260701000000",
        "range_date_to": "20260701090000",
    }


@pytest.mark.parametrize("body", [{"status": "error", "data": [_forecast_row()]}, {"status": "success"}])
async def test_a_forecast_response_that_is_not_a_successful_series_returns_none(body):
    client = answering(json=body)

    assert await wbgt_client.fetch_forecast(client, "44132", _RANGE_FROM, _RANGE_TO, new_forecast_cache()) is None


async def test_forecast_cache_key_is_the_point_number_only():
    """地点ごとに1時間キャッシュする。検索範囲を変えても、その間は同じ発表が返る。"""
    upstream = _success_upstream(_forecast_row())
    client = client_for(upstream)

    cache = new_forecast_cache()

    await wbgt_client.fetch_forecast(client, "44132", _RANGE_FROM, _RANGE_TO, cache)
    await wbgt_client.fetch_forecast(
        client, "44132", datetime(2026, 7, 1, 3, tzinfo=JST), datetime(2026, 7, 1, 12, tzinfo=JST), cache
    )
    assert upstream.calls.call_count == 1

    await wbgt_client.fetch_forecast(client, "44136", _RANGE_FROM, _RANGE_TO, cache)
    assert upstream.calls.call_count == 2
