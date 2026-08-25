from datetime import datetime

from app.domain.route import Coordinates
from app.infrastructure.weather_client import WeatherClient
from app.services.weather_service import WeatherService

POINT = Coordinates(latitude=35.7597, longitude=139.7387)
OTHER_POINT = Coordinates(latitude=35.1, longitude=139.1)

SAMPLE_DATA = {
    "current": {
        "time": "2026-08-13T21:15",
        "temperature_2m": 24.6,
        "wind_speed_10m": 2.5,
        "wind_direction_10m": 69,
        "apparent_temperature": 27.1,
        "wind_gusts_10m": 4.8,
        "precipitation": 0.2,
        "uv_index": 0.0,
    },
    "hourly": {
        "time": ["2026-08-13T20:00", "2026-08-13T21:00", "2026-08-13T22:00", "2026-08-13T23:00"],
        "temperature_2m": [25.0, 24.5, 24.0, 23.8],
        "wind_speed_10m": [3.0, 2.8, 2.5, 2.2],
        "wind_direction_10m": [60, 65, 70, 75],
        "precipitation_probability": [50, 60, 70, 80],
        "apparent_temperature": [27.5, 27.1, 26.6, 26.0],
        "wind_gusts_10m": [5.5, 4.8, 4.2, 3.9],
        "precipitation": [0.3, 0.2, 0.1, 0.0],
        "uv_index": [1.0, 0.0, 0.0, 0.0],
    },
}

# 改善計画T172でパラメータを追加する前のキャッシュ応答を想定した、新フィールドを持たない
# データ（stale cache・Open-Meteo側の一時的な欠落を模す）。graceful Noneフォールバックの検証用。
SAMPLE_DATA_WITHOUT_T172_FIELDS = {
    "current": {
        "time": "2026-08-13T21:15",
        "temperature_2m": 24.6,
        "wind_speed_10m": 2.5,
        "wind_direction_10m": 69,
    },
    "hourly": {
        "time": ["2026-08-13T20:00", "2026-08-13T21:00", "2026-08-13T22:00", "2026-08-13T23:00"],
        "temperature_2m": [25.0, 24.5, 24.0, 23.8],
        "wind_speed_10m": [3.0, 2.8, 2.5, 2.2],
        "wind_direction_10m": [60, 65, 70, 75],
        "precipitation_probability": [50, 60, 70, 80],
    },
}


class FakeWeatherClient:
    def __init__(self, data):
        self._data = data
        self.get_forecast_many_calls: list[list[Coordinates]] = []

    async def get_forecast(self, http_client, point):
        return self._data

    async def get_forecast_many(self, http_client, points):
        self.get_forecast_many_calls.append(points)
        return {WeatherClient.cache_key(point): self._data for point in points}

    cache_key = staticmethod(WeatherClient.cache_key)


async def test_get_conditions_returns_current_when_at_is_none():
    service = WeatherService(FakeWeatherClient(SAMPLE_DATA), http_client=None)

    conditions = await service.get_conditions(POINT)

    assert conditions.observed_at == "2026-08-13T21:15"
    assert conditions.temperature_c == 24.6
    assert conditions.wind_speed_ms == 2.5
    assert conditions.wind_direction_deg == 69
    assert conditions.wind_direction_label == "東"
    # 21:15に最も近いのは21:00（precipitation_probability=60）
    assert conditions.precipitation_probability_percent == 60
    # 改善計画T172: 突風・体感温度・降水量・UV指数はcurrentからそのまま読む
    assert conditions.apparent_temperature_c == 27.1
    assert conditions.wind_gusts_ms == 4.8
    assert conditions.precipitation_mm == 0.2
    assert conditions.uv_index == 0.0


async def test_conditions_from_data_returns_nearest_hourly_for_future_time():
    # get_conditionsはatを取らなくなった（呼び出し元は常にNoneのため引数を削除、
    # 改善計画のデッドコード監査）。未来時刻の近傍hourly選択ロジック自体は
    # get_conditions_manyが使う_conditions_from_dataで健在なため、直接テストする。
    service = WeatherService(FakeWeatherClient(SAMPLE_DATA), http_client=None)

    conditions = service._conditions_from_data(SAMPLE_DATA, at=datetime(2026, 8, 13, 22, 10))

    # 22:10に最も近いのは22:00
    assert conditions.observed_at == "2026-08-13T22:00"
    assert conditions.temperature_c == 24.0
    assert conditions.precipitation_probability_percent == 70
    # 改善計画T172: hourly側は_hourly_index_value経由（同じindex=2を再利用）
    assert conditions.apparent_temperature_c == 26.6
    assert conditions.wind_gusts_ms == 4.2
    assert conditions.precipitation_mm == 0.1
    assert conditions.uv_index == 0.0


async def test_conditions_from_data_returns_none_when_at_is_outside_hourly_range():
    service = WeatherService(FakeWeatherClient(SAMPLE_DATA), http_client=None)

    # hourlyは2026-08-13の20:00-23:00のみ。翌日はhourlyの範囲外。
    conditions = service._conditions_from_data(SAMPLE_DATA, at=datetime(2026, 8, 14, 10, 0))

    assert conditions is None


