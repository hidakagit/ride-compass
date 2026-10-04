"""天候サービス（services/weather_service.py）のテスト。値はすべてMSMから読む。"""

from datetime import datetime

import numpy as np
import pytest

from app.domain.region import BoundingBox
from app.domain.route import Coordinates
from app.domain.weather import TemperatureRange, derive_observed_weather_code
from app.domain.weather_display import WEATHER_CATEGORIES
from app.infrastructure import msm_client
from app.infrastructure.msm_client import MsmSeries, MsmUnavailableError
from app.services.weather_service import WeatherService

POINT = Coordinates(latitude=35.7597, longitude=139.7387)
OTHER_POINT = Coordinates(latitude=35.1, longitude=139.1)


def _series(times, *, u=None, v=None, precipitation=None, temperature=None, count=1):
    """MSMの読み出し結果を、`count`地点とも同じ値で組み立てる。省略した変数は既定値で埋める。"""
    n = len(times)

    def column(values, default):
        return np.tile(np.array(values if values is not None else [default] * n, dtype=float), (count, 1))

    return MsmSeries(
        times=times,
        wind_u_ms=column(u, 0.0),
        wind_v_ms=column(v, 0.0),
        precipitation_mm=column(precipitation, 0.0),
        temperature_c=column(temperature, 20.0),
    )


def _patch_read_series(monkeypatch, **values):
    async def read_series(latitudes, longitudes):
        return _series(**values, count=len(latitudes))

    monkeypatch.setattr(msm_client, "read_series", read_series)


def _patch_unavailable(monkeypatch):
    async def unavailable(latitudes, longitudes):
        raise MsmUnavailableError("未同期")

    monkeypatch.setattr(msm_client, "read_series", unavailable)


async def test_get_conditions_reports_the_first_hour_as_current(monkeypatch):
    _patch_read_series(
        monkeypatch,
        times=["2026-09-07T13:00", "2026-09-07T14:00"],
        u=[3.0, 0.0],
        v=[0.0, 0.0],
        temperature=[24.6, 25.0],
        precipitation=[0.2, 0.0],
    )

    conditions = await WeatherService().get_conditions(POINT)

    assert conditions.observed_at == "2026-09-07T13:00"
    assert conditions.temperature_c == 24.6
    assert conditions.wind_speed_ms == 3.0
    # 東西成分だけの風（u=3）は西から吹くため270度。
    assert conditions.wind_direction_deg == 270.0
    assert conditions.wind_direction_label == "西"
    assert conditions.precipitation_mm == 0.2


async def test_get_conditions_aggregates_today_only(monkeypatch):
    """日次の集計は同じJST暦日ぶんに限る（翌日の値を今日の最高気温に混ぜない）。"""
    _patch_read_series(
        monkeypatch,
        times=["2026-09-07T22:00", "2026-09-07T23:00", "2026-09-08T00:00"],
        temperature=[25.0, 23.0, 35.0],
        precipitation=[0.0, 1.5, 9.9],
        u=[1.0, 4.0, 20.0],
    )

    conditions = await WeatherService().get_conditions(POINT)

    assert conditions.temperature_range == TemperatureRange(min_c=23.0, max_c=25.0)
    assert conditions.precipitation_max_mm == 1.5
    assert conditions.wind_speed_max_ms == 4.0


async def test_a_missing_hour_leaves_the_temperature_range_out(monkeypatch):
    """格子の欠損（NaN）を含む日の範囲は、片方だけでなく丸ごと無い（応答でnullが混ざった範囲を配らない）。"""
    _patch_read_series(monkeypatch, times=["2026-09-07T13:00", "2026-09-07T14:00"], temperature=[24.0, float("nan")])

    conditions = await WeatherService().get_conditions(POINT)

    assert conditions.temperature_range is None


async def test_get_conditions_builds_two_hourly_periods(monkeypatch):
    times = [f"2026-09-07T{hour:02d}:00" for hour in range(6, 22)]
    _patch_read_series(monkeypatch, times=times, temperature=[20.0 + i for i in range(len(times))])

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
    # 画面はこの間隔をコマの並びの見出しに出す。並びの実際の間隔と食い違わない。
    assert conditions.today_period_interval_hours == 2


async def test_get_conditions_truncates_periods_at_the_end_of_the_forecast(monkeypatch):
    """予報の終端に達したらコマ数は8未満になる（runによって予報の長さが変わるため）。"""
    _patch_read_series(monkeypatch, times=["2026-09-07T13:00", "2026-09-07T14:00", "2026-09-07T15:00"])

    conditions = await WeatherService().get_conditions(POINT)

    assert [p.period for p in conditions.today_periods] == ["13:00", "15:00"]


