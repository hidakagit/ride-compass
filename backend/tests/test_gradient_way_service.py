"""GradientWayService（改善計画T423、way_id→勾配配信層のオーケストレーション）のテスト。
test_wind_way_service.pyと同じ流儀（FakeRepository・FakeRedis、実DB/Redis不要）。
"""

import pytest

from app.domain.gradient import GradientCalculator
from app.infrastructure import dynamic_way_value_cache
from app.services.gradient_way_service import GradientWayService

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
    monkeypatch.setattr(dynamic_way_value_cache, "get_redis_client", lambda: fake)
    return fake


class FakeGradientInputsRepository:
    """RoadGraphRepositoryのうちget_way_gradient_inputs_in_tileだけを実装したフェイク。"""

    def __init__(self, inputs: dict[int, tuple[float, float]] | None, error: Exception | None = None):
        self._inputs = inputs
        self._error = error
        self.calls: list[tuple[int, int, int, tuple[int, int, int]]] = []

    async def get_way_gradient_inputs_in_tile(self, z, x, y, bbox, coverage_tile):
        self.calls.append((z, x, y, coverage_tile))
        if self._error is not None:
            raise self._error
        return self._inputs


async def test_repository_none_returns_empty_dict():
    service = GradientWayService(repository=None)

    result = await service.get_way_values(Z, X, Y, None, 0.0)

    assert result == {}


async def test_uncovered_tile_returns_empty_dict():
    repository = FakeGradientInputsRepository(inputs=None)
    service = GradientWayService(repository=repository)

    result = await service.get_way_values(Z, X, Y, None, 0.0)

    assert result == {}


async def test_covered_but_no_inputs_returns_empty_dict():
    repository = FakeGradientInputsRepository(inputs={})
    service = GradientWayService(repository=repository)

    result = await service.get_way_values(Z, X, Y, None, 0.0)

    assert result == {}


async def test_computes_effective_gradient_per_way():
    # way1・way2は道路自身の勾配・向きが異なるため、同じ走行方位でも異なる値になる
    # （wind_way_serviceと違いbroadcastしない、モジュールdocstring参照）。
    inputs = {1: (5.0, 90.0), 2: (-3.0, 0.0)}
    repository = FakeGradientInputsRepository(inputs=inputs)
    service = GradientWayService(repository=repository)
    bearing_deg = 90.0

    result = await service.get_way_values(Z, X, Y, None, bearing_deg)

    expected_1 = round(GradientCalculator.effective_gradient(5.0, 90.0, bearing_deg), 1)
    expected_2 = round(GradientCalculator.effective_gradient(-3.0, 0.0, bearing_deg), 1)
    assert result == {1: expected_1, 2: expected_2}


async def test_second_call_with_same_bearing_bucket_is_served_from_cache():
    repository = FakeGradientInputsRepository(inputs={1: (5.0, 90.0)})
    service = GradientWayService(repository=repository)

    first = await service.get_way_values(Z, X, Y, None, 0.0)
    second = await service.get_way_values(Z, X, Y, None, 0.0)

    assert first == second
    # 勾配はキャッシュ確認を先に行い、ヒットすればDB問い合わせ自体をスキップする
    # （wind_way_serviceと異なりway一覧の取得自体もキャッシュされた値に含まれるため、
    # 2回目はrepositoryを一切呼ばない）。
    assert len(repository.calls) == 1


async def test_different_bearing_bucket_recomputes():
    repository = FakeGradientInputsRepository(inputs={1: (5.0, 90.0)})
    service = GradientWayService(repository=repository)

    first = await service.get_way_values(Z, X, Y, None, 0.0)
    second = await service.get_way_values(Z, X, Y, None, 90.0)

    assert first != second


async def test_repository_error_returns_empty_dict():
    repository = FakeGradientInputsRepository(inputs=None, error=RuntimeError("db down"))
    service = GradientWayService(repository=repository)

    result = await service.get_way_values(Z, X, Y, None, 0.0)

    assert result == {}


async def test_at_argument_is_ignored():
    # 勾配は時刻に依存しないため、atに何を渡しても結果は変わらない
    # （router側インターフェース統一のためだけに受け取る引数、gradient_way_service.py参照）。
    from datetime import datetime

    repository = FakeGradientInputsRepository(inputs={1: (5.0, 90.0)})
    service = GradientWayService(repository=repository)

    result = await service.get_way_values(Z, X, Y, datetime(2026, 1, 1), 0.0)

    expected = round(GradientCalculator.effective_gradient(5.0, 90.0, 0.0), 1)
    assert result == {1: expected}
