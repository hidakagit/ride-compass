"""鍵→wind_drag_ratio配信層（`services/wind_way_service.py`）のオーケストレーション。

走行方位は呼び出し側が指定する単一の値で、道路自身の向きは使わない。風グリッドもタイル
中心1点で代表させる。その結果、同じタイル内の全wayが同じ値を持つ。
"""

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.region import tile_bounds_lonlat
from app.domain.route import Coordinates
from app.domain.wind import kmh_to_ms, wind_drag_ratio
from app.domain.wind_grid import WIND_GRID_DETAIL_SPACING_DEG, WindGridPoint, nearest_grid_point
from app.domain.time_zone import JST
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.wind_way_service import WindWayService

Z, X, Y = 14, 14551, 6447
SPEED_KMH = 20.0


class FakeWayIdsRepository:
    """RoadGraphRepositoryのうちget_feature_keys_in_tileだけを実装したフェイク。

    引数は本物の定義へ当てて照合する。フェイクが自前の引数を持つと、本物の引数が変わっても
    呼び出し側の食い違いを通してしまう。
    """

    def __init__(self, way_ids: list[int] | None, error: Exception | None = None):
        self._way_ids = way_ids
        self._error = error
        self.calls: list[tuple] = []

    async def get_feature_keys_in_tile(self, *args, **kwargs):
        inspect.signature(RoadGraphRepository.get_feature_keys_in_tile).bind(self, *args, **kwargs)
        self.calls.append(args)
        if self._error is not None:
            raise self._error
        return self._way_ids


class FakeWeatherService:
    """WeatherServiceのうちget_wind_gridだけを実装したフェイク。"""

    def __init__(self, times: list[str], point: WindGridPoint | None):
        self._times = times
        self._point = point
        self.calls: list[list] = []

    async def get_wind_grid(self, points):
        self.calls.append(points)
        return self._times, [self._point]


def make_grid_point(times: list[str], speeds: list[float], directions: list[float]) -> WindGridPoint:
    return WindGridPoint(
        latitude=35.68,
        longitude=139.75,
        wind_speed_ms=speeds,
        wind_direction_deg=directions,
        precipitation_mm=[0.0] * len(times),
    )


AT = datetime(2026, 8, 30, 9, 0)
TIMES = ["2026-08-30T08:00", "2026-08-30T09:00", "2026-08-30T10:00"]


async def test_repository_none_returns_empty_dict():
    service = WindWayService(repository=None, weather_service=FakeWeatherService([], None))

    result = await service.get_way_values(Z, X, Y, AT, 0.0, SPEED_KMH)

    assert result == {}


# 型が`float | None`なのは呼び出し口の形を揃えるためで、Noneのまま計算へ進ませない。
async def test_bearing_deg_none_raises_value_error():
    service = WindWayService(repository=None, weather_service=FakeWeatherService([], None))

    with pytest.raises(ValueError, match="bearing_deg"):
        await service.get_way_values(Z, X, Y, AT, None, SPEED_KMH)


async def test_speed_kmh_none_raises_value_error():
    service = WindWayService(repository=None, weather_service=FakeWeatherService([], None))

    with pytest.raises(ValueError, match="speed_kmh"):
        await service.get_way_values(Z, X, Y, AT, 0.0)


async def test_uncovered_tile_returns_empty_dict_without_calling_weather():
    repository = FakeWayIdsRepository(way_ids=None)
    weather_service = FakeWeatherService(TIMES, make_grid_point(TIMES, [5.0, 5.0, 5.0], [0.0, 0.0, 0.0]))
    service = WindWayService(repository=repository, weather_service=weather_service)

    result = await service.get_way_values(Z, X, Y, AT, 0.0, SPEED_KMH)

    assert result == {}
    assert weather_service.calls == []  # カバレッジ外は風データを取りに行かない


async def test_covered_but_no_ways_returns_empty_dict():
    repository = FakeWayIdsRepository(way_ids=[])
    service = WindWayService(repository=repository, weather_service=FakeWeatherService(TIMES, None))

    result = await service.get_way_values(Z, X, Y, AT, 0.0, SPEED_KMH)

    assert result == {}


