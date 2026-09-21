"""鍵→勾配配信層（`services/gradient_way_service.py`）のオーケストレーション。"""

import pytest

from app.domain.gradient import GradientCalculator
from app.infrastructure import redis_json_cache
from app.services.gradient_way_service import GradientWayService
from tests.fake_redis import FakeRedis

Z, X, Y = 14, 14551, 6447


@pytest.fixture(autouse=True)
def use_fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(redis_json_cache, "get_redis_client_or_none", lambda: fake)
    return fake


class FakeGradientInputsRepository:
    """RoadGraphRepositoryのうちget_feature_gradient_inputs_in_tileだけを実装したフェイク。"""

    def __init__(self, inputs: dict[int, tuple[float, float]] | None, error: Exception | None = None):
        self._inputs = inputs
        self._error = error
        self.calls: list[tuple[int, int, int, tuple[int, int, int]]] = []

    async def get_feature_gradient_inputs_in_tile(self, z, x, y, bbox, coverage_tile):
        self.calls.append((z, x, y, coverage_tile))
        if self._error is not None:
            raise self._error
        return self._inputs


async def test_repository_none_returns_empty_dict():
    service = GradientWayService(repository=None)

    result = await service.get_way_values(Z, X, Y, None, 0.0)

    assert result == {}


# 型が`float | None`なのは呼び出し口の形を揃えるためで、Noneのまま計算へ進ませない。
async def test_bearing_deg_none_raises_value_error():
    service = GradientWayService(repository=None)

    with pytest.raises(ValueError, match="bearing_deg"):
        await service.get_way_values(Z, X, Y, None, None)


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
    inputs = {1: (5.0, 90.0), 2: (-3.0, 45.0)}
    repository = FakeGradientInputsRepository(inputs=inputs)
    service = GradientWayService(repository=repository)
    bearing_deg = 90.0

    result = await service.get_way_values(Z, X, Y, None, bearing_deg)

    expected_1 = round(GradientCalculator.effective_gradient(5.0, 90.0, bearing_deg), 1)
    expected_2 = round(GradientCalculator.effective_gradient(-3.0, 45.0, bearing_deg), 1)
    assert result == {1: expected_1, 2: expected_2}


async def test_perpendicular_way_is_omitted_instead_of_zero():
    """直角に近い道路は結果から落とす（地図では「データなし」）。

    0.0を返すと凡例の「平坦」の段へ入り、実際には急な坂の道が平坦な道と同じ色で塗られる。
    """
    # way1は走行方位と直角（落ちる）、way2は沿っている（残る）。
    repository = FakeGradientInputsRepository(inputs={1: (15.0, 0.0), 2: (15.0, 90.0)})
    service = GradientWayService(repository=repository)

    result = await service.get_way_values(Z, X, Y, None, 90.0)

    assert 1 not in result
    assert result[2] == 15.0


async def test_second_call_with_same_bearing_bucket_is_served_from_cache():
    # 直角に落ちない向きにする（空の結果同士を比べても、キャッシュの検査にならない）。
    repository = FakeGradientInputsRepository(inputs={1: (5.0, 30.0)})
    service = GradientWayService(repository=repository)

    first = await service.get_way_values(Z, X, Y, None, 0.0)
    second = await service.get_way_values(Z, X, Y, None, 0.0)

    assert first == second
    # 勾配はキャッシュ確認を先に行い、ヒットすればDB問い合わせ自体をスキップする
    # （wind_way_serviceと異なりway一覧の取得自体もキャッシュされた値に含まれるため、
    # 2回目はrepositoryを一切呼ばない）。
    assert len(repository.calls) == 1


async def test_different_bearing_bucket_recomputes():
    # どちらの走行方位でも直角に落ちない向きにする（片方が空になると、値が作り直された
    # ことではなく落ちたことを見てしまう）。
    repository = FakeGradientInputsRepository(inputs={1: (5.0, 30.0)})
    service = GradientWayService(repository=repository)

    # 走行方位は符号を決める（domain/gradient.py）。値が変わる組み合わせにするため、
    # 道路の向きを挟んで反対側の方位を選ぶ。
    first = await service.get_way_values(Z, X, Y, None, 0.0)
    second = await service.get_way_values(Z, X, Y, None, 180.0)

    assert first != second
    # 値が違うことだけでなく、向きバケットが違えば実際に作り直していることを見る。
    assert len(repository.calls) == 2


async def test_repository_error_returns_empty_dict():
    repository = FakeGradientInputsRepository(inputs=None, error=RuntimeError("db down"))
    service = GradientWayService(repository=repository)

    result = await service.get_way_values(Z, X, Y, None, 0.0)

    assert result == {}


async def test_at_argument_is_ignored():
    # 勾配は時刻に依存しないため、atに何を渡しても結果は変わらない
    # （router側インターフェース統一のためだけに受け取る引数、gradient_way_service.py参照）。
    from datetime import datetime

    repository = FakeGradientInputsRepository(inputs={1: (5.0, 0.0)})
    service = GradientWayService(repository=repository)

    result = await service.get_way_values(Z, X, Y, datetime(2026, 1, 1), 0.0)

    expected = round(GradientCalculator.effective_gradient(5.0, 0.0, 0.0), 1)
    assert result == {1: expected}
