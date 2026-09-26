"""`infrastructure/jma_amedas_client.py`——観測所マスタ・最新観測時刻・観測値を引き、気象庁の応答の形を解く。

応答は気象庁の実際の形（[度, 分]の座標・[値, 品質フラグ]の観測値）で与える。

ここで見ないもの:
- TTLキャッシュの引き当てと、失敗をNoneへ倒す骨格 → `test_simple_api_client.py`
- 最寄り観測所の選択・観測値の読み替え・雨の履歴 → `test_jma_amedas_service.py`
"""

import pytest

from app.infrastructure import jma_amedas_client
from app.infrastructure.jma_amedas_client import AmedasReading, AmedasStation
from tests.fake_api_http import FailingHttpClient, FakeHttpClient, FakeResponse, RoutingHttpClient


@pytest.fixture(autouse=True)
def _clear_caches():
    jma_amedas_client._station_table_cache.clear()
    jma_amedas_client._latest_time_cache.clear()
    yield
    jma_amedas_client._station_table_cache.clear()
    jma_amedas_client._latest_time_cache.clear()


#: 観測所マスタ（amedastable.json）の東京の行。2026-09-27に取得した応答の写し。
TOKYO_STATION = {
    "type": "A",
    "elems": "11111111",
    "lat": [35, 41.5],
    "lon": [139, 45.0],
    "alt": 25,
    "kjName": "東京",
    "knName": "トウキョウ",
    "enName": "Tokyo",
}

#: 正時の観測値（map/YYYYMMDDHH0000.json）の東京の行。2026-09-27に取得した応答の写し。
TOKYO_HOURLY_OBSERVATION = {
    "pressure": [1008.7, 0],
    "normalPressure": [1011.5, 0],
    "temp": [18.9, 0],
    "humidity": [94, 0],
    "snow": [None, 5],
    "snow1h": [0, 6],
    "snow6h": [0, 6],
    "snow12h": [0, 6],
    "snow24h": [0, 6],
    "sun10m": [0, 0],
    "sun1h": [0.0, 0],
    "precipitation10m": [0.0, 0],
    "precipitation1h": [0.0, 0],
    "precipitation3h": [0.5, 0],
    "precipitation24h": [4.5, 0],
    "windDirection": [14, 0],
    "wind": [1.7, 0],
}


async def test_station_coordinates_are_read_from_degrees_and_minutes():
    table = await jma_amedas_client.fetch_station_table(FakeHttpClient({"44132": TOKYO_STATION}))

    assert table == {"44132": AmedasStation(name="東京", latitude=35 + 41.5 / 60, longitude=139 + 45.0 / 60)}


@pytest.mark.parametrize("missing", ["lat", "lon", "kjName"])
async def test_a_station_without_coordinates_or_a_name_is_left_out(missing):
    """最寄りにも雨の履歴の座標にも使えない観測所を、表に載せない。"""
    entry = {key: value for key, value in TOKYO_STATION.items() if key != missing}
    client = FakeHttpClient({"44132": entry, "46106": {"lat": [35, 26.3], "lon": [139, 39.1], "kjName": "横浜"}})

    table = await jma_amedas_client.fetch_station_table(client)

    assert set(table) == {"46106"}


async def test_a_station_table_that_is_not_an_object_yields_none():
    assert await jma_amedas_client.fetch_station_table(FakeHttpClient(["44132"])) is None


async def test_latest_observation_time_drops_surrounding_whitespace():
    """改行が残ったままだと観測値のURLが組み立てられず、観測値が1つも出なくなる。"""
    client = FakeHttpClient(text=" 2026-08-29T17:00:00+09:00\n")

    assert await jma_amedas_client.fetch_latest_observation_time(client) == "2026-08-29T17:00:00+09:00"


async def test_blank_latest_observation_time_yields_none():
    """空文字を時刻として返すと、呼び出し元が空のURLを引きに行く。"""
    client = FakeHttpClient(text="   \n")

    assert await jma_amedas_client.fetch_latest_observation_time(client) is None


async def test_an_observation_takes_the_value_of_each_value_and_quality_flag_pair():
    client = FakeHttpClient({"44132": TOKYO_HOURLY_OBSERVATION})

    readings = await jma_amedas_client.fetch_observation_map(client, "20260927050000")

    assert readings == {
        "44132": AmedasReading(
            temperature_c=18.9,
            humidity_percent=94,
            wind_speed_ms=1.7,
            wind_direction_code=14,
            precipitation_10min_mm=0.0,
            sunshine_10min_minutes=0,
            precipitation_1h_mm=0.0,
            reports_precipitation_1h=True,
        )
    }


async def test_missing_sensors_and_missing_values_both_read_as_none_but_only_a_missing_value_reports_rain():
    """雨量計の無い観測所（項目なし）と雨量計の欠測（値がnull）は、雨の履歴で扱いが違う。"""
    client = FakeHttpClient(
        {
            "no-gauge": {"temp": [10.0, 0]},
            "gauge-missing": {"temp": [None, 5], "precipitation1h": [None, 5], "windDirection": [None, 5]},
        }
    )

    readings = await jma_amedas_client.fetch_observation_map(client, "20260829170000")

    assert readings["no-gauge"].precipitation_1h_mm is None
    assert readings["no-gauge"].reports_precipitation_1h is False
    assert readings["no-gauge"].humidity_percent is None
    assert readings["gauge-missing"].precipitation_1h_mm is None
    assert readings["gauge-missing"].reports_precipitation_1h is True
    assert readings["gauge-missing"].temperature_c is None
    assert readings["gauge-missing"].wind_direction_code is None


async def test_observation_map_requests_the_given_timestamp():
    """要求した時刻がURLへ載らないと、いつまでも同じ（古い）観測値が返る。"""
    template = jma_amedas_client.AMEDAS_OBSERVATION_URL_TEMPLATE
    payloads = {
        template.format(timestamp="20260829170000"): {"44132": {"temp": [30.1, 0]}},
        template.format(timestamp="20260829171000"): {"44132": {"temp": [29.8, 0]}},
    }
    client = RoutingHttpClient(lambda url: FakeResponse(payloads[url]))

    first = await jma_amedas_client.fetch_observation_map(client, "20260829170000")
    second = await jma_amedas_client.fetch_observation_map(client, "20260829171000")

    assert first["44132"].temperature_c == 30.1
    assert second["44132"].temperature_c == 29.8


async def test_observation_map_yields_none_when_upstream_fails():
    """例外を外へ出すと、観測値が欠けただけで天候の応答全体が失敗する。"""
    assert await jma_amedas_client.fetch_observation_map(FailingHttpClient(), "20260829170000") is None


async def test_an_observation_map_that_is_not_an_object_yields_none():
    assert await jma_amedas_client.fetch_observation_map(FakeHttpClient([]), "20260829170000") is None
