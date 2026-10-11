"""鮮度台帳（`infrastructure/derived_data_freshness.py`）と、それを画面の判定へ組むレポート
（`services/derived_data_freshness_service.py: build_freshness_report`）の契約。

この台帳は**対象を宣言から導く**（表の印`orm_base.py: DERIVED`を持つ表が派生データ）。表や列が増えても
手当てが要らないことが値打ちなので、ここで見るのは個々の表の名前ではなく、導出の規則である: 派生の表・値の列、
ソースごとの鮮度と表ごとの列の記録との比べ（DBで）、作り直した直後に値や行の無い道・区間があっても作り直しを求めないこと。
"""

import pytest

from app.batch import derive_cli
from app.infrastructure import derived_data_meta, derived_models
from app.infrastructure.derived_data_freshness import (
    ColumnsChange,
    DerivedDataFreshnessQuery,
    declared_columns,
    derived_tables,
    value_columns,
)
from app.infrastructure.orm_base import Base
from app.infrastructure.source_models import Source
from app.services.derived_data_freshness_service import build_freshness_report
from tests.conftest import postgis_database_url, raw_connection
from tests.source_ingest import abr_prefecture_record, ingest_records, point_record, way_record

from datetime import datetime, timezone

DERIVED = derived_tables()


#: DBで確かめるテストにだけ付ける（接続とイベントループをファイルで共有する。testing-backend.md パターン2）。
on_postgis = pytest.mark.asyncio(loop_scope="module")


# --- 対象の導出 -------------------------------------------------------------

def test_派生の表の印は派生の表のモジュールの表にだけ付く():
    """印を付け忘れた派生の表は、作り直しで作業用のスキーマへ写されず、台帳にも出ない。"""
    declared = {mapper.local_table.name for mapper in Base.registry.mappers
                if mapper.class_.__module__ == derived_models.__name__}
    assert declared, "派生の表のモジュールに表が1つも無い"
    assert {table.name for table in DERIVED} == declared


def test_値の列は鍵を除いた列():
    """鍵はNULLになりえない。数えると常に「未計算0件」の行が並ぶ。"""
    table = DERIVED[0]
    keys = {column.name for column in table.primary_key.columns}
    values = value_columns(table)

    assert values
    assert keys.isdisjoint(values)


# --- ソースごとの鮮度 -------------------------------------------------------

def _breaks_midway():
    yield point_record(1, 139.7, 35.6)
    raise OSError("配信元が途中で切れた")


@on_postgis
async def test_作り直しに使った取込が成功した最新の取込でないソースは作り直しが要る(road_graph_session):
    """取り直したソース・まだ作り直しに使っていないソース・取込が1度も成功していないソースが、作り直しが要る側に出る。"""
    way_run = await ingest_records(Source.OSM_WAY, [])
    accident_run = await ingest_records(Source.ACCIDENT, [])
    async with raw_connection() as conn:
        await derived_data_meta.replace_source_runs(conn, {Source.OSM_WAY: way_run, Source.ACCIDENT: accident_run})
    reingested_accident_run = await ingest_records(Source.ACCIDENT, [])
    node_run = await ingest_records(Source.OSM_NODE, [])
    with pytest.raises(OSError):
        await ingest_records(Source.DEM, _breaks_midway())

    freshness = await DerivedDataFreshnessQuery(road_graph_session).get_freshness()
    report = build_freshness_report(freshness, datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert [(s.source, s.derived_run_id, s.latest_run_id, s.needs_rebuild) for s in report.sources] == [
        (Source.ACCIDENT, accident_run, reingested_accident_run, True),  # 取り直した
        (Source.DEM, None, None, True),                                   # 取込が1度も成功していない
        (Source.OSM_NODE, None, node_run, True),                          # まだ作り直しに使っていない
        (Source.OSM_WAY, way_run, way_run, False),
    ]


# --- 表ごとの列 -------------------------------------------------------------

async def _report(session):
    freshness = await DerivedDataFreshnessQuery(session).get_freshness()
    return build_freshness_report(freshness, datetime(2026, 1, 1, tzinfo=timezone.utc))


@on_postgis
async def test_作り直した後に列を足した表と消した表と列の記録が無い表は作り直しが要る(road_graph_session):
    """列を足した表は足した列が全行NULLのまま、消した表は作ったときと宣言が違う。記録の無い表は、どの列で作ったかが分からない。"""
    added, removed, same, *unrecorded = DERIVED
    declared = declared_columns()
    dropped = value_columns(added)[0]
    async with raw_connection() as conn:
        await derived_data_meta.replace_columns(conn, {
            added.name: declared[added.name] - {dropped},
            removed.name: declared[removed.name] | {"removed_column"},
            same.name: declared[same.name],
        })

    report = await _report(road_graph_session)

    assert unrecorded
    assert [(t.table_name, t.columns_change, t.needs_rebuild) for t in report.tables] == [
        (added.name, ColumnsChange(added=(dropped,), removed=()), True),
        (removed.name, ColumnsChange(added=(), removed=("removed_column",)), True),
        (same.name, ColumnsChange(added=(), removed=()), False),
        *((table.name, None, True) for table in unrecorded),
    ]


@on_postgis
async def test_作り直した直後は値や行の無い道と区間があっても作り直しを求めない(road_graph_session, road_network_root):
    """区間に切れない道（同じ位置に点が重なる）は派生の表に行を持たず、標高と土地被覆のタイルが無い区間は値を持たない。
    どちらも作り直した結果なので、作り直しても消えない「作り直しが必要」を出さない。"""
    points = {1: (139.700, 35.680), 2: (139.701, 35.681), 3: (139.702, 35.680), 4: (139.702, 35.680)}
    await ingest_records(Source.OSM_NODE, [point_record(n, *point) for n, point in points.items()])
    await ingest_records(Source.OSM_WAY, [
        way_record(way_id, [points[n] for n in nodes], nodes) for way_id, nodes in ((100, [1, 2]), (200, [3, 4]))])
    await ingest_records(Source.ABR, [abr_prefecture_record("130001", "東京都", *points[1])])
    assert await derive_cli.run(postgis_database_url()) == 0

    report = await _report(road_graph_session)

    tables = {table.table_name: table for table in report.tables}
    # 前提: 道200は道の表に行が無く、道100の区間は標高も土地被覆も持たない。
    assert tables[derived_models.RoadWayRow.__tablename__].row_count == 1
    assert (tables[derived_models.EdgeElevationRow.__tablename__].row_count,
            tables[derived_models.EdgeLandcoverRow.__tablename__].row_count) == (0, 0)
    assert [source.source for source in report.sources if source.needs_rebuild] == []
    assert [table.table_name for table in report.tables if table.needs_rebuild] == []
