"""WindWayService（改善計画T405、way_id→wind_penalty配信層のオーケストレーション）のテスト。

FakeRegionRepository（test_region_service.py）と同じ流儀で、RoadGraphRepository/
WeatherServiceが持つメソッドのうち本サービスが実際に呼ぶものだけをダックタイピングした
フェイクへ差し替える。Redisはtest_wind_way_penalty_cache.pyと同じFakeRedisパターンで
使う（実Redis不要）。
"""

from datetime import datetime

import pytest

from app.domain.wind import WindCalculator
from app.domain.wind_grid import WindGridPoint
from app.infrastructure import wind_way_penalty_cache
from app.services.route_generator import JST
from app.services.wind_way_service import WindWayService

Z, X, Y = 14, 14551, 6447


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def mget(self, keys):
        return [self.store.get(key) for key in keys]

    def pipeline(self, transaction=False):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._ops = []

    def set(self, key, value, ex=None):
        self._ops.append((key, value))
        return self

    async def execute(self):
        for key, value in self._ops:
            self._redis.store[key] = value


@pytest.fixture(autouse=True)
def use_fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(wind_way_penalty_cache, "get_redis_client", lambda: fake)
    return fake


class FakeBearingRepository:
    """RoadGraphRepositoryのうちget_way_bearings_in_tileだけを実装したフェイク。"""

    def __init__(self, bearings: dict[int, float] | None, error: Exception | None = None):
        self._bearings = bearings
        self._error = error
        self.calls: list[tuple[int, int, int, tuple[int, int, int]]] = []

    async def get_way_bearings_in_tile(self, z, x, y, bbox, coverage_tile):
        self.calls.append((z, x, y, coverage_tile))
        if self._error is not None:
            raise self._error
        return self._bearings


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

    result = await service.get_way_wind_penalties(Z, X, Y, AT)

    assert result == {}


async def test_uncovered_tile_returns_empty_dict_without_calling_weather():
    repository = FakeBearingRepository(bearings=None)
    weather_service = FakeWeatherService(TIMES, make_grid_point(TIMES, [5.0, 5.0, 5.0], [0.0, 0.0, 0.0]))
    service = WindWayService(repository=repository, weather_service=weather_service)

    result = await service.get_way_wind_penalties(Z, X, Y, AT)

    assert result == {}
    assert weather_service.calls == []  # カバレッジ外は風データを取りに行かない


async def test_covered_but_no_ways_returns_empty_dict():
    repository = FakeBearingRepository(bearings={})
    service = WindWayService(repository=repository, weather_service=FakeWeatherService(TIMES, None))

    result = await service.get_way_wind_penalties(Z, X, Y, AT)

    assert result == {}


async def test_computes_wind_penalty_from_bearing_and_wind_grid():
    # way1は真北向き(bearing=0)。9時の風は南寄り10m/s、風向(気象学=吹いてくる方向)=180度
    # →真北へ進むと正面から風を受ける向かい風になり、wind_penalty=speed*cos(180-0)=-10になる
    # はず……ではなく、WindCalculator.wind_penaltyの定義どおりに直接計算して突き合わせる
    # （二重実装を避ける、既存の車ストレス系テストと同じ方針）。
    repository = FakeBearingRepository(bearings={1: 0.0, 2: 90.0})
    wind_speed, wind_direction = 6.0, 200.0
    grid_point = make_grid_point(TIMES, [1.0, wind_speed, 1.0], [10.0, wind_direction, 10.0])
    weather_service = FakeWeatherService(TIMES, grid_point)
    service = WindWayService(repository=repository, weather_service=weather_service)

    result = await service.get_way_wind_penalties(Z, X, Y, AT)

    assert result == {
        1: round(WindCalculator.wind_penalty(wind_speed, wind_direction, 0.0), 2),
        2: round(WindCalculator.wind_penalty(wind_speed, wind_direction, 90.0), 2),
    }
    assert len(weather_service.calls) == 1


