import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_weather_service
from app.config import settings
from app.domain.weather import WeatherConditions
from app.infrastructure import rate_limiter
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    # rate_limiterはプロセス内グローバルの固定窓カウンタのため、テスト間で
    # 消し込まないと前のテストのリクエストが今のテストの上限に食い込む。
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


class FakeWeatherService:
    def __init__(self, conditions, wind_grid=None):
        self._conditions = conditions
        self._wind_grid = wind_grid if wind_grid is not None else []

    async def get_conditions(self, point, at=None):
        return self._conditions

    async def get_wind_grid(self, points):
        return self._wind_grid


def test_get_weather_returns_conditions_on_success():
    conditions = WeatherConditions(
        temperature_c=24.6,
        apparent_temperature_c=27.1,
        wind_speed_ms=2.5,
        wind_direction_deg=69,
        wind_direction_label="東",
        wind_gusts_ms=4.8,
        precipitation_probability_percent=60,
        precipitation_mm=0.5,
        uv_index=6.2,
        observed_at="2026-08-13T21:15",
    )
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(conditions)

    try:
        response = client.get("/api/weather", params={"latitude": 35.7597, "longitude": 139.7387})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["temperature_c"] == 24.6
    assert body["wind_direction_label"] == "東"


def test_get_weather_returns_502_when_unavailable():
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(None)

    try:
        response = client.get("/api/weather", params={"latitude": 35.7597, "longitude": 139.7387})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502


def test_get_weather_is_rate_limited_per_client():
    conditions = WeatherConditions(
        temperature_c=24.6,
        apparent_temperature_c=27.1,
        wind_speed_ms=2.5,
        wind_direction_deg=69,
        wind_direction_label="東",
        wind_gusts_ms=4.8,
        precipitation_probability_percent=60,
        precipitation_mm=0.5,
        uv_index=6.2,
        observed_at="2026-08-13T21:15",
    )
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(conditions)

    try:
        for _ in range(settings.weather_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit("weather:testclient", settings.weather_rate_limit_per_minute)
        params = {"latitude": 35.7597, "longitude": 139.7387}
        assert client.get("/api/weather", params=params).status_code == 200
        response = client.get("/api/weather", params={"latitude": 35.7597, "longitude": 139.7387})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429


def test_get_wind_grid_returns_points_on_success():
    from app.domain.wind_grid import WindGridPoint

    grid = [
        WindGridPoint(
            latitude=35.68,
            longitude=139.77,
            times=["2026-08-20T12:00", "2026-08-20T13:00"],
            wind_speed_ms=[2.5, 3.1],
            wind_direction_deg=[90.0, 95.0],
        )
    ]
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(None, wind_grid=grid)

    try:
        response = client.get("/api/weather/wind-grid")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["latitude"] == 35.68
    assert body[0]["wind_speed_ms"] == [2.5, 3.1]


def test_get_wind_grid_omits_none_points():
    from app.domain.wind_grid import WindGridPoint

    grid = [
        WindGridPoint(
            latitude=35.68, longitude=139.77, times=["2026-08-20T12:00"], wind_speed_ms=[2.5], wind_direction_deg=[90.0]
        ),
        None,
    ]
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(None, wind_grid=grid)

    try:
        response = client.get("/api/weather/wind-grid")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_wind_grid_is_rate_limited_per_client():
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(None, wind_grid=[])

    try:
        for _ in range(settings.wind_grid_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit("wind-grid:testclient", settings.wind_grid_rate_limit_per_minute)
        assert client.get("/api/weather/wind-grid").status_code == 200
        response = client.get("/api/weather/wind-grid")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429
