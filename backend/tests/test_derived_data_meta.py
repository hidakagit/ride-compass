"""`infrastructure/derived_data_meta.py`——派生データと生データの世代。

確かめるのは、派生の世代が行の無いDBで最初に進めたときに生まれて進むことと、成功した取込だけが生データの世代を
進めること。後者は本物の取込を通して、配信するタイルの世代（`GET /api/axis-catalog`の`tile_versions`と同じ口）で見る。

ここで見ないもの:
- 世代の変化を読み手がどう使うか（キャッシュの追随・配列の作り直し） → それぞれの読み手のテスト
- 入れ替えと同じトランザクションで進むこと・作り直しに使った取込の記録 → `test_derive_cli.py`
"""

import asyncpg
import pytest

from app.batch.common import asyncpg_dsn
from app.config import settings
from app.infrastructure import derived_data_meta
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.region_service import RegionService
from tests.conftest import postgis_database_url
from tests.source_ingest import ingest_records, point_record

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]


async def _bump_revision() -> int:
    conn = await asyncpg.connect(asyncpg_dsn(postgis_database_url()))
    try:
        return await derived_data_meta.bump_revision(conn)
    finally:
        await conn.close()


async def test_first_bump_creates_the_revision_and_later_bumps_advance_it(road_graph_session):
    """行が無いDB（スキーマをORMの宣言から作っただけ）でも、最初に進めた時点で世代が生まれる。"""
    assert (await derived_data_meta.get_revisions(road_graph_session)).derived is None

    first = await _bump_revision()
    second = await _bump_revision()

    assert (first, second) == (1, 2)
    assert (await derived_data_meta.get_revisions(road_graph_session)).derived == 2


@pytest.fixture
def reread_every_time(monkeypatch):
    monkeypatch.setattr(settings, "derived_data_revision_check_interval_seconds", 0.0)


async def _tile_versions(session) -> dict[str, str]:
    return await RegionService(repository=RoadGraphRepository(session)).tile_versions()


async def test_a_succeeded_ingest_of_any_source_changes_every_tile_version(road_graph_session, reread_every_time):
    """取込だけを流すと派生の世代は動かないが、タイルは生データも直接読む。どのソースの取り直しでも
    全系統の鍵が変わらないと、取込の前と後に焼いたタイルが同じ鍵で混ざる。成功した取込はソースを問わず
    同じに数える（`source_models.py: succeeded_run_count`）ので、1つのソースで見る。"""
    await _bump_revision()
    before = await _tile_versions(road_graph_session)

    await ingest_records("dem", [])

    after = await _tile_versions(road_graph_session)
    assert [name for name in before if before[name] == after[name]] == []


async def test_a_failed_ingest_keeps_every_tile_version(road_graph_session, reread_every_time):
    """失敗した取込は生データを入れ替えない。鍵を変えると、中身の同じタイルを焼き直すだけになる。"""
    await _bump_revision()
    await ingest_records("accident", [point_record(1, 139.7, 35.6)])
    before = await _tile_versions(road_graph_session)

    def breaks_midway():
        yield point_record(2, 139.7, 35.6)
        raise OSError("配信元が途中で切れた")

    with pytest.raises(OSError):
        await ingest_records("accident", breaks_midway())

    assert await _tile_versions(road_graph_session) == before
