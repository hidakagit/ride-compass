from datetime import datetime

from app.domain.route import Coordinates
from app.domain.weather import WeatherConditions
from app.services.wind_service import WindService

START_TIME = datetime(2026, 8, 13, 12, 0)


def northbound_points() -> list[Coordinates]:
    # 真北に向かう3点の直線
    return [
        Coordinates(latitude=35.0, longitude=139.0),
        Coordinates(latitude=35.05, longitude=139.0),
        Coordinates(latitude=35.1, longitude=139.0),
    ]


def headwind_conditions(speed_ms: float = 5.0) -> WeatherConditions:
    # 北から吹く風＝北向き走行にとっての正面からの向かい風
    return WeatherConditions(
        temperature_c=20.0,
        wind_speed_ms=speed_ms,
        wind_direction_deg=0.0,
        wind_direction_label="北",
        precipitation_probability_percent=0.0,
        observed_at="2026-08-13T12:00",
    )


class FakeWeatherService:
    def __init__(self, conditions_by_call: list):
        self._conditions = conditions_by_call
        self.calls: list[tuple[Coordinates, datetime | None]] = []

    async def get_conditions(self, point: Coordinates, at: datetime | None = None) -> WeatherConditions | None:
        self.calls.append((point, at))
        return self._conditions[len(self.calls) - 1]


async def test_constant_headwind_yields_that_wind_speed_as_score():
    weather = FakeWeatherService([headwind_conditions(5.0), headwind_conditions(5.0)])
    service = WindService(weather)

    profile = await service.get_wind_profile(northbound_points(), START_TIME)

    assert profile["wind_score"] == 5.0


async def test_returns_none_score_when_all_weather_lookups_fail():
    weather = FakeWeatherService([None, None])
    service = WindService(weather)

    profile = await service.get_wind_profile(northbound_points(), START_TIME)

    assert profile["wind_score"] is None
    assert [s["wind_penalty"] for s in profile["segments"]] == [None, None]


async def test_ignores_segments_with_missing_weather_when_scoring():
    weather = FakeWeatherService([None, headwind_conditions(4.0)])
    service = WindService(weather)

    profile = await service.get_wind_profile(northbound_points(), START_TIME)

    assert profile["wind_score"] == 4.0


async def test_first_segment_is_queried_at_start_time():
    weather = FakeWeatherService([headwind_conditions(), headwind_conditions()])
    service = WindService(weather)

    await service.get_wind_profile(northbound_points(), START_TIME)

    first_point, first_at = weather.calls[0]
    assert first_at == START_TIME


async def test_segments_include_per_segment_wind_penalty_and_distance():
    weather = FakeWeatherService([headwind_conditions(5.0), headwind_conditions(5.0)])
    service = WindService(weather)

    profile = await service.get_wind_profile(northbound_points(), START_TIME)

    assert len(profile["segments"]) == 2
    for segment in profile["segments"]:
        assert segment["wind_penalty"] == 5.0
        assert segment["distance_km"] > 0
        assert segment["arrival_time"] is not None
