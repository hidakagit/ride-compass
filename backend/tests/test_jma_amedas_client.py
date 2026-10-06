"""`infrastructure/jma_amedas_client.py`——気象庁アメダスの観測所マスタ・最新時刻・観測値の取得と、応答の形の解き方。

入口は`fetch_station_table`・`fetch_latest_observation_time`・`fetch_observation_map`の3つで、気象庁の代役（respx）へ
本物の`httpx.AsyncClient`を向けて呼ぶ。見るのは、返る値（`AmedasStation`・`AmedasReading`（風向コードの読み替えを含む）・時刻）と、取得に失敗したときの
None、プロセス内キャッシュで上流を引き直さないこと。

ここで見ないもの:
- キャッシュの骨格（失敗をキャッシュしない・該当なしのNoneもキャッシュする・ログの`fields`）→ `test_simple_api_client.py`
- 観測値をRedisへ置く・最寄りの観測所を選ぶ・雨の履歴 → `test_jma_amedas_service.py`
- 体感温度 → `test_jma_amedas.py`
- 16方位の呼び名の並び（`domain/geo.py: SIXTEEN_POINT_LABELS`） → `test_geo.py`
"""

from datetime import datetime, timedelta, timezone

import pytest
import respx

from app.domain.jma_amedas import WindDirection
from app.infrastructure import jma_amedas_client
from app.infrastructure.jma_amedas_client import new_latest_time_cache, new_station_table_cache
from tests.fake_http import answering, client_for


# --- 観測所マスタ ---


async def test_station_table_reads_degree_minute_coordinates():
    client = answering(json={"44132": {"kjName": "東京", "lat": [35, 41.5], "lon": [139, 45.0], "alt": 25}})

    stations = await jma_amedas_client.fetch_station_table(client, new_station_table_cache())

    assert stations == {"44132": jma_amedas_client.AmedasStation(latitude=35 + 41.5 / 60, longitude=139.75)}


@pytest.mark.parametrize("missing", ["lat", "lon"])
async def test_station_without_coordinates_is_left_out(missing):
    entry = {"kjName": "某所", "lat": [35, 0.0], "lon": [139, 0.0]}
    del entry[missing]
    client = answering(json={"99999": entry, "44132": {"kjName": "東京", "lat": [35, 41.5], "lon": [139, 45.0]}})

    stations = await jma_amedas_client.fetch_station_table(client, new_station_table_cache())

    assert list(stations) == ["44132"]


async def test_station_table_is_fetched_once_while_cached():
    router = respx.Router()
    route = router.get(jma_amedas_client.AMEDAS_STATION_TABLE_URL).respond(
        json={"44132": {"kjName": "東京", "lat": [35, 41.5], "lon": [139, 45.0]}}
    )
    client = client_for(router)

    cache = new_station_table_cache()

    first = await jma_amedas_client.fetch_station_table(client, cache)
    second = await jma_amedas_client.fetch_station_table(client, cache)

    assert second == first
    assert route.call_count == 1


@pytest.mark.parametrize(
    "response",
    [
        pytest.param({"status_code": 500}, id="サーバの失敗"),
        pytest.param({"json": [["44132"]]}, id="辞書でない"),
        pytest.param({"text": "<html>"}, id="JSONでない"),
    ],
)
async def test_station_table_failure_is_none(response):
    assert await jma_amedas_client.fetch_station_table(answering(**response), new_station_table_cache()) is None


# --- 最新の観測時刻 ---


async def test_latest_time_is_the_offset_aware_time_in_the_plain_text():
    client = answering(text="2026-08-29T17:00:00+09:00\n")

    observed_at = await jma_amedas_client.fetch_latest_observation_time(client, new_latest_time_cache())

    assert observed_at == datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)
    assert observed_at.utcoffset() == timedelta(hours=9)


async def test_latest_time_is_fetched_once_while_cached():
    router = respx.Router()
    route = router.get(jma_amedas_client.AMEDAS_LATEST_TIME_URL).respond(text="2026-08-29T17:00:00+09:00")
    client = client_for(router)

    cache = new_latest_time_cache()

    await jma_amedas_client.fetch_latest_observation_time(client, cache)
    await jma_amedas_client.fetch_latest_observation_time(client, cache)

    assert route.call_count == 1


@pytest.mark.parametrize(
    "response",
    [
        pytest.param({"status_code": 503}, id="サーバの失敗"),
        pytest.param({"text": "not a time"}, id="時刻でない"),
        pytest.param({"text": "2026-08-29T17:00:00"}, id="時差が無い"),
    ],
)
async def test_latest_time_failure_is_none(response):
    assert await jma_amedas_client.fetch_latest_observation_time(answering(**response), new_latest_time_cache()) is None