async def test_second_call_within_same_hour_bucket_is_served_from_cache():
    repository = FakeBearingRepository(bearings={1: 0.0})
    grid_point = make_grid_point(TIMES, [1.0, 6.0, 1.0], [10.0, 200.0, 10.0])
    weather_service = FakeWeatherService(TIMES, grid_point)
    service = WindWayService(repository=repository, weather_service=weather_service)

    first = await service.get_way_wind_penalties(Z, X, Y, AT)
    second = await service.get_way_wind_penalties(Z, X, Y, AT)

    assert first == second
    # bearing取得（DBクエリ）は都度行うが、風グリッドの再取得はキャッシュヒットのため1回のみ。
    assert len(repository.calls) == 2
    assert len(weather_service.calls) == 1


async def test_partial_cache_only_computes_missing_way_ids():
    grid_point = make_grid_point(TIMES, [1.0, 6.0, 1.0], [10.0, 200.0, 10.0])
    weather_service = FakeWeatherService(TIMES, grid_point)
    service = WindWayService(
        repository=FakeBearingRepository(bearings={1: 0.0}), weather_service=weather_service
    )
    await service.get_way_wind_penalties(Z, X, Y, AT)  # way1をキャッシュへ積む

    # 同じタイルにway2が増えたケース（例: 再取込・別ズームの祖先タイルで新規way判明）。
    service_with_new_way = WindWayService(
        repository=FakeBearingRepository(bearings={1: 0.0, 2: 45.0}), weather_service=weather_service
    )
    result = await service_with_new_way.get_way_wind_penalties(Z, X, Y, AT)

    assert set(result.keys()) == {1, 2}
    assert len(weather_service.calls) == 2  # way2ぶんの不足を補うため再度風グリッドを取得


async def test_wind_grid_unavailable_returns_empty_dict():
    repository = FakeBearingRepository(bearings={1: 0.0})
    weather_service = FakeWeatherService(TIMES, None)
    service = WindWayService(repository=repository, weather_service=weather_service)

    result = await service.get_way_wind_penalties(Z, X, Y, AT)

    assert result == {}


async def test_time_outside_wind_grid_range_returns_empty_dict():
    repository = FakeBearingRepository(bearings={1: 0.0})
    grid_point = make_grid_point(TIMES, [1.0, 6.0, 1.0], [10.0, 200.0, 10.0])
    weather_service = FakeWeatherService(TIMES, grid_point)
    service = WindWayService(repository=repository, weather_service=weather_service)

    far_future = datetime(2027, 1, 1, 0, 0)
    result = await service.get_way_wind_penalties(Z, X, Y, far_future)

    assert result == {}


async def test_repository_error_returns_empty_dict():
    repository = FakeBearingRepository(bearings=None, error=RuntimeError("db down"))
    service = WindWayService(repository=repository, weather_service=FakeWeatherService(TIMES, None))

    result = await service.get_way_wind_penalties(Z, X, Y, AT)

    assert result == {}


async def test_at_none_defaults_to_now_without_raising():
    # WindWayServiceの既定時刻はdatetime.now(JST)（route_generator.pyのJSTと同じ簡易近似、
    # Open-MeteoのhourlyがnaiveなJST文字列を返すことに整合させるため）。テストのwide_timesも
    # 同じ基準（JST）で「今日1日分の全時間帯」を用意し、テスト実行環境のタイムゾーンに
    # 依存せず必ず範囲内に収まるようにする。
    repository = FakeBearingRepository(bearings={1: 0.0})
    now_jst = datetime.now(JST)
    wide_times = [f"{now_jst.year:04d}-{now_jst.month:02d}-{now_jst.day:02d}T{h:02d}:00" for h in range(24)]
    grid_point = make_grid_point(wide_times, [3.0] * 24, [45.0] * 24)
    weather_service = FakeWeatherService(wide_times, grid_point)
    service = WindWayService(repository=repository, weather_service=weather_service)

    result = await service.get_way_wind_penalties(Z, X, Y, None)

    assert set(result.keys()) == {1}
