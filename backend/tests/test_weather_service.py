from datetime import datetime

from app.domain.route import Coordinates
from app.services.weather_service import WeatherService

POINT = Coordinates(latitude=35.7597, longitude=139.7387)

SAMPLE_DATA = {
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

    async def get_forecast(self, http_client, point):
        return self._data


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


async def test_get_conditions_returns_nearest_hourly_for_future_time():
    service = WeatherService(FakeWeatherClient(SAMPLE_DATA), http_client=None)

    conditions = await service.get_conditions(POINT, at=datetime(2026, 8, 13, 22, 10))

    # 22:10に最も近いのは22:00
    assert conditions.observed_at == "2026-08-13T22:00"
    assert conditions.temperature_c == 24.0
    assert conditions.precipitation_probability_percent == 70


async def test_get_conditions_returns_none_when_at_is_outside_hourly_range():
    service = WeatherService(FakeWeatherClient(SAMPLE_DATA), http_client=None)

    # hourlyは2026-08-13の20:00-23:00のみ。翌日はhourlyの範囲外。
    conditions = await service.get_conditions(POINT, at=datetime(2026, 8, 14, 10, 0))

    assert conditions is None


async def test_get_conditions_returns_none_when_forecast_unavailable():
    service = WeatherService(FakeWeatherClient(None), http_client=None)

    conditions = await service.get_conditions(POINT)

    assert conditions is None
