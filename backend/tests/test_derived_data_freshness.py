"""鮮度台帳（`infrastructure/derived_data_freshness.py`）と、それを画面の判定へ組むレポート
（`services/derived_data_freshness_service.py: build_freshness_report`）の契約。

この台帳は**対象を宣言から導く**（表の印`orm_base.py: DERIVED`を持つ表が派生データ）。表や列が増えても
手当てが要らないことが値打ちなので、ここで見るのは個々の表の名前ではなく、導出の規則である: 派生の表・値の列・
NULLの意味・被覆の親の導き方、ソースごとの鮮度（DBで）、作り直しが要るかの判定。

ここで見ないもの:
- 集計SQLが未計算と確定した値なしを分けて数えること → `test_derive_landcover.py`（有効画素の足りない区間をDBで数える）
"""

from dataclasses import replace

import asyncpg
import pytest

from app.batch.common import asyncpg_dsn
from app.infrastructure import derived_data_meta, derived_models
from app.infrastructure.derived_data_freshness import (
    ColumnCompleteness,
    Coverage,
    DerivedDataFreshness,
    DerivedDataFreshnessQuery,
    TableFreshness,
    absent_condition,
    build_coverage_sql,
    covered_source,
    coverage_parent,
    derived_tables,
    parent_derived_table,
    value_columns,
)
from app.infrastructure.orm_base import Base
from app.infrastructure.source_models import Source
from app.services.derived_data_freshness_service import build_freshness_report
from tests.conftest import postgis_database_url
from tests.source_ingest import ingest_records, point_record

from datetime import datetime, timezone

DERIVED = derived_tables()


def on_postgis(test):
    """DBで確かめるテストにだけ付ける。ほかのテストはDBの無い環境でも走る。"""
    for mark in (pytest.mark.asyncio(loop_scope="module"), pytest.mark.xdist_group(name="postgis"), pytest.mark.postgis):
        test = mark(test)
    return test


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


# --- NULLの意味 -------------------------------------------------------------

@pytest.mark.parametrize(("marked", "condition"), [
    # 印の付け忘れは「鳴りすぎる」側へ倒れる。黙って見逃す側へ倒れてはいけない。
    (lambda info: not info, "FALSE"),
    # `ABSENT_OK`を付けた列（橋の勾配・指定のない道など）。
    (lambda info: info.get("null_means_absent"), "TRUE"),
], ids=["印の無い列は未計算", "確定して値が無い列は数えない"])
def test_NULLを確定して値なしと読むかは列の印で決まる(marked, condition):
    table, name = next((table, name) for table in DERIVED for name in value_columns(table)
                       if marked(table.c[name].info))

    assert absent_condition(table, name) == condition


# --- ソースごとの鮮度 -------------------------------------------------------

def _breaks_midway():
    yield point_record(1, 139.7, 35.6)
    raise OSError("配信元が途中で切れた")


@on_postgis
async def test_作り直しに使った取込が成功した最新の取込でないソースは作り直しが要る(road_graph_session):
    """取り直したソース・まだ作り直しに使っていないソース・取込が1度も成功していないソースが、作り直しが要る側に出る。"""
    way_run = await ingest_records(Source.OSM_WAY, [])
    accident_run = await ingest_records(Source.ACCIDENT, [])
    conn = await asyncpg.connect(asyncpg_dsn(postgis_database_url()))
    try:
        await derived_data_meta.replace_source_runs(conn, {Source.OSM_WAY: way_run, Source.ACCIDENT: accident_run})
    finally:
        await conn.close()
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


# --- レポートの組み立て -----------------------------------------------------

def _table() -> TableFreshness:
    return TableFreshness(table_name="t", row_count=1, columns=(), coverage=None)


# --- 被覆（行そのものが無いケース）---------------------------------------

def test_覆うことを宣言しない表は母数を持たない():
    """印の無い表まで測ると、設計どおり行を作らなかったぶんが欠けとして鳴り続ける。"""
    table = next(t for t in DERIVED if covered_source(t) is None and parent_derived_table(t) is None)

    assert build_coverage_sql(table) is None
    assert coverage_parent(table) is None


def test_親は自分の主キーが指す先だけ():
    """主キー以外の列のFK（区間の端点→ノード）を母数にすると、覆っていない側を欠けとして
    数える。`road_edges`は端点で`node_materials`を指すが、親ではない。"""
    children = [(table, parent) for table in DERIVED if (parent := parent_derived_table(table)) is not None]
    assert children, "親を持つ派生表が1つも無い"
    for table, (_, columns) in children:
        assert [child for _, child in columns] == [c.name for c in table.primary_key.columns]


@on_postgis
async def test_生データの母数は覆うと宣言したソースの行だけを数える(road_graph_session):
    """絞らないと`source_features`の全ソース（標高タイル・事故点）まで母数に入る。"""
    await ingest_records(Source.ACCIDENT, [point_record(1, 139.7, 35.6)])

    freshness = await DerivedDataFreshnessQuery(road_graph_session).get_freshness()

    counts = [table.coverage.parent_row_count for table in freshness.tables if table.coverage is not None]
    assert counts
    assert all(count == 0 for count in counts)


@pytest.mark.parametrize(("missing", "expected"), [(0, False), (1, True)])
def test_行が欠けたかは被覆の欠けの件数で決まる(missing, expected):
    """行が無ければ値の列もNULLにならないので、完成度では分からない。"""
    table = replace(_table(), coverage=Coverage(parent="osm_way", parent_row_count=10,
                                                missing_rows=missing))
    assert table.has_missing_rows is expected


@pytest.mark.parametrize(("table", "expected"), [
    (replace(_table(), coverage=Coverage(parent="osm_way", parent_row_count=10, missing_rows=1)), True),
    (replace(_table(), columns=(ColumnCompleteness(column="c", uncalculated_count=3, absent_count=0),)),
     True),                 # 値の列に未計算が残る
    (replace(_table(), columns=(ColumnCompleteness(column="c", uncalculated_count=0, absent_count=3),)),
     False),                # 確定した値なしは作り直しでは埋まらない
], ids=["行が欠ける", "未計算", "確定した値なし"])
def test_作り直しが要るかはレポートが決める(table, expected):
    entry = build_freshness_report(DerivedDataFreshness(sources=(), tables=(table,)),
                                   datetime(2026, 1, 1, tzinfo=timezone.utc)).tables[0]

    assert entry.needs_rebuild is expected
