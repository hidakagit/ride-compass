"""WindWayService（改善計画T405→T414で作り直し、way_id→wind_penalty配信層の
オーケストレーション）のテスト。

FakeRegionRepository（test_region_service.py）と同じ流儀で、RoadGraphRepository/
WeatherServiceが持つメソッドのうち本サービスが実際に呼ぶものだけをダックタイピングした
フェイクへ差し替える。Redisはtest_dynamic_way_value_cache.pyと同じFakeRedisパターンで
使う（実Redis不要）。

T414での設計変更: 走行方位（bearing_deg）は道路自身の向きではなく、呼び出し側
（コンパススライダー）が指定する引数になった。同じタイル内の全wayは常に同じ
wind_penaltyを持つ（風グリッドをタイル中心1点で代表させる既存の近似＋向きが全道路共通の
ため）。
"""

from datetime import datetime, timedelta

import pytest

from app.domain.wind import headwind_component_ms
from app.domain.wind_grid import WindGridPoint
from app.infrastructure import dynamic_way_value_cache
from app.services.route_generator import JST
from app.services.wind_way_service import WindWayService

Z, X, Y = 14, 14551, 6447


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


@pytest.fixture(autouse=True)
def use_fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(dynamic_way_value_cache, "get_redis_client_or_none", lambda: fake)
    return fake


class FakeWayIdsRepository:
    """RoadGraphRepositoryのうちget_way_ids_in_tileだけを実装したフェイク。"""

    def __init__(self, way_ids: list[int] | None, error: Exception | None = None):
        self._way_ids = way_ids
        self._error = error
        self.calls: list[tuple[int, int, int, tuple[int, int, int]]] = []

    async def get_way_ids_in_tile(self, z, x, y, bbox, coverage_tile):
        self.calls.append((z, x, y, coverage_tile))
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

    result = await service.get_way_values(Z, X, Y, AT, 0.0)

    assert result == {}


# 改善計画T445: bearing_deg=Noneで呼ばれたら即座に失敗する（router側422検証をすり抜けて
# 呼ばれた場合の防御。router/service間の型シグネチャをfloat | Noneへ揃えた副作用として、
# 型チェッカーが通してしまうNone到達を実行時ガードで塞ぐ）。
async def test_bearing_deg_none_raises_value_error():
    service = WindWayService(repository=None, weather_service=FakeWeatherService([], None))

    with pytest.raises(ValueError, match="bearing_deg"):
        await service.get_way_values(Z, X, Y, AT, None)


async def test_uncovered_tile_returns_empty_dict_without_calling_weather():
    repository = FakeWayIdsRepository(way_ids=None)
    weather_service = FakeWeatherService(TIMES, make_grid_point(TIMES, [5.0, 5.0, 5.0], [0.0, 0.0, 0.0]))
    service = WindWayService(repository=repository, weather_service=weather_service)

    result = await service.get_way_values(Z, X, Y, AT, 0.0)

    assert result == {}
    assert weather_service.calls == []  # カバレッジ外は風データを取りに行かない


async def test_covered_but_no_ways_returns_empty_dict():
    repository = FakeWayIdsRepository(way_ids=[])
    service = WindWayService(repository=repository, weather_service=FakeWeatherService(TIMES, None))

    result = await service.get_way_values(Z, X, Y, AT, 0.0)

    assert result == {}


async def test_computes_wind_penalty_from_bearing_and_wind_grid():
    # T414: 走行方位はユーザー指定の単一の値（全道路共通）。同じタイル内のway1・way2は
    # 常に同じwind_penalty（進行方向に平行な風成分、headwind_component_msの定義どおりに
    # 直接計算して突き合わせる、二重実装を避ける既存の車ストレス系テストと同じ方針）を持つ。
    repository = FakeWayIdsRepository(way_ids=[1, 2])
    wind_speed, wind_direction = 6.0, 200.0
    bearing_deg = 45.0
    grid_point = make_grid_point(TIMES, [1.0, wind_speed, 1.0], [10.0, wind_direction, 10.0])
    weather_service = FakeWeatherService(TIMES, grid_point)
    service = WindWayService(repository=repository, weather_service=weather_service)

    result = await service.get_way_values(Z, X, Y, AT, bearing_deg)

    expected = round(float(headwind_component_ms(wind_speed, wind_direction, bearing_deg)), 2)
    assert service.material_id == "wind_penalty"
    assert result == {1: expected, 2: expected}
    assert len(weather_service.calls) == 1


