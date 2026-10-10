"""地図の配信が評価するタイルの材料を読む口（`services/feature_materials.py: FeatureMaterialService`）が、読んだ材料を
路面タイルの世代と読み方の署名ごとに持つこと。差し替えるのはDB（リポジトリ）だけで、ディスクの置き場は`conftest.py`の
autouseがテストごとの一時ディレクトリへ差し替える。

ここで見ないもの:
- 読み出しのSQLが返す材料 → `test_feature_materials_in_tile.py`・`test_material_values.py`
- DB障害・取込範囲の外・空のタイルを値なしにすること（`services/feature_midpoints.py: tile_features`） → `test_gradient_way_service.py`
- 置き場の失敗と失効 → `test_tile_persistent_cache.py`
"""

import inspect

import numpy as np

from app.config import settings
from app.domain.dynamic_way_values import FeatureMaterials
from app.infrastructure import debug_log
from app.infrastructure.derived_data_meta import DataRevisions
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services import feature_materials
from app.services.feature_materials import FeatureMaterialService

Z, X, Y = 14, 14551, 6447


def _materials(value: float) -> FeatureMaterials:
    return FeatureMaterials(feature_keys=("1-0",), columns={"num_a": np.array([value])})


class FakeFeatureMaterialsRepository:
    """RoadGraphRepositoryのうち、タイルの材料と世代と事故の収録年数だけを答えるフェイク。引数は本物の定義へ当てて照合する。"""

    def __init__(self, materials: FeatureMaterials):
        self.materials = materials
        self.revision = 1

    async def get_data_revisions(self):
        return DataRevisions(derived=self.revision, imported=1)

    async def get_accident_years_covered(self):
        return 1

    async def get_feature_materials_in_tile(self, *args, **kwargs):
        inspect.signature(RoadGraphRepository.get_feature_materials_in_tile).bind(self, *args, **kwargs)
        return self.materials


async def _num_a(service: FeatureMaterialService) -> float:
    materials = await service.materials(Z, X, Y)
    assert materials is not None
    return float(materials.columns["num_a"][0])


async def test_a_tile_read_once_is_served_from_the_cache():
    """DBの中身が変わっても、同じ世代の間は前に読んだ材料を返す。外した1回と当たった1回が、運用の統計の
    ヒット率に載る（集計はプロセスの寿命の間に足されるだけなので差で見る）。"""
    repository = FakeFeatureMaterialsRepository(_materials(1.0))
    service = FeatureMaterialService(repository)
    before = debug_log.get_stats().external.get("region:feature-materials")

    first = await _num_a(service)
    repository.materials = _materials(2.0)
    second = await _num_a(service)

    assert (first, second) == (1.0, 1.0)
    after = debug_log.get_stats().external["region:feature-materials"]
    counted_before = (before.cache_misses, before.cache_hits) if before else (0, 0)
    assert (after.cache_misses - counted_before[0], after.cache_hits - counted_before[1]) == (1, 1)


async def test_a_new_derived_data_revision_reads_the_tile_again(monkeypatch):
    """材料の鍵は路面タイルの`feature_key`と一致して初めて意味を持つ。派生を作り直した後も前の世代の材料を返すと、
    鍵の合わない道が「データなし」になり、合う道は古い値で塗られる。"""
    monkeypatch.setattr(settings, "derived_data_revision_check_interval_seconds", 0.0)
    repository = FakeFeatureMaterialsRepository(_materials(1.0))
    service = FeatureMaterialService(repository)
    await _num_a(service)

    repository.materials = _materials(2.0)
    repository.revision = 2

    assert await _num_a(service) == 2.0


async def test_a_deploy_that_changes_how_the_materials_are_read_reads_the_tile_again(monkeypatch):
    """読み出しのSQLを変えたデプロイは、DBの世代も路面タイルの形も動かさない。署名が鍵に届いていないと、前の読み方の
    材料がTTLの間返り続ける。"""
    repository = FakeFeatureMaterialsRepository(_materials(1.0))
    service = FeatureMaterialService(repository)
    await _num_a(service)

    repository.materials = _materials(2.0)
    monkeypatch.setattr(feature_materials, "FEATURE_MATERIALS_VALUE_SHAPE", "another-reading")

    assert await _num_a(service) == 2.0
