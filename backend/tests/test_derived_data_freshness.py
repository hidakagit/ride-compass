"""鮮度台帳（`infrastructure/derived_data_freshness.py`）の契約。

この台帳は**対象を宣言から導く**（`source_run_id`を持つ表が派生データ）。表や列が増えても
手当てが要らないことが値打ちなので、ここで見るのは個々の表の名前ではなく、導出の規則が
全ての派生表に対して成り立つことである。
"""

from dataclasses import replace

import pytest

from app.infrastructure.derived_data_freshness import (
    SOURCE_RUN_COLUMN,
    ColumnCompleteness,
    Coverage,
    DerivedDataFreshness,
    TableFreshness,
    build_coverage_sql,
    build_table_sql,
    counts_as_uncalculated,
    covered_source,
    coverage_parent,
    derived_tables,
    parent_derived_table,
    value_columns,
)
from app.services.derived_data_freshness_service import build_freshness_report

from datetime import datetime, timezone

DERIVED = derived_tables()


# --- 対象の導出 -------------------------------------------------------------

def test_派生表は宣言から導かれる():
    """1つでも導けていないと、その表の鮮度は永久に画面へ出ない。"""
    assert DERIVED, "source_run_idを持つ表が1つも無い"
    for table in DERIVED:
        assert SOURCE_RUN_COLUMN in table.c


def test_系譜を持たない表は対象に入らない():
    """生データ（`source_features`）自身や軸定義まで数えると、鮮度の意味が変わる。"""
    names = {table.name for table in DERIVED}
    assert "source_features" not in names
    assert "source_runs" not in names


@pytest.mark.parametrize("table", DERIVED, ids=lambda t: t.name)
def test_値の列は鍵と系譜を含まない(table):
    """鍵はNULLになりえず、系譜は値ではない。数えると常に「未計算0件」の行が並ぶ。"""
    keys = {column.name for column in table.primary_key.columns} | {SOURCE_RUN_COLUMN}
    assert keys.isdisjoint(value_columns(table))


@pytest.mark.parametrize("table", DERIVED, ids=lambda t: t.name)
def test_値の列が1本以上ある(table):
    assert value_columns(table)


# --- 集計SQLの組み立て -------------------------------------------------------

@pytest.mark.parametrize("table", DERIVED, ids=lambda t: t.name)
def test_集計SQLは宣言にある名前だけで組む(table):
    """列名を外部入力から組まないこと。ここが崩れると管理APIがSQL注入の口になる。"""
    sql = build_table_sql(table)
    declared = {column.name for column in table.columns}
    for name in value_columns(table):
        assert f"count(*) FILTER (WHERE {name} IS NULL) AS null_{name}" in sql
        assert name in declared
    assert sql.endswith(f"FROM {table.name}")


@pytest.mark.parametrize("table", DERIVED, ids=lambda t: t.name)
def test_集計SQLは1回の走査で済ませる(table):
    """表ごとに列の本数ぶんクエリを投げると、管理APIの1回が数十クエリになる。"""
    assert build_table_sql(table).count("SELECT") == 1


# --- NULLの意味 -------------------------------------------------------------

def test_印の無い列は未計算として数える():
    """印の付け忘れは「鳴りすぎる」側へ倒れる。黙って見逃す側へ倒れてはいけない。"""
    table = DERIVED[0]
    name = next(n for n in value_columns(table) if not table.c[n].info.get("null_means_absent"))
    assert counts_as_uncalculated(table, name) is True


def test_確定して値が無い列は数えない():
    """`ABSENT_OK`を付けた列（橋の勾配・指定のない道など）。"""
    marked = [(table, name) for table in DERIVED for name in value_columns(table)
              if table.c[name].info.get("null_means_absent")]
    assert marked, "ABSENT_OKの列が1つも無い（印の仕組みが効いていない）"
    for table, name in marked:
        assert counts_as_uncalculated(table, name) is False


# --- 古さの判定 -------------------------------------------------------------

def _table(oldest: int | None, latest: int | None) -> TableFreshness:
    return TableFreshness(table_name="t", row_count=1, oldest_run_id=oldest,
                          source="osm_way", latest_run_id=latest, columns=())


@pytest.mark.parametrize(("oldest", "latest", "stale"), [
    (1, 2, True),    # 生データを取り直したのに派生を流し直していない
    (2, 2, False),   # 追いついている
    (3, 2, False),   # 派生の方が新しい（成功runの判定より後に流した）
    (None, 2, False),  # 行が無い
    (1, None, False),  # 成功したrunがまだ無い
])
def test_古いかどうかは世代の比較で決まる(oldest, latest, stale):
    assert _table(oldest, latest).is_stale is stale


# --- レポートの組み立て -----------------------------------------------------

