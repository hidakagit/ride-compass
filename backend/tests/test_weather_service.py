"""天候サービス（services/weather_service.py）のテスト。値はすべてMSMから読む。"""

from datetime import datetime

import numpy as np
import pytest

from app.domain.route import Coordinates
from app.domain.weather import derive_weather_code
from app.infrastructure import msm_client
from app.infrastructure.msm_client import MsmUnavailableError
from app.services.weather_service import WeatherService

POINT = Coordinates(latitude=35.7597, longitude=139.7387)
OTHER_POINT = Coordinates(latitude=35.1, longitude=139.1)


def _series(times, *, u=None, v=None, precipitation=None, temperature=None, cloud_cover=None):
    """MSMの読み出し結果（[地点数, 時刻数]）を1地点ぶん組み立てる。省略した変数は既定値で埋める。"""
    n = len(times)

    def column(values, default):
        return np.array([values if values is not None else [default] * n], dtype=float)

    return times, {
        "wind_u_component_10m": column(u, 0.0),
        "wind_v_component_10m": column(v, 0.0),
        "precipitation": column(precipitation, 0.0),
        "temperature_2m": column(temperature, 20.0),
        "cloud_cover": column(cloud_cover, 0.0),
    }


def _patch_read_series(monkeypatch, result):
    async def read_series(latitudes, longitudes, hours=None):
        times, values = result
        count = len(latitudes)
        return times, {key: np.tile(value[0], (count, 1)) for key, value in values.items()}

    monkeypatch.setattr(msm_client, "read_series", read_series)


def _patch_unavailable(monkeypatch):
    async def unavailable(latitudes, longitudes, hours=None):
        raise MsmUnavailableError("未同期")

    monkeypatch.setattr(msm_client, "read_series", unavailable)


async def test_get_conditions_reports_the_first_hour_as_current(monkeypatch):
    _patch_read_series(
        monkeypatch,
        _series(
            ["2026-09-07T13:00", "2026-09-07T14:00"],
            u=[3.0, 0.0],
            v=[0.0, 0.0],
            temperature=[24.6, 25.0],
            precipitation=[0.2, 0.0],
            cloud_cover=[90.0, 10.0],
        ),
    )

    conditions = await WeatherService().get_conditions(POINT)

    assert conditions.observed_at == "2026-09-07T13:00"
    assert conditions.temperature_c == 24.6
    assert conditions.wind_speed_ms == 3.0
    # 東西成分だけの風（u=3）は西から吹くため270度。
    assert conditions.wind_direction_deg == 270.0
    assert conditions.wind_direction_label == "西"
    assert conditions.precipitation_mm == 0.2
    # 降水0.2mm/hは弱い雨（61）。
    assert conditions.weather_code == 61


async def test_get_conditions_aggregates_today_only(monkeypatch):
    """日次の集計は同じJST暦日ぶんに限る（翌日の値を今日の最高気温に混ぜない）。"""
    _patch_read_series(
        monkeypatch,
        _series(
            ["2026-09-07T22:00", "2026-09-07T23:00", "2026-09-08T00:00"],
            temperature=[25.0, 23.0, 35.0],
            precipitation=[0.0, 1.5, 9.9],
            u=[1.0, 4.0, 20.0],
        ),
    )

    conditions = await WeatherService().get_conditions(POINT)

    assert conditions.temperature_max_c == 25.0
    assert conditions.temperature_min_c == 23.0
    assert conditions.precipitation_max_mm == 1.5
    assert conditions.wind_speed_max_ms == 4.0


async def test_get_conditions_builds_two_hourly_periods(monkeypatch):
    times = [f"2026-09-07T{hour:02d}:00" for hour in range(6, 22)]
    _patch_read_series(monkeypatch, _series(times, temperature=[20.0 + i for i in range(len(times))]))

    conditions = await WeatherService().get_conditions(POINT)

    assert [p.period for p in conditions.today_periods] == [
        "06:00",
        "08:00",
        "10:00",
        "12:00",
        "14:00",
        "16:00",
        "18:00",
        "20:00",
    ]
    assert conditions.today_periods[1].temperature_c == 22.0