async def test_get_conditions_computes_sunrise_and_sunset_locally(monkeypatch):
    """日の出・日没は外部に問い合わせず天文計算（domain/twilight.py）で埋める。"""
    _patch_read_series(monkeypatch, times=["2026-09-07T13:00"])

    conditions = await WeatherService().get_conditions(POINT)

    assert conditions.twilight is not None
    assert conditions.twilight.sunrise.startswith("2026-09-07T0")
    assert conditions.twilight.sunset.startswith("2026-09-07T1")


async def test_get_conditions_returns_none_when_msm_unavailable(monkeypatch):
    _patch_unavailable(monkeypatch)

    assert await WeatherService().get_conditions(POINT) is None


async def test_get_wind_grid_builds_speed_and_direction_from_msm(monkeypatch):
    # 北風（v=-1, u=0）は「北から吹いてくる」ため風向0度、風速1.0 m/s になる。
    _patch_read_series(monkeypatch, times=["2026-09-07T13:00"], u=[0.0], v=[-1.0], precipitation=[0.4])

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


ROUTE_BBOX = BoundingBox(min_latitude=35.0, min_longitude=139.0, max_latitude=35.12, max_longitude=139.1)


async def test_get_wind_forecast_lattice_reads_msm_at_every_grid_point_of_the_area(monkeypatch):
    asked = []

    async def read_series(latitudes, longitudes):
        asked.append((np.asarray(latitudes), np.asarray(longitudes)))
        return _series(["2026-09-07T13:00", "2026-09-07T14:00"], u=[3.0, 0.0], v=[0.0, 4.0], count=len(latitudes))

    monkeypatch.setattr(msm_client, "read_series", read_series)

    series = await WeatherService().get_wind_forecast_lattice(ROUTE_BBOX)

    assert series.times == [datetime(2026, 9, 7, 13, 0), datetime(2026, 9, 7, 14, 0)]
    latitudes, longitudes = asked[0]
    assert len(latitudes) == series.lattice.rows * series.lattice.cols
    assert latitudes.min() <= 35.0 and latitudes.max() >= 35.12
    assert longitudes.min() <= 139.0 and longitudes.max() >= 139.1
    # 西風（u=3）は270度、北向きに吹く風（v=4）は南から＝180度。
    assert series.speed_ms[0].tolist() == [3.0, 4.0]
    assert series.direction_deg[0].tolist() == [270.0, 180.0]


async def test_get_wind_forecast_lattice_returns_none_when_msm_unavailable(monkeypatch):
    _patch_unavailable(monkeypatch)

    assert await WeatherService().get_wind_forecast_lattice(ROUTE_BBOX) is None


@pytest.mark.parametrize(
    ("precipitation_10min", "sunshine_10min", "temperature", "expected"),
    [
        (0.0, 10.0, 20.0, 0),  # 降水なし・日が差している
        (0.0, 0.0, 20.0, 3),  # 降水なし・日照なし
        (None, 0.0, 20.0, 3),
        (0.1, 10.0, 20.0, 61),  # 10分0.1mm＝1時間0.6mm相当は弱い雨。日照より降水を先に見る
        (0.5, 10.0, 20.0, 63),  # 1時間3mm相当
        (1.0, None, 20.0, 65),  # 1時間6mm相当は強い雨
        (0.5, None, 0.0, 73),  # 0℃以下は雪
        (0.5, None, 0.1, 63),
        (0.5, None, None, 63),  # 気温が欠測なら雨
        (0.0, None, 20.0, None),  # 降水なしで日照が欠測なら判定材料が無い
        (None, None, 20.0, None),
    ],
)
def test_derive_observed_weather_code(precipitation_10min, sunshine_10min, temperature, expected):
    assert derive_observed_weather_code(precipitation_10min, sunshine_10min, temperature) == expected


def test_weather_categories_hold_exactly_the_derived_codes():
    """画面は分類に無いコードを出さないので、導くコードはどれも分類に入る。導かないコードと、導くコードを1つも
    持たない分類は、画面に通らないアイコンを残すので置かない。入力は降水量の全ての強さの帯・日照の
    有無・気温の雨と雪の両側を掃く。"""
    precipitations = [None, *(step / 100 for step in range(201))]
    derived = {
        derive_observed_weather_code(precipitation, sunshine, temperature)
        for precipitation in precipitations
        for sunshine in (None, 0.0, 5.0, 10.0)
        for temperature in (None, -5.0, 0.0, 0.1, 20.0)
    } - {None}
    categorized = {code for category in WEATHER_CATEGORIES for code in category.codes}
    assert derived
    assert derived <= categorized, sorted(derived - categorized)
    assert categorized <= derived, sorted(categorized - derived)
    assert all(category.codes for category in WEATHER_CATEGORIES)