async def test_get_conditions_falls_back_to_none_when_t172_fields_are_missing():
    # 改善計画T172で追加したフィールドが無い応答（デプロイ直後のstale cache等）でも
    # 例外にならず、その4項目だけNoneになり他の既存項目は従来どおり取得できることを確認する。
    service = WeatherService(FakeWeatherClient(SAMPLE_DATA_WITHOUT_T172_FIELDS), http_client=None)

    conditions = await service.get_conditions(POINT)

    assert conditions is not None
    assert conditions.temperature_c == 24.6
    assert conditions.apparent_temperature_c is None
    assert conditions.wind_gusts_ms is None
    assert conditions.precipitation_mm is None
    assert conditions.uv_index is None


async def test_get_conditions_returns_none_when_forecast_unavailable():
    service = WeatherService(FakeWeatherClient(None), http_client=None)

    conditions = await service.get_conditions(POINT)

    assert conditions is None


async def test_get_conditions_many_returns_conditions_per_point():
    service = WeatherService(FakeWeatherClient(SAMPLE_DATA), http_client=None)

    results = await service.get_conditions_many(
        [POINT, OTHER_POINT],
        [None, datetime(2026, 8, 13, 22, 10)],
    )

    assert len(results) == 2
    assert results[0].observed_at == "2026-08-13T21:15"
    assert results[1].observed_at == "2026-08-13T22:00"


async def test_prefetch_delegates_to_client_get_forecast_many():
    client = FakeWeatherClient(SAMPLE_DATA)
    service = WeatherService(client, http_client=None)

    await service.prefetch([POINT, OTHER_POINT])

    assert client.get_forecast_many_calls == [[POINT, OTHER_POINT]]


async def test_get_conditions_many_returns_none_for_points_without_forecast():
    class MissingSomeForecastsClient(FakeWeatherClient):
        async def get_forecast_many(self, http_client, points):
            return {WeatherClient.cache_key(points[0]): None, WeatherClient.cache_key(points[1]): SAMPLE_DATA}

    service = WeatherService(MissingSomeForecastsClient(SAMPLE_DATA), http_client=None)

    results = await service.get_conditions_many([POINT, OTHER_POINT], [None, None])

    assert results[0] is None
    assert results[1] is not None


async def test_get_wind_grid_returns_hourly_arrays_per_point():
    service = WeatherService(FakeWeatherClient(SAMPLE_DATA), http_client=None)

    times, results = await service.get_wind_grid([POINT, OTHER_POINT])

    assert times == SAMPLE_DATA["hourly"]["time"]
    assert len(results) == 2
    assert results[0].latitude == POINT.latitude
    assert results[0].longitude == POINT.longitude
    assert results[0].wind_speed_ms == SAMPLE_DATA["hourly"]["wind_speed_10m"]
    assert results[0].wind_direction_deg == SAMPLE_DATA["hourly"]["wind_direction_10m"]
    assert results[0].precipitation_mm == SAMPLE_DATA["hourly"]["precipitation"]


async def test_get_wind_grid_returns_none_for_points_without_forecast():
    class MissingSomeForecastsClient(FakeWeatherClient):
        async def get_forecast_many(self, http_client, points):
            return {WeatherClient.cache_key(points[0]): None, WeatherClient.cache_key(points[1]): SAMPLE_DATA}

    service = WeatherService(MissingSomeForecastsClient(SAMPLE_DATA), http_client=None)

    times, results = await service.get_wind_grid([POINT, OTHER_POINT])

    assert results[0] is None
    assert results[1] is not None
    # 最初の地点が失敗しても、成功した2番目の地点のtimesが採用される。
    assert times == SAMPLE_DATA["hourly"]["time"]


async def test_get_wind_grid_returns_none_when_hourly_missing():
    service = WeatherService(FakeWeatherClient({"current": SAMPLE_DATA["current"]}), http_client=None)

    times, results = await service.get_wind_grid([POINT])

    assert results[0] is None
    assert times == []


async def test_get_wind_grid_returns_none_when_wind_fields_missing():
    stale_data = {"hourly": {"time": ["2026-08-13T20:00"], "temperature_2m": [25.0]}}
    service = WeatherService(FakeWeatherClient(stale_data), http_client=None)

    times, results = await service.get_wind_grid([POINT])

    assert results[0] is None
    assert times == []


async def test_get_wind_grid_returns_none_when_precipitation_missing():
    # T183: precipitationは風の2フィールドと同じく必須（3配列とも欠けると格子点全体をNoneにする）。
    data_without_precipitation = {
        "hourly": {
            "time": ["2026-08-13T20:00"],
            "wind_speed_10m": [3.0],
            "wind_direction_10m": [60],
        }
    }
    service = WeatherService(FakeWeatherClient(data_without_precipitation), http_client=None)

    times, results = await service.get_wind_grid([POINT])

    assert results[0] is None
    assert times == []