async def test_get_conditions_truncates_periods_at_the_end_of_the_forecast(monkeypatch):
    """予報の終端に達したらコマ数は8未満になる（runによって予報の長さが変わるため）。"""
    _patch_read_series(monkeypatch, _series(["2026-09-07T13:00", "2026-09-07T14:00", "2026-09-07T15:00"]))

    conditions = await WeatherService().get_conditions(POINT)

    assert [p.period for p in conditions.today_periods] == ["13:00", "15:00"]


async def test_get_conditions_computes_sunrise_and_sunset_locally(monkeypatch):
    """日の出・日没は外部に問い合わせず天文計算（domain/twilight.py）で埋める。"""
    _patch_read_series(monkeypatch, _series(["2026-09-07T13:00"]))

    conditions = await WeatherService().get_conditions(POINT)

    assert conditions.sunrise.startswith("2026-09-07T0")
    assert conditions.sunset.startswith("2026-09-07T1")
    assert conditions.is_day == 1


async def test_get_conditions_returns_none_when_msm_unavailable(monkeypatch):
    _patch_unavailable(monkeypatch)

    assert await WeatherService().get_conditions(POINT) is None


async def test_get_wind_grid_builds_speed_and_direction_from_msm(monkeypatch):
    # 北風（v=-1, u=0）は「北から吹いてくる」ため風向0度、風速1.0 m/s になる。
    _patch_read_series(monkeypatch, _series(["2026-09-07T13:00"], u=[0.0], v=[-1.0], precipitation=[0.4]))

    times, results = await WeatherService().get_wind_grid([POINT, OTHER_POINT])

    assert times == ["2026-09-07T13:00"]
    assert len(results) == 2
    assert results[0].latitude == POINT.latitude
    assert results[0].longitude == POINT.longitude
    assert results[0].wind_speed_ms == [1.0]
    assert results[0].wind_direction_deg == [0.0]
    assert results[0].precipitation_mm == [0.4]


async def test_get_wind_grid_returns_all_none_when_msm_unavailable(monkeypatch):
    _patch_unavailable(monkeypatch)

    times, results = await WeatherService().get_wind_grid([POINT, OTHER_POINT])

    assert times == []
    assert results == [None, None]


async def test_get_wind_grid_returns_empty_for_empty_points():
    assert await WeatherService().get_wind_grid([]) == ([], [])


async def test_get_wind_forecast_series_reads_msm(monkeypatch):
    _patch_read_series(monkeypatch, _series(["2026-09-07T13:00", "2026-09-07T14:00"], u=[3.0, 0.0], v=[0.0, 4.0]))

    series = await WeatherService().get_wind_forecast_series(POINT)

    assert series.times == [datetime(2026, 9, 7, 13, 0), datetime(2026, 9, 7, 14, 0)]
    # 西風（u=3）は270度、北向きに吹く風（v=4）は南から＝180度。
    assert series.speed_ms.tolist() == [3.0, 4.0]
    assert series.direction_deg.tolist() == [270.0, 180.0]


async def test_get_wind_forecast_series_returns_none_when_msm_unavailable(monkeypatch):
    _patch_unavailable(monkeypatch)

    assert await WeatherService().get_wind_forecast_series(POINT) is None


@pytest.mark.parametrize(
    ("precipitation", "cloud_cover", "temperature", "expected"),
    [
        (0.0, 5.0, 20.0, 0),  # 快晴
        (0.0, 30.0, 20.0, 1),
        (0.0, 70.0, 20.0, 2),
        (0.0, 95.0, 20.0, 3),  # 曇天
        (0.05, 95.0, 20.0, 3),  # 微量の降水は雨扱いにしない
        (0.5, 95.0, 20.0, 61),  # 弱い雨
        (2.0, 95.0, 20.0, 63),
        (10.0, 95.0, 20.0, 65),  # 強い雨
        (0.5, 95.0, -1.0, 71),  # 氷点下は雪
        (10.0, 95.0, -5.0, 75),
    ],
)
def test_derive_weather_code(precipitation, cloud_cover, temperature, expected):
    assert derive_weather_code(precipitation, cloud_cover, temperature) == expected


def test_derive_weather_code_returns_none_without_cloud_cover():
    assert derive_weather_code(0.0, None, 20.0) is None
