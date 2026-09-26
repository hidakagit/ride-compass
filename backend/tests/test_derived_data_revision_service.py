"""DBの派生データ世代を読み直す経路（配信するタイルの世代が使う）。

TTLが切れるまでDBを読み直さないこと、読めないときも前回の値のまま配信を止めないこと、そして配信するタイルの
鍵に世代が入ること。
"""

import pytest

from app.infrastructure import cache_identity
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


@pytest.fixture(autouse=True)
def _reset():
    derived_data_revision_service.reset_for_tests()
    yield
    derived_data_revision_service.reset_for_tests()


async def test_first_call_reads_db_and_records_revision():
    repository = FakeRepository(7)

    await derived_data_revision_service.refresh_current_revision(repository)

    assert repository.calls == 1
    assert derived_data_revision_service.current_revision() == 7


async def test_second_call_within_ttl_does_not_read_db():
    # TTL内は問い合わせない。ここが効かないと、タイルの世代を配るたびにDB往復が1回増える。
    repository = FakeRepository(7)
    await derived_data_revision_service.refresh_current_revision(repository)

    await derived_data_revision_service.refresh_current_revision(repository)

    assert repository.calls == 1


async def test_force_reads_db_even_within_ttl():
    repository = FakeRepository(7)
    await derived_data_revision_service.refresh_current_revision(repository)
    repository.revision = 8

    await derived_data_revision_service.refresh_current_revision(repository, force=True)

    assert repository.calls == 2
    assert derived_data_revision_service.current_revision() == 8


async def test_db_failure_keeps_the_last_revision():
    """世代を読めないことは、配信を止める理由にはならない。前回読んだ値のまま配る。"""

    class ExplodingRepository:
        async def get_derived_data_revision(self):
            raise ConnectionRefusedError("DBに触れない")

    await derived_data_revision_service.refresh_current_revision(FakeRepository(7))

    await derived_data_revision_service.refresh_current_revision(ExplodingRepository(), force=True)

    assert derived_data_revision_service.current_revision() == 7


async def test_世代が変わると焼き済みタイルの鍵も変わる():
    """世代の変化はSQLが読むテーブルの中身が作り直されたことを表す。

    **鍵に世代が入っていないと、同じ鍵で古い中身を配り続ける。**
    """
    await derived_data_revision_service.refresh_current_revision(FakeRepository(5), force=True)
    before = region_service._tile_cache_path(12, 5, 6)
    await derived_data_revision_service.refresh_current_revision(FakeRepository(6), force=True)
    after = region_service._tile_cache_path(12, 5, 6)

    assert before != after, "世代が変わったのに焼き済みタイルの鍵が同じ"


async def test_配信するタイル世代は読んだ世代を前置きする():
    """タイルURLの世代は`<DBの世代>-<形の署名>`。形だけでは中身の作り直しを表せない。"""
    versions = await tile_version_service.current_tile_versions(FakeRepository(9))

    assert versions, "配信するタイルの系統が1つも無い"
    for name, shape in tile_version_service.TILE_SHAPES.items():
        assert versions[name] == f"9-{shape}"


async def test_世代を読めないうちは印を前置きする():
    """世代の行が無いDB。既定の世代を作らない——本物と区別が付かなくなる。"""
    versions = await tile_version_service.current_tile_versions(FakeRepository(None))

    assert all(v.startswith(f"{cache_identity.UNKNOWN_REVISION}-") for v in versions.values())