def _report(column: ColumnCompleteness):
    freshness = DerivedDataFreshness(tables=(replace(_table(1, 1), columns=(column,)),))
    return build_freshness_report(freshness, datetime(2026, 1, 1, tzinfo=timezone.utc))


@pytest.mark.parametrize(("null_count", "counts", "incomplete"), [
    (3, True, True),    # 未計算が残っている
    (0, True, False),   # 全部計算済み
    (3, False, False),  # NULLだが「確定して値が無い」列
])
def test_未計算の判定は件数と印の両方を見る(null_count, counts, incomplete):
    report = _report(ColumnCompleteness(column="c", null_count=null_count,
                                        counts_as_uncalculated=counts))
    entry = report.tables[0].columns[0]
    assert entry.is_incomplete is incomplete
    assert entry.null_count == null_count, "鳴らさない列でも件数は返す"


# --- 被覆（行そのものが無いケース）---------------------------------------

def test_覆うことを宣言した表だけが母数を持つ():
    """印の無い表まで測ると、設計どおり行を作らなかったぶんが欠けとして鳴り続ける。"""
    declared = {table.name for table in DERIVED if covered_source(table)}
    assert declared, "coversを宣言した表が1つも無い"
    for table in DERIVED:
        if covered_source(table) is None and parent_derived_table(table) is None:
            assert build_coverage_sql(table) is None
            assert coverage_parent(table) is None


def test_親は自分の主キーが指す先だけ():
    """主キー以外の列のFK（区間の端点→ノード）を母数にすると、覆っていない側を欠けとして
    数える。`road_edges`は端点で`node_materials`を指すが、親ではない。"""
    for table in DERIVED:
        parent = parent_derived_table(table)
        if parent is None:
            continue
        _, columns = parent
        assert [child for _, child in columns] == [c.name for c in table.primary_key.columns]


def test_生データの母数はソース名で絞る():
    """絞らないと`source_features`の全ソース（標高タイル・事故点）まで母数に入る。"""
    table = next(t for t in DERIVED if covered_source(t))
    sql = build_coverage_sql(table)
    assert "WHERE f.source = :source" in sql


@pytest.mark.parametrize("table", DERIVED, ids=lambda t: t.name)
def test_被覆SQLは宣言にある名前だけで組む(table):
    sql = build_coverage_sql(table)
    if sql is None:
        return
    declared = {column.name for column in table.columns}
    quoted = [word for word in sql.replace("(", " ").replace(")", " ").split()
              if word.startswith("d.")]
    assert quoted, f"{table.name}の被覆SQLが派生表の列を1つも引いていない"
    for word in quoted:
        assert word.removeprefix("d.") in declared


@pytest.mark.parametrize(("missing", "expected"), [(0, False), (1, True)])
def test_行が無いことは鮮度でも完成度でも分からない(missing, expected):
    """行が無ければ`source_run_id`は古くならず、値の列もNULLにならない。"""
    table = replace(_table(2, 2), coverage=Coverage(parent="osm_way", parent_row_count=10,
                                                    missing_rows=missing))
    assert table.is_stale is False
    assert table.has_missing_rows is expected


def test_レポートは母数と欠けをそのまま渡す():
    freshness = DerivedDataFreshness(tables=(
        replace(_table(1, 1),
                coverage=Coverage(parent="osm_way", parent_row_count=12029, missing_rows=3)),))
    entry = build_freshness_report(freshness, datetime(2026, 1, 1, tzinfo=timezone.utc)).tables[0]

    assert (entry.coverage_parent, entry.coverage_parent_row_count, entry.missing_rows) == (
        "osm_way", 12029, 3)


@pytest.mark.parametrize(("table", "expected"), [
    (_table(2, 2), False),
    (_table(1, 2), True),   # 取込より古い
    (replace(_table(2, 2), coverage=Coverage(parent="osm_way", parent_row_count=10, missing_rows=1)), True),
    (replace(_table(2, 2), columns=(ColumnCompleteness(column="c", null_count=3, counts_as_uncalculated=True),)),
     True),                 # 値の列に未計算が残る
    (replace(_table(2, 2), columns=(ColumnCompleteness(column="c", null_count=3, counts_as_uncalculated=False),)),
     False),                # 確定した値なしは作り直しでは埋まらない
], ids=["最新", "古い", "行が欠ける", "未計算", "確定した値なし"])
def test_作り直しが要るかはレポートが決める(table, expected):
    entry = build_freshness_report(DerivedDataFreshness(tables=(table,)),
                                   datetime(2026, 1, 1, tzinfo=timezone.utc)).tables[0]

    assert entry.needs_rebuild is expected


def test_覆わない表はNoneのまま渡る():
    entry = build_freshness_report(
        DerivedDataFreshness(tables=(_table(1, 1),)),
        datetime(2026, 1, 1, tzinfo=timezone.utc)).tables[0]

    assert (entry.coverage_parent, entry.missing_rows) == (None, None)
