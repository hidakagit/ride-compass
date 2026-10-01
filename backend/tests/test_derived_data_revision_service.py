"""DBの派生データと生データの世代を読み直す経路（配信するタイルの世代が使う）。

TTLが切れるまでDBを読み直さないこと、読めないときも前回の値のまま配信を止めないこと、そして配信するタイルの
鍵に世代が入り、世代が分からないうちに焼いたタイルはディスクへ残らないこと。取込が実際に世代を進めることは
`test_derived_data_meta.py`が本物の取込で見る。
"""

import pytest

from app.config import settings
from app.infrastructure import cache_identity
from app.infrastructure.derived_data_meta import DataRevisions
from app.services import derived_data_revision_service, tile_version_service
from app.services.region_service import RegionService

pytestmark = pytest.mark.asyncio


class FakeRepository:
    """世代を返すだけのリポジトリ。サービスはフラットなリポジトリ契約にのみ依存する。"""

    def __init__(self, revision: int | None, imported: int = 3):
        self.revision = revision
        self.imported = imported
        self.calls = 0

    async def get_data_revisions(self) -> DataRevisions:
        self.calls += 1
        return DataRevisions(derived=self.revision, imported=self.imported)


async def test_first_call_reads_db_and_records_revision():
    repository = FakeRepository(7)

    await derived_data_revision_service.refresh_current_revisions(repository)

    assert repository.calls == 1
    assert derived_data_revision_service.current_revisions() == DataRevisions(derived=7, imported=3)


async def test_second_call_within_ttl_does_not_read_db():
    # TTL内は問い合わせない。ここが効かないと、タイルの世代を配るたびにDB往復が1回増える。
    repository = FakeRepository(7)
    await derived_data_revision_service.refresh_current_revisions(repository)

    await derived_data_revision_service.refresh_current_revisions(repository)

    assert repository.calls == 1


async def test_db_failure_keeps_the_last_revision(monkeypatch):
    """世代を読めないことは、配信を止める理由にはならない。前回読んだ値のまま配る。"""

    class ExplodingRepository:
        async def get_data_revisions(self):
            raise ConnectionRefusedError("DBに触れない")

    monkeypatch.setattr(settings, "derived_data_revision_check_interval_seconds", 0.0)
    await derived_data_revision_service.refresh_current_revisions(FakeRepository(7))

    await derived_data_revision_service.refresh_current_revisions(ExplodingRepository())

    assert derived_data_revision_service.current_revisions() == DataRevisions(derived=7, imported=3)


class TileRepository(FakeRepository):
    """世代と路面タイルを返すリポジトリ。タイルを焼いた回数を数える。"""

    def __init__(self, revision: int | None, imported: int = 3):
        super().__init__(revision, imported)
        self.tile_calls = 0

    async def get_road_surface_tile_mvt(self, z, x, y, bbox):
        self.tile_calls += 1
        return b"tile"


async def test_世代が変わると焼き済みタイルを使わずに焼き直す(monkeypatch):
    """世代の変化はSQLが読むテーブルの中身が作り直されたことを表す。

    **鍵に世代が入っていないと、同じ鍵で古い中身を配り続ける。** 世代を読み直すのはタイルを配る経路
    自身で、バッチが世代を進めた後は、カタログを誰も取らなくてもTTLの後のタイルから新しい世代で配る。
    """
    monkeypatch.setattr(settings, "derived_data_revision_check_interval_seconds", 0.0)
    repository = TileRepository(5)
    service = RegionService(repository=repository)
    await service.get_road_surface_tile(12, 5, 6)
    await service.get_road_surface_tile(12, 5, 6)
    assert repository.tile_calls == 1, "同じ世代のタイルを焼き直している"

    repository.revision = 6
    await service.get_road_surface_tile(12, 5, 6)
    assert repository.tile_calls == 2, "派生の世代が変わったのに焼き済みタイルを配った"

    repository.imported = 4
    await service.get_road_surface_tile(12, 5, 6)
    assert repository.tile_calls == 3, "生データの世代が変わったのに焼き済みタイルを配った"


async def test_配信するタイル世代は読んだ世代を前置きする():
    """タイルURLの世代は`<派生の世代>.<生データの世代>-<形の署名>`。形だけでは中身の作り直しを表せない。"""
    versions = await tile_version_service.current_tile_versions(FakeRepository(9, imported=4))

    assert versions, "配信するタイルの系統が1つも無い"
    for name, shape in tile_version_service.TILE_SHAPES.items():
        assert versions[name] == f"9.4-{shape}"


class NeverReadRepository(TileRepository):
    """起動直後からDBに触れない。世代を一度も読めていない状態を作る。"""

    def __init__(self):
        super().__init__(revision=None)

    async def get_data_revisions(self):
        raise ConnectionRefusedError("DBに触れない")


@pytest.mark.parametrize("repository_type", [lambda: TileRepository(None), NeverReadRepository],
                         ids=["派生の世代の行が無い", "まだ一度も読めていない"])
async def test_世代が分からないうちは印を前置きしディスクへ残さない(monkeypatch, repository_type):
    """既定の世代を作らない——本物と区別が付かなくなる。印の鍵で焼いたタイルを残すと、後で世代が
    分かっても古いと判定できないため、毎回焼き直す。"""
    monkeypatch.setattr(settings, "derived_data_revision_check_interval_seconds", 0.0)
    repository = repository_type()

    versions = await tile_version_service.current_tile_versions(repository)
    service = RegionService(repository=repository)
    await service.get_road_surface_tile(12, 5, 6)
    await service.get_road_surface_tile(12, 5, 6)

    assert all(v.startswith(f"{cache_identity.UNKNOWN_REVISION}-") for v in versions.values())
    assert repository.tile_calls == 2, "世代が分からないまま焼いたタイルをディスクから配った"
