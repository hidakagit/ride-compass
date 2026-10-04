"""鍵→勾配配信層（`services/gradient_way_service.py`）。差し替えるのはDB（リポジトリ）だけで、ディスクの置き場は
`conftest.py`のautouseがテストごとの一時ディレクトリへ差し替える。

ここで見ないもの:
- 実効勾配の式・直角で落とす幅 → `test_gradient.py`
- 鍵のどの部分が違っても別のエントリになること・置き場の失敗と失効 → `test_dynamic_way_value_cache.py`・`test_tile_persistent_cache.py`
- 路面タイルの世代がDBの世代と形の署名を持つこと → `test_cache_identity.py`
"""

import inspect
from contextlib import nullcontext

import pytest

from app.config import settings
from app.domain.gradient import GradientCalculator
from app.infrastructure import debug_log
from app.infrastructure.derived_data_meta import DataRevisions
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services import gradient_way_service
from app.services.gradient_way_service import GradientConditions, GradientWayService

Z, X, Y = 14, 14551, 6447
#: キャッシュの検査で、1回目の後にDBの中身を替える先。`{1: (5.0, 30.0)}`と走行方位0度で値が違う。
CHANGED_INPUTS = {1: (8.0, 30.0)}


class FakeGradientInputsRepository:
    """RoadGraphRepositoryのうちget_feature_gradient_inputs_in_tileだけを実装したフェイク。

    引数は本物の定義へ当てて照合する。フェイクが自前の引数を持つと、本物の引数が変わっても
    呼び出し側の食い違いを通してしまう。
    """

    def __init__(self, inputs: dict[int, tuple[float, float]] | None, error: Exception | None = None):
        self.inputs = inputs
        self._error = error
        self.revision = 1

    async def get_data_revisions(self):
        return DataRevisions(derived=self.revision, imported=1)

    async def get_feature_gradient_inputs_in_tile(self, *args, **kwargs):
        inspect.signature(RoadGraphRepository.get_feature_gradient_inputs_in_tile).bind(self, *args, **kwargs)
        if self._error is not None:
            raise self._error
        return self.inputs


async def test_uncovered_tile_returns_empty_dict():
    repository = FakeGradientInputsRepository(inputs=None)
    service = GradientWayService(repository=repository)

    result = await service.get_way_values(Z, X, Y, GradientConditions(0.0))

    assert result == {}


async def test_computes_effective_gradient_per_way():
    # way1・way2は道路自身の勾配・向きが異なるため、同じ走行方位でも異なる値になる
    # （wind_way_serviceと違いbroadcastしない、モジュールdocstring参照）。
    inputs = {1: (5.0, 90.0), 2: (-3.0, 45.0)}
    repository = FakeGradientInputsRepository(inputs=inputs)
    service = GradientWayService(repository=repository)
    bearing_deg = 90.0

    result = await service.get_way_values(Z, X, Y, GradientConditions(bearing_deg))

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

    result = await service.get_way_values(Z, X, Y, GradientConditions(90.0))

    assert result == {2: 15.0}


@pytest.mark.usefixtures("empty_debug_counters")
async def test_second_call_with_same_bearing_bucket_is_served_from_cache():
    # 直角に落ちない向きにする（空の結果同士を比べても、キャッシュの検査にならない）。
    repository = FakeGradientInputsRepository(inputs={1: (5.0, 30.0)})
    service = GradientWayService(repository=repository)

    first = await service.get_way_values(Z, X, Y, GradientConditions(0.0))
    # wind_way_serviceと異なり、way一覧の取得もキャッシュした値に含まれる。DBの中身が変わっても、
    # 当たれば前の値を返す。
    repository.inputs = CHANGED_INPUTS
    second = await service.get_way_values(Z, X, Y, GradientConditions(0.0))

    assert first == second
    # 外した1回と当たった1回が、運用の統計のヒット率に載る。
    stats = debug_log.get_stats().external["region:gradient-way-values"]
    assert (stats.cache_misses, stats.cache_hits) == (1, 1)


async def test_different_bearing_bucket_recomputes():
    # どちらの走行方位でも直角に落ちない向きにする（片方が空になると、値が作り直された
    # ことではなく落ちたことを見てしまう）。
    repository = FakeGradientInputsRepository(inputs={1: (5.0, 30.0)})
    service = GradientWayService(repository=repository)

    # 走行方位は符号を決める（domain/gradient.py）。値が変わる組み合わせにするため、
    # 道路の向きを挟んで反対側の方位を選ぶ。
    first = await service.get_way_values(Z, X, Y, GradientConditions(0.0))
    second = await service.get_way_values(Z, X, Y, GradientConditions(180.0))

    assert first != second


async def test_a_new_derived_data_revision_recomputes_without_the_catalog(monkeypatch):
    """勾配の鍵は路面タイルの世代を持つ。世代はこの経路が自分で読み直すため、バッチが世代を進めれば、
    カタログを誰も取らなくてもTTLの後から作り直す（前の世代の値は路面タイルの鍵と一致しない）。"""
    monkeypatch.setattr(settings, "derived_data_revision_check_interval_seconds", 0.0)
    repository = FakeGradientInputsRepository(inputs={1: (5.0, 30.0)})
    service = GradientWayService(repository=repository)
    first = await service.get_way_values(Z, X, Y, GradientConditions(0.0))

    repository.inputs = CHANGED_INPUTS
    repository.revision = 2

    assert await service.get_way_values(Z, X, Y, GradientConditions(0.0)) != first


async def test_a_deploy_that_changes_how_gradient_is_computed_recomputes(monkeypatch):
    """勾配の作り方（入力のSQL・落とす幅・丸め・式のリビジョン）を変えたデプロイは、DBの世代も路面タイルの形も
    動かさない。署名が鍵に届いていないと、前の計算の値がTTL（24時間）の間返り続ける。"""
    repository = FakeGradientInputsRepository(inputs={1: (5.0, 30.0)})
    service = GradientWayService(repository=repository)
    first = await service.get_way_values(Z, X, Y, GradientConditions(0.0))

    repository.inputs = CHANGED_INPUTS
    monkeypatch.setattr(gradient_way_service, "GRADIENT_VALUE_SHAPE", "another-computation")

    assert await service.get_way_values(Z, X, Y, GradientConditions(0.0)) != first


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (ConnectionRefusedError("db down"), nullcontext()),
        # DB障害でない例外まで空へ倒すと、利用者には「データなし」に見えて誰も気づかない。
        (TypeError("wrong arguments"), pytest.raises(TypeError)),
    ],
)
async def test_only_a_db_outage_is_turned_into_an_empty_result(error, outcome):
    service = GradientWayService(repository=FakeGradientInputsRepository(inputs=None, error=error))

    with outcome:
        assert await service.get_way_values(Z, X, Y, GradientConditions(0.0)) == {}
