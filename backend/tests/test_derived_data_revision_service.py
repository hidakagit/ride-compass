"""ディスクキャッシュをDBの派生データ世代へ追随させる経路（改善計画T847）。

見るのは3点。TTLが切れるまでDBを読み直さないこと、世代が変わったときに材料とスコア行列の
両方を捨てること、そして世代が同じなら何も捨てないこと。
"""

import pytest

from app.domain.attributes import SearchMaterials
from app.domain.graph import LeanRoadGraph
from app.infrastructure import graph_material_cache, tile_score_matrix_cache
from app.services import derived_data_revision_service

pytestmark = pytest.mark.asyncio


class FakeRepository:
    """世代を返すだけのリポジトリ。サービスはフラットなリポジトリ契約にのみ依存する。"""

    def __init__(self, revision: int | None):
        self.revision = revision
        self.calls = 0

    async def get_derived_data_revision(self) -> int | None:
        self.calls += 1
        return self.revision


def _materials() -> SearchMaterials:
    return SearchMaterials(graph=LeanRoadGraph(graph_version="v", nodes={}, edges={}), materials=None)


@pytest.fixture(autouse=True)
def _reset():
    derived_data_revision_service.reset_for_tests()
    graph_material_cache.clear()
    tile_score_matrix_cache.clear()
    yield
    derived_data_revision_service.reset_for_tests()
    graph_material_cache.clear()
    tile_score_matrix_cache.clear()


async def test_first_call_reads_db_and_records_revision():
    repository = FakeRepository(7)

    await derived_data_revision_service.ensure_caches_match_db(repository)

    assert repository.calls == 1
    assert graph_material_cache.read_persisted_revision() == 7


async def test_second_call_within_ttl_does_not_read_db():
    # TTL内は問い合わせない。ここが効かないと、材料を使う全リクエストがDB往復を1回増やす。
    repository = FakeRepository(7)
    await derived_data_revision_service.ensure_caches_match_db(repository)

    await derived_data_revision_service.ensure_caches_match_db(repository)

    assert repository.calls == 1


async def test_force_reads_db_even_within_ttl():
    repository = FakeRepository(7)
    await derived_data_revision_service.ensure_caches_match_db(repository)

    await derived_data_revision_service.ensure_caches_match_db(repository, force=True)

    assert repository.calls == 2


async def test_unchanged_revision_keeps_both_caches():
    repository = FakeRepository(7)
    await derived_data_revision_service.ensure_caches_match_db(repository)
    graph_material_cache.set_tile_materials(12, 5, 6, _materials())

    await derived_data_revision_service.ensure_caches_match_db(repository, force=True)

    assert graph_material_cache.get_tile_materials(12, 5, 6) is not None


async def test_changed_revision_drops_materials_and_score_matrix():
    # スコア行列は材料から作られるため、材料を捨てたら一緒に捨てないと古い値が残る。
    repository = FakeRepository(7)
    await derived_data_revision_service.ensure_caches_match_db(repository)
    graph_material_cache.set_tile_materials(12, 5, 6, _materials())
    tile_score_matrix_cache._cache[(12, 5, 6)] = object()

    repository.revision = 8
    await derived_data_revision_service.ensure_caches_match_db(repository, force=True)

    assert graph_material_cache.get_tile_materials(12, 5, 6) is None
    assert tile_score_matrix_cache.size() == 0


async def test_db_failure_does_not_break_the_caller():
    """世代を読めないことは、ルート生成を止める理由にはならない。キャッシュは温存する。"""

    class ExplodingRepository:
        async def get_derived_data_revision(self):
            raise RuntimeError("DBに触れない")

    graph_material_cache.set_tile_materials(12, 5, 6, _materials())

    await derived_data_revision_service.ensure_caches_match_db(ExplodingRepository())

    assert graph_material_cache.get_tile_materials(12, 5, 6) is not None
