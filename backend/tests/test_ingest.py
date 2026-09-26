"""取込の共通経路（`ingest.ingest_source`）が、行の多さ・大きさに比例してメモリを抱えないこと。

本番の取込は上限つきの使い捨てコンテナで走り、標高のタイルは1件が約0.26MB（256×256画素のint32）ある。
ここでは同じ大きさの行を数百件、本物の入口へ流し、取込の間のPythonの確保の最大が、流した総量より
桁で小さいことを見る。アダプタは取込の追加点（`ADAPTERS`）へ差し込んだ、行を作って返すだけのもの。
"""

import tracemalloc
from dataclasses import replace

import asyncpg
import pytest
import pytest_asyncio
import shapely
from shapely.geometry import Point

from app.batch._common import asyncpg_dsn
from app.batch.ingest import (
    ADAPTERS,
    RegisteredAdapter,
    SourceRecord,
    ingest_source,
    partition_table_name,
)
from app.batch.source_profile import NoFields, SourceSpec, load_source_profile
from tests.conftest import postgis_database_url

# road_graph_session（conftest.py）と同じDBを使うため、docs/conventions/testing.mdのパターン2どおり
# loop_scope="module"・xdist_group="postgis"が必須。
pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

SOURCE = "ingest_probe"
#: 標高タイル1枚のraster（256×256画素のint32）と同じ大きさ。
ROW_BYTES = 256 * 256 * 4
ROWS = 300
POINT_WKB = shapely.to_wkb(Point(139.7, 35.6))


async def _large_rows(spec, profile, origin):
    for i in range(ROWS):
        yield SourceRecord(natural_key=str(i), geom_wkb=POINT_WKB, attrs={"i": i},
                           payload=bytes(ROW_BYTES))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def conn(road_graph_engine):
    """`road_graph_engine`に依存するのはスキーマを作らせるため。"""
    connection = await asyncpg.connect(asyncpg_dsn(postgis_database_url()))
    try:
        yield connection
    finally:
        await connection.execute(f'DROP TABLE IF EXISTS "{partition_table_name(SOURCE)}"')
        await connection.execute("DELETE FROM source_runs WHERE source = $1", SOURCE)
        await connection.close()


async def test_memory_held_while_ingesting_does_not_grow_with_the_rows(conn, monkeypatch):
    monkeypatch.setitem(ADAPTERS, SOURCE,
                        RegisteredAdapter(read=_large_rows, rows=NoFields, grid=NoFields))
    profile = replace(load_source_profile(), sources=(
        SourceSpec(name=SOURCE, adapter=SOURCE, rows=NoFields(), grid=NoFields()),))

    tracemalloc.start()
    try:
        async with conn.transaction():
            await ingest_source(conn, profile, SOURCE)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    count, total = await conn.fetchrow(
        f'SELECT count(*), sum(octet_length(payload)) FROM "{partition_table_name(SOURCE)}"')
    assert (count, total) == (ROWS, ROWS * ROW_BYTES)
    # 流した総量は約79MB。溜めずに流していれば、確保の最大は行数によらず一定（数MB）に留まる。
    assert peak < ROWS * ROW_BYTES / 10, f"取込の間の確保の最大 {peak / 1e6:.1f}MB"
