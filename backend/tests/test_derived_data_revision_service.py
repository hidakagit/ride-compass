"""DBの派生データと生データの世代を読み直す経路（`services/derived_data_revision_service.py`）と、それを読む
配信するタイルの世代（`services/tile_version_service.py: current_tile_versions`）。

TTLが切れるまでDBを読み直さないこと、読めないときも前回の値のまま配信を止めないこと、配信するタイルの世代が
読み直した世代を持つこと。

ここで見ないもの:
- 世代の文字列の組み立て・世代が分からないときの印 → `test_cache_identity.py`
- タイルを配る経路が世代を読み、世代付きの鍵でディスクへ残すこと → `test_region_service.py`
- 取込が実際に世代を進めること → `test_derived_data_meta.py`（本物の取込で見る）
"""

import pytest

from app.config import settings
from app.infrastructure.derived_data_meta import DataRevisions
from app.services import derived_data_revision_service, tile_version_service

pytestmark = pytest.mark.asyncio


class FakeRepository:
    """世代を返すだけのリポジトリ。サービスはフラットなリポジトリ契約にのみ依存する。"""

    def __init__(self, revision: int | None, imported: int = 3):
        self.revision = revision
        self.imported = imported

    async def get_data_revisions(self) -> DataRevisions:
        return DataRevisions(derived=self.revision, imported=self.imported)


async def test_second_call_within_ttl_does_not_read_db():
    # TTL内は問い合わせない。ここが効かないと、タイルの世代を配るたびにDB往復が1回増える。
    repository = FakeRepository(7)
    await derived_data_revision_service.refresh_current_revisions(repository)

    repository.revision = 8
    await derived_data_revision_service.refresh_current_revisions(repository)

    assert derived_data_revision_service.current_revisions() == DataRevisions(derived=7, imported=3)


async def test_db_failure_keeps_the_last_revision(monkeypatch):
    """世代を読めないことは、配信を止める理由にはならない。前回読んだ値のまま配る。"""

    class ExplodingRepository:
        async def get_data_revisions(self):
            raise ConnectionRefusedError("DBに触れない")

    monkeypatch.setattr(settings, "derived_data_revision_check_interval_seconds", 0.0)
    await derived_data_revision_service.refresh_current_revisions(FakeRepository(7))

    await derived_data_revision_service.refresh_current_revisions(ExplodingRepository())

    assert derived_data_revision_service.current_revisions() == DataRevisions(derived=7, imported=3)


async def test_配信するタイル世代は読んだ世代を前置きする():
    """タイルURLの世代は`<派生の世代>.<生データの世代>-<形の署名>`。形だけでは中身の作り直しを表せない。"""
    versions = await tile_version_service.current_tile_versions(FakeRepository(9, imported=4))

    assert versions, "配信するタイルの系統が1つも無い"
    for name, shape in tile_version_service.TILE_SHAPES.items():
        assert versions[name] == f"9.4-{shape}"