async def test_second_call_with_same_bearing_bucket_is_served_from_cache():
    repository = FakeWayIdsRepository(way_ids=[1])
    grid_point = make_grid_point(TIMES, [1.0, 6.0, 1.0], [10.0, 200.0, 10.0])
    weather_service = FakeWeatherService(TIMES, grid_point)
    service = WindWayService(repository=repository, weather_service=weather_service)

    first = await service.get_way_values(Z, X, Y, AT, 0.0)
    second = await service.get_way_values(Z, X, Y, AT, 0.0)

    assert first == second
    # way_id一覧の取得（DBクエリ）は都度行うが、風グリッドの再取得はキャッシュヒットのため1回のみ。
    assert len(repository.calls) == 2
    assert len(weather_service.calls) == 1


async def test_different_bearing_bucket_recomputes():
    repository = FakeWayIdsRepository(way_ids=[1])
    grid_point = make_grid_point(TIMES, [1.0, 6.0, 1.0], [10.0, 200.0, 10.0])
    weather_service = FakeWeatherService(TIMES, grid_point)
    service = WindWayService(repository=repository, weather_service=weather_service)

    first = await service.get_way_values(Z, X, Y, AT, 0.0)
    second = await service.get_way_values(Z, X, Y, AT, 90.0)

    assert first != second
    assert len(weather_service.calls) == 2


async def test_wind_grid_unavailable_returns_empty_dict():
    repository = FakeWayIdsRepository(way_ids=[1])
    weather_service = FakeWeatherService(TIMES, None)
    service = WindWayService(repository=repository, weather_service=weather_service)

    result = await service.get_way_values(Z, X, Y, AT, 0.0)

    assert result == {}


async def test_time_outside_wind_grid_range_returns_empty_dict():
    repository = FakeWayIdsRepository(way_ids=[1])
    grid_point = make_grid_point(TIMES, [1.0, 6.0, 1.0], [10.0, 200.0, 10.0])
    weather_service = FakeWeatherService(TIMES, grid_point)
    service = WindWayService(repository=repository, weather_service=weather_service)

    far_future = datetime(2027, 1, 1, 0, 0)
    result = await service.get_way_values(Z, X, Y, far_future, 0.0)

    assert result == {}


async def test_repository_error_returns_empty_dict():
    repository = FakeWayIdsRepository(way_ids=None, error=RuntimeError("db down"))
    service = WindWayService(repository=repository, weather_service=FakeWeatherService(TIMES, None))

    result = await service.get_way_values(Z, X, Y, AT, 0.0)

    assert result == {}


async def test_at_none_defaults_to_now_without_raising():
    # WindWayServiceの既定時刻はdatetime.now(JST)（route_generator.pyのJSTと同じ簡易近似、
    # Open-MeteoのhourlyがnaiveなJST文字列を返すことに整合させるため）。テストのwide_timesも
    # 同じ基準（JST）で「今日00:00〜翌日00:00」を用意し、テスト実行環境のタイムゾーンや
    # 実行時刻（23時台を含む）に依存せず必ず範囲内に収まるようにする（_nearest_time_indexは
    # 配列の最終時刻を超えると範囲外扱いにするため、今日の23:00までだと23時台に外れる）。
    repository = FakeWayIdsRepository(way_ids=[1])
    today_jst = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0)
    wide_times = [(today_jst + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(25)]
    grid_point = make_grid_point(wide_times, [3.0] * 25, [45.0] * 25)
    weather_service = FakeWeatherService(wide_times, grid_point)
    service = WindWayService(repository=repository, weather_service=weather_service)

    result = await service.get_way_values(Z, X, Y, None, 0.0)

    assert set(result.keys()) == {1}
