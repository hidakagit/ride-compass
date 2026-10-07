"""取込の共通経路（`ingest.ingest_source`）が、行の多さ・大きさに比例してメモリを抱えないこと。
途中で落ちた取込が、行を元のまま残して失敗のrunを記録すること。取込の間は派生の作り直しが止まること。
アダプタが必ず持つと宣言した列が空の行を、区画が断ること。

本番の取込は上限つきの使い捨てコンテナで走り、標高のタイルは1件が約0.26MB（256×256画素のint32）ある。
ここでは同じ大きさの行を数百件、本物の入口へ流し、取込の間のPythonの確保の最大が、流した総量より
桁で小さいことを見る。アダプタは取込の追加点（`ADAPTERS`）へ差し込んだ、行を作って返すだけのもの。

ここで見ないもの:
- アダプタが外部の形をどう読むか → `test_npa_honhyo.py`・`test_osm_pbf.py`・`test_gsi_dem_tile.py`
- 作り直しの間に取込を始めると断ること → 作り直しの側から起こす`test_derive_cli.py`
"""

import tracemalloc
from dataclasses import replace

import asyncpg
import pytest
import pytest_asyncio
import shapely
from shapely.geometry import Point

from app.batch import derive_cli
from app.batch.ingest import (
    ADAPTERS,
    RegisteredAdapter,
    SourceRecord,
    ingest_source,
    partition_table_name,
)
from app.batch.source_profile import NoFields, SourceProfile, SourceSpec, load_source_profile
from app.infrastructure.source_models import SourceFeatureRow
from tests.conftest import postgis_database_url, raw_connection

# road_graph_session（conftest.py）と同じDBを使うため、docs/conventions/testing.mdのパターン2どおり
# loop_scope="module"・xdist_group="postgis"が必須。
pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

SOURCE = "ingest_probe"
#: 必ず持つ列を宣言したアダプタで初めて取り込むソース（区画は作るときにだけ制約を持つ）。
REQUIRED_SOURCE = "ingest_probe_required"
#: 標高タイル1枚のraster（256×256画素のint32）と同じ大きさ。
ROW_BYTES = 256 * 256 * 4
ROWS = 300
POINT_WKB = shapely.to_wkb(Point(139.7, 35.6))


def _only(source: str, adapter: str) -> SourceProfile:
    return replace(load_source_profile(None), sources=(
        SourceSpec(name=source, adapter=adapter, rows=NoFields(), grid=NoFields()),))


async def _large_rows(spec, profile, origin):
    for i in range(ROWS):
        yield SourceRecord(natural_key=str(i), geom_wkb=POINT_WKB, attrs={"i": i},
                           payload=bytes(ROW_BYTES))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def conn(road_graph_engine):
    """`road_graph_engine`に依存するのはスキーマを作らせるため。"""
    async with raw_connection() as connection:
        try:
            yield connection
        finally:
            for source in (SOURCE, REQUIRED_SOURCE):
                await connection.execute(f'DROP TABLE IF EXISTS "{partition_table_name(source)}"')
                await connection.execute("DELETE FROM source_runs WHERE source = $1", source)


async def test_memory_held_while_ingesting_does_not_grow_with_the_rows(conn, monkeypatch):
    monkeypatch.setitem(ADAPTERS, SOURCE,
                        RegisteredAdapter(read=_large_rows, rows=NoFields, grid=NoFields))
    profile = _only(SOURCE, SOURCE)

    tracemalloc.start()
    try:
        await ingest_source(conn, profile, SOURCE)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    count, total = await conn.fetchrow(
        f'SELECT count(*), sum(octet_length(payload)) FROM "{partition_table_name(SOURCE)}"')
    assert (count, total) == (ROWS, ROWS * ROW_BYTES)
    # 流した総量は約79MB。溜めずに流していれば、確保の最大は行数によらず一定（数MB）に留まる。
    assert peak < ROWS * ROW_BYTES / 10, f"取込の間の確保の最大 {peak / 1e6:.1f}MB"


async def _breaks_midway(spec, profile, origin):
    yield SourceRecord(natural_key="new", geom_wkb=POINT_WKB, attrs={})
    raise OSError("配信元が途中で切れた")


async def test_a_failed_ingest_leaves_a_failed_run_and_the_previous_rows(conn, monkeypatch):
    async def one_row(spec, profile, origin):
        yield SourceRecord(natural_key="old", geom_wkb=POINT_WKB, attrs={})

    monkeypatch.setitem(ADAPTERS, "one_row", RegisteredAdapter(read=one_row, rows=NoFields, grid=NoFields))
    monkeypatch.setitem(ADAPTERS, "breaks", RegisteredAdapter(read=_breaks_midway, rows=NoFields, grid=NoFields))
    succeeded = await ingest_source(conn, _only(SOURCE, "one_row"), SOURCE)

    with pytest.raises(OSError):
        await ingest_source(conn, _only(SOURCE, "breaks"), SOURCE)

    runs = await conn.fetch(
        "SELECT run_id, status, finished_at IS NOT NULL AS closed FROM source_runs"
        " WHERE source = $1 AND run_id >= $2 ORDER BY run_id", SOURCE, succeeded)
    assert [(r["status"], r["closed"]) for r in runs] == [("succeeded", True), ("failed", True)]
    kept = await conn.fetch(f'SELECT natural_key, run_id FROM "{partition_table_name(SOURCE)}"')
    assert [(r["natural_key"], r["run_id"]) for r in kept] == [("old", succeeded)]


async def test_ingesting_inside_a_transaction_is_refused(conn, monkeypatch):
    monkeypatch.setitem(ADAPTERS, "breaks", RegisteredAdapter(read=_breaks_midway, rows=NoFields, grid=NoFields))
    async with conn.transaction():
        with pytest.raises(RuntimeError, match="トランザクションの外"):
            await ingest_source(conn, _only(SOURCE, "breaks"), SOURCE)


async def test_a_rebuild_is_refused_while_an_import_runs(conn, monkeypatch):
    async def rebuild_meanwhile(spec, profile, origin):
        with pytest.raises(RuntimeError, match="取込が走っている"):
            await derive_cli.run(postgis_database_url(), None)
        yield SourceRecord(natural_key="new", geom_wkb=POINT_WKB, attrs={})

    monkeypatch.setitem(ADAPTERS, "rebuild", RegisteredAdapter(read=rebuild_meanwhile, rows=NoFields, grid=NoFields))
    await ingest_source(conn, _only(SOURCE, "rebuild"), SOURCE)


async def test_a_row_missing_a_column_the_adapter_requires_is_refused(conn, monkeypatch):
    async def without_payload(spec, profile, origin):
        yield SourceRecord(natural_key="1", geom_wkb=POINT_WKB, attrs={})

    monkeypatch.setitem(ADAPTERS, "without_payload", RegisteredAdapter(
        read=without_payload, rows=NoFields, grid=NoFields, required=(SourceFeatureRow.payload,)))
    with pytest.raises(asyncpg.NotNullViolationError, match="payload"):
        await ingest_source(conn, _only(REQUIRED_SOURCE, "without_payload"), REQUIRED_SOURCE)