async def test_computes_wind_drag_ratio_from_bearing_speed_and_wind_grid():
    # 走行方位は全道路共通のため、同じタイル内の2本は同じ値になる。
    repository = FakeWayIdsRepository(way_ids=[1, 2])
    wind_speed, wind_direction = 6.0, 200.0
    bearing_deg = 45.0
    grid_point = make_grid_point(TIMES, [1.0, wind_speed, 1.0], [10.0, wind_direction, 10.0])
    weather_service = FakeWeatherService(TIMES, grid_point)
    service = WindWayService(repository=repository, weather_service=weather_service)

    result = await service.get_way_values(Z, X, Y, AT, bearing_deg, SPEED_KMH)

    expected = round(wind_drag_ratio(wind_speed, wind_direction, bearing_deg, kmh_to_ms(SPEED_KMH)), 3)
    assert result == {1: expected, 2: expected}
    assert len(weather_service.calls) == 1


def _tile_center(z: int, x: int, y: int) -> Coordinates:
    bbox = tile_bounds_lonlat(z, x, y)
    return Coordinates(
        latitude=(bbox.min_latitude + bbox.max_latitude) / 2,
        longitude=(bbox.min_longitude + bbox.max_longitude) / 2,
    )


async def test_grid_point_uses_wind_grid_detail_spacing_not_the_coarse_default():
    repository = FakeWayIdsRepository(way_ids=[1])
    grid_point = make_grid_point(TIMES, [1.0, 6.0, 1.0], [10.0, 200.0, 10.0])
    weather_service = FakeWeatherService(TIMES, grid_point)
    service = WindWayService(repository=repository, weather_service=weather_service)

    await service.get_way_values(Z, X, Y, AT, 0.0, SPEED_KMH)

    expected_point = nearest_grid_point(_tile_center(Z, X, Y), spacing_deg=WIND_GRID_DETAIL_SPACING_DEG)
    assert weather_service.calls[0] == [expected_point]


async def test_adjacent_tiles_resolve_to_different_grid_points():
    # 格子間隔がタイル幅より広いと、隣り合うタイルが同じ格子点へ丸められて同じ色になる。
    grid_point = make_grid_point(TIMES, [1.0, 6.0, 1.0], [10.0, 200.0, 10.0])

    repository_a = FakeWayIdsRepository(way_ids=[1])
    weather_service_a = FakeWeatherService(TIMES, grid_point)
    service_a = WindWayService(repository=repository_a, weather_service=weather_service_a)
    await service_a.get_way_values(Z, X, Y, AT, 0.0, SPEED_KMH)

    repository_b = FakeWayIdsRepository(way_ids=[1])
    weather_service_b = FakeWeatherService(TIMES, grid_point)
    service_b = WindWayService(repository=repository_b, weather_service=weather_service_b)
    await service_b.get_way_values(Z, X + 1, Y, AT, 0.0, SPEED_KMH)

    assert weather_service_a.calls[0] != weather_service_b.calls[0]


async def test_second_call_recomputes_without_caching():
    repository = FakeWayIdsRepository(way_ids=[1])
    grid_point = make_grid_point(TIMES, [1.0, 6.0, 1.0], [10.0, 200.0, 10.0])
    weather_service = FakeWeatherService(TIMES, grid_point)
    service = WindWayService(repository=repository, weather_service=weather_service)

    first = await service.get_way_values(Z, X, Y, AT, 0.0, SPEED_KMH)
    second = await service.get_way_values(Z, X, Y, AT, 0.0, SPEED_KMH)

    assert first == second
    # 風の値はキャッシュせず、同じ条件でも都度計算する。
    assert len(repository.calls) == 2
    assert len(weather_service.calls) == 2


async def test_different_bearing_changes_the_value():
    repository = FakeWayIdsRepository(way_ids=[1])
    grid_point = make_grid_point(TIMES, [1.0, 6.0, 1.0], [10.0, 200.0, 10.0])
    weather_service = FakeWeatherService(TIMES, grid_point)
    service = WindWayService(repository=repository, weather_service=weather_service)

    first = await service.get_way_values(Z, X, Y, AT, 0.0, SPEED_KMH)
    second = await service.get_way_values(Z, X, Y, AT, 90.0, SPEED_KMH)

    assert first != second
    assert len(weather_service.calls) == 2


