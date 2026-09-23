"""ディスクキャッシュをDBの派生データ世代へ追随させる経路。

TTLが切れるまでDBを読み直さないこと、世代が変わったときに材料とスコア行列を揃えて捨てる
こと、世代が同じなら何も捨てないこと、そして配信するタイルの鍵に世代が入ること。
"""

import pytest

from app.domain.attributes import SearchMaterials
from app.domain.graph import LeanRoadGraph
from app.infrastructure import cache_identity, graph_material_cache, tile_score_matrix_cache
from app.services import derived_data_revision_service, region_service, tile_version_service

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
def _reset(_use_temp_tile_persistent_cache_dir):
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
            raise ConnectionRefusedError("DBに触れない")

    graph_material_cache.set_tile_materials(12, 5, 6, _materials())

    await derived_data_revision_service.ensure_caches_match_db(ExplodingRepository())

    assert graph_material_cache.get_tile_materials(12, 5, 6) is not None


async def test_世代が変わると焼き済みタイルの鍵も変わる():
    """世代の変化はSQLが読むテーブルの中身が作り直されたことを表す。

    **鍵に世代が入っていないと、同じ鍵で古い中身を配り続ける。**
    """
    derived_data_revision_service.reset_for_tests()
    graph_material_cache.clear()

    await derived_data_revision_service.ensure_caches_match_db(FakeRepository(5), force=True)
    before = region_service._tile_cache_path(12, 5, 6)
    await derived_data_revision_service.ensure_caches_match_db(FakeRepository(6), force=True)
    after = region_service._tile_cache_path(12, 5, 6)

    assert before != after, "世代が変わったのに焼き済みタイルの鍵が同じ"


async def test_配信するタイル世代は読んだ世代を前置きする():
    """タイルURLの世代は`<DBの世代>-<形の署名>`。形だけでは中身の作り直しを表せない。"""
    derived_data_revision_service.reset_for_tests()

    versions = await tile_version_service.current_tile_versions(FakeRepository(9))

    assert versions, "配信するタイルの系統が1つも無い"
    for name, shape in tile_version_service.TILE_SHAPES.items():
        assert versions[name] == f"9-{shape}"


async def test_世代を読めないうちは印を前置きする():
    """migration未適用のDB・DBなし構成。既定の世代を作らない——本物と区別が付かなくなる。"""
    derived_data_revision_service.reset_for_tests()

    versions = await tile_version_service.current_tile_versions(None)

    assert all(v.startswith(f"{cache_identity.UNKNOWN_REVISION}-") for v in versions.values())