# --- 観測値 ---

_FULL_READING = {
    "temp": [21.3, 0],
    "humidity": [68, 0],
    "wind": [3.2, 0],
    "windDirection": [8, 0],
    "precipitation10m": [0.5, 0],
    "sun10m": [4, 0],
    "precipitation1h": [2.0, 0],
}


async def test_observation_map_is_requested_by_the_jst_time():
    """URLの時刻はJSTの`YYYYMMDDHHMMSS`。UTCで渡しても同じ観測を引く。"""
    router = respx.Router()
    url = jma_amedas_client.AMEDAS_OBSERVATION_URL_TEMPLATE.format(timestamp="20260829170000")
    route = router.get(url).respond(json={"44132": _FULL_READING})

    readings = await jma_amedas_client.fetch_observation_map(
        client_for(router), datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)
    )

    assert route.called
    assert readings == {
        "44132": jma_amedas_client.AmedasReading(
            temperature_c=21.3,
            humidity_percent=68,
            wind_speed_ms=3.2,
            wind_direction=WindDirection(deg=180.0, label="南"),
            precipitation_10min_mm=0.5,
            precipitation_1h_mm=2.0,
            reports_precipitation_1h=True,
        )
    }


async def test_reading_without_a_sensor_has_none_and_no_hourly_rain():
    """雨量計しか持たない観測所: 他の項目は無く、正時でない観測は1時間雨量の項目も無い。"""
    client = answering(json={"11001": {"precipitation10m": [0.0, 0]}})

    readings = await jma_amedas_client.fetch_observation_map(client, datetime(2026, 8, 29, 17, 10, tzinfo=timezone.utc))

    assert readings == {
        "11001": jma_amedas_client.AmedasReading(
            temperature_c=None,
            humidity_percent=None,
            wind_speed_ms=None,
            wind_direction=None,
            precipitation_10min_mm=0.0,
            precipitation_1h_mm=None,
            reports_precipitation_1h=False,
        )
    }


async def test_missing_value_is_none_but_the_hourly_rain_item_is_still_reported():
    """雨量計はあるが欠測（`[null, フラグ]`）なら、値はNoneで、1時間雨量の項目は持つ。"""
    client = answering(json={"44132": {"precipitation1h": [None, 5]}})

    readings = await jma_amedas_client.fetch_observation_map(client, datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc))

    assert readings["44132"] == jma_amedas_client.AmedasReading(
        temperature_c=None,
        humidity_percent=None,
        wind_speed_ms=None,
        wind_direction=None,
        precipitation_10min_mm=None,
        precipitation_1h_mm=None,
        reports_precipitation_1h=True,
    )


async def _wind_direction(code) -> WindDirection | None:
    client = answering(json={"44132": {"windDirection": [code, 0]}})
    readings = await jma_amedas_client.fetch_observation_map(client, datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc))
    assert readings is not None
    return readings["44132"].wind_direction


@pytest.mark.parametrize(
    ("code", "deg", "label"),
    [(1, 22.5, "北北東"), (16, 0.0, "北")],
)
async def test_jma_wind_codes_read_as_the_direction_the_wind_comes_from(code, deg, label):
    """気象庁の番号は1=北北東から時計回りで16=北。北は360度ではなく0度。"""
    assert await _wind_direction(code) == WindDirection(deg=deg, label=label)


@pytest.mark.parametrize("code", [None, 0, 17])
async def test_calm_missing_and_out_of_range_codes_have_no_direction(code):
    """0は静穏（方位不定）。範囲外を別の方位として出すと向かい風と追い風を取り違えさせる。"""
    assert await _wind_direction(code) is None


async def test_the_sixteen_codes_go_round_clockwise_in_equal_steps():
    degrees = [(await _wind_direction(code)).deg for code in range(1, 17)]  # type: ignore[union-attr]
    steps = [(later - earlier) % 360 for earlier, later in zip(degrees, degrees[1:] + degrees[:1], strict=True)]
    assert steps == [22.5] * 16


@pytest.mark.parametrize(
    "response",
    [
        pytest.param({"status_code": 404}, id="無い時刻"),
        pytest.param({"json": []}, id="辞書でない"),
        pytest.param({"text": "{"}, id="JSONでない"),
    ],
)
async def test_observation_map_failure_is_none(response):
    observed_at = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)

    assert await jma_amedas_client.fetch_observation_map(answering(**response), observed_at) is None