async def test_different_speed_changes_the_value():
    repository = FakeWayIdsRepository(way_ids=[1, 2])
    wind_speed, wind_direction, bearing_deg = 6.0, 200.0, 45.0
    grid_point = make_grid_point(TIMES, [1.0, wind_speed, 1.0], [10.0, wind_direction, 10.0])
    service = WindWayService(repository=repository, weather_service=FakeWeatherService(TIMES, grid_point))

    slow = await service.get_way_values(Z, X, Y, AT, bearing_deg, 15.0)
    fast = await service.get_way_values(Z, X, Y, AT, bearing_deg, 35.0)

    def expected(speed_kmh: float) -> float:
        return round(wind_drag_ratio(wind_speed, wind_direction, bearing_deg, kmh_to_ms(speed_kmh)), 3)

    assert slow == {1: expected(15.0), 2: expected(15.0)}
    assert fast == {1: expected(35.0), 2: expected(35.0)}
    assert slow[1] != fast[1]


async def test_wind_grid_unavailable_returns_empty_dict():
    repository = FakeWayIdsRepository(way_ids=[1])
    weather_service = FakeWeatherService(TIMES, None)
    service = WindWayService(repository=repository, weather_service=weather_service)

    result = await service.get_way_values(Z, X, Y, AT, 0.0, SPEED_KMH)

    assert result == {}


async def test_time_outside_wind_grid_range_returns_empty_dict():
    repository = FakeWayIdsRepository(way_ids=[1])
    grid_point = make_grid_point(TIMES, [1.0, 6.0, 1.0], [10.0, 200.0, 10.0])
    weather_service = FakeWeatherService(TIMES, grid_point)
    service = WindWayService(repository=repository, weather_service=weather_service)

    far_future = datetime(2027, 1, 1, 0, 0)
    result = await service.get_way_values(Z, X, Y, far_future, 0.0, SPEED_KMH)

    assert result == {}


async def test_repository_error_returns_empty_dict():
    repository = FakeWayIdsRepository(way_ids=None, error=ConnectionRefusedError("db down"))
    service = WindWayService(repository=repository, weather_service=FakeWeatherService(TIMES, None))

    result = await service.get_way_values(Z, X, Y, AT, 0.0, SPEED_KMH)

    assert result == {}


async def test_an_implementation_error_is_not_turned_into_an_empty_result():
    """DB障害でない例外まで空へ倒すと、利用者には「データなし」に見えて誰も気づかない。"""
    repository = FakeWayIdsRepository(way_ids=None, error=TypeError("wrong arguments"))
    service = WindWayService(repository=repository, weather_service=FakeWeatherService(TIMES, None))

    with pytest.raises(TypeError):
        await service.get_way_values(Z, X, Y, AT, 0.0, SPEED_KMH)


async def test_at_none_defaults_to_now_without_raising():
    # 既定時刻は「今」のため、時刻配列は翌日00:00まで張る。今日の23:00までだと、
    # 23時台に実行したとき範囲外になって落ちる。
    repository = FakeWayIdsRepository(way_ids=[1])
    today_jst = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0)
    wide_times = [(today_jst + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(25)]
    grid_point = make_grid_point(wide_times, [3.0] * 25, [45.0] * 25)
    weather_service = FakeWeatherService(wide_times, grid_point)
    service = WindWayService(repository=repository, weather_service=weather_service)

    result = await service.get_way_values(Z, X, Y, None, 0.0, SPEED_KMH)

    assert set(result.keys()) == {1}


async def test_utc_aware_at_is_converted_to_jst_before_range_check():
    # 呼び出し側はtz-awareなUTCを送りうる。風グリッドの時刻配列はJST基準の壁時計時刻
    # （tzなし文字列）のため、tzinfoを剥がすだけで比べると時差ぶんズレ、JST深夜〜早朝が
    # 前日扱いになって誤って範囲外と判定される。
    repository = FakeWayIdsRepository(way_ids=[1])
    today_jst = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0)
    wide_times = [(today_jst + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(24)]
    grid_point = make_grid_point(wide_times, [3.0] * 24, [45.0] * 24)
    weather_service = FakeWeatherService(wide_times, grid_point)
    service = WindWayService(repository=repository, weather_service=weather_service)

    # JST今日00:30を、tz-awareなUTCとして表現する。
    target_utc = today_jst.replace(hour=0, minute=30).astimezone(timezone.utc)

    result = await service.get_way_values(Z, X, Y, target_utc, 0.0, SPEED_KMH)

    assert set(result.keys()) == {1}
