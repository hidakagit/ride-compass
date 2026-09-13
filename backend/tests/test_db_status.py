"""本番DB状態の判定（services/db_status_service.py）とSQL組み立ての単体テスト。

DB接続は要らない——生値から「注意が要るか」を決める部分だけを対象にする（実DBに対する
動作は`infrastructure/db_status.py`のSQLが担い、そちらは管理APIの実行で確かめる）。
"""

from datetime import datetime, timezone

from app.infrastructure.db_status import (
    IMPORT_RUN_SPECS,
    ConnectionCounts,
    DbStatusCounts,
    ImportRunCounts,
    TableCounts,
    build_latest_import_run_sql,
)
from app.services.db_status_service import (
    DEAD_TUPLE_WARN_MIN_ROWS,
    STATISTICS_WARN_MIN_ROWS,
    build_db_status_report,
)

COMPUTED_AT = datetime(2026, 9, 14, tzinfo=timezone.utc)
ANALYZED = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _counts(*, imports=(), tables=(), connections=None) -> DbStatusCounts:
    return DbStatusCounts(
        imports=tuple(imports),
        tables=tuple(tables),
        connections=connections
        or ConnectionCounts(
            total=2,
            max_connections=100,
            idle_in_transaction=0,
            longest_idle_transaction_seconds=0.0,
            longest_query_seconds=0.0,
        ),
        database_bytes=1024,
    )


def _import(label="OSM取込", *, latest_id=4, status="succeeded", succeeded_id=4) -> ImportRunCounts:
    return ImportRunCounts(
        label=label,
        latest_id=latest_id,
        latest_status=status,
        latest_finished_at=ANALYZED,
        latest_identity={"pbf_name": "kanto-latest.osm.pbf"},
        latest_item_count=1_329_632,
        latest_succeeded_id=succeeded_id,
        latest_succeeded_finished_at=ANALYZED,
    )


def _table(name="road_edges", *, rows=5_000_000, dead=0, analyzed=ANALYZED) -> TableCounts:
    return TableCounts(
        table_name=name,
        row_count=rows,
        total_bytes=1024,
        dead_tuples=dead,
        analyzed_at=analyzed,
        vacuumed_at=analyzed,
    )


def test_import_run_that_succeeded_needs_no_attention():
    report = build_db_status_report(_counts(imports=[_import()]), COMPUTED_AT)

    assert report.imports[0].needs_attention is False
    assert report.imports[0].note == ""


def test_failed_import_says_which_run_the_derived_data_still_stands_on():
    # 「失敗した」だけでは何が起きているか分からない。派生データの基準が成功した古いrunの
    # ままであることまで示さないと、鮮度タブが「最新」と出す意味を読み違える。
    report = build_db_status_report(
        _counts(imports=[_import(latest_id=5, status="failed", succeeded_id=4)]), COMPUTED_AT
    )

    entry = report.imports[0]
    assert entry.needs_attention is True
    assert "#4" in entry.note


def test_import_with_no_record_at_all_is_flagged():
    # 記録が1件も無いと、派生データの世代比較が拠って立つ基準そのものが無い。
    empty = ImportRunCounts(
        label="OSM取込",
        latest_id=None,
        latest_status=None,
        latest_finished_at=None,
        latest_identity={},
        latest_item_count=None,
        latest_succeeded_id=None,
        latest_succeeded_finished_at=None,
    )
    report = build_db_status_report(_counts(imports=[empty]), COMPUTED_AT)

    assert report.imports[0].needs_attention is True


def test_large_table_without_statistics_is_flagged():
    report = build_db_status_report(
        _counts(tables=[_table(rows=STATISTICS_WARN_MIN_ROWS, analyzed=None)]), COMPUTED_AT
    )

    assert report.tables[0].needs_attention is True
    assert "統計" in report.tables[0].note


def test_small_table_without_statistics_is_not_flagged():
    # 小さいテーブルはプランナが行数をどう推定しても全走査で足り、注意を出しても打つ手が無い。
    report = build_db_status_report(
        _counts(tables=[_table(rows=STATISTICS_WARN_MIN_ROWS - 1, analyzed=None)]), COMPUTED_AT
    )

    assert report.tables[0].needs_attention is False


def test_dead_tuples_need_both_a_share_and_a_count():
    # 割合だけで見ると、行数の少ないテーブルが常に注意になる（回収できる容量が無いのに）。
    many_but_small_share = build_db_status_report(
        _counts(tables=[_table(rows=1_000_000, dead=DEAD_TUPLE_WARN_MIN_ROWS)]), COMPUTED_AT
    )
    assert many_but_small_share.tables[0].needs_attention is False

    big_share_but_few = build_db_status_report(
        _counts(tables=[_table(rows=10, dead=DEAD_TUPLE_WARN_MIN_ROWS - 1)]), COMPUTED_AT
    )
    assert big_share_but_few.tables[0].needs_attention is False

    both = build_db_status_report(
        _counts(tables=[_table(rows=1_000, dead=DEAD_TUPLE_WARN_MIN_ROWS)]), COMPUTED_AT
    )
    assert both.tables[0].needs_attention is True


def test_long_idle_transaction_is_flagged_with_why_it_matters():
    report = build_db_status_report(
        _counts(
            connections=ConnectionCounts(
                total=2,
                max_connections=100,
                idle_in_transaction=1,
                longest_idle_transaction_seconds=3600.0,
                longest_query_seconds=0.0,
            )
        ),
        COMPUTED_AT,
    )

    assert report.connections.needs_attention is True
    assert "VACUUM" in report.connections.note


def test_connection_usage_near_the_limit_is_flagged():
    report = build_db_status_report(
        _counts(
            connections=ConnectionCounts(
                total=90,
                max_connections=100,
                idle_in_transaction=0,
                longest_idle_transaction_seconds=0.0,
                longest_query_seconds=0.0,
            )
        ),
        COMPUTED_AT,
    )

    assert report.connections.needs_attention is True


def test_latest_import_run_sql_uses_the_declared_columns():
    # 件数列・識別列はテーブルごとに違う。宣言から組み立てていなければ、どれかのテーブルで
    # 存在しない列を読んで落ちる。
    for spec in IMPORT_RUN_SPECS:
        sql = str(build_latest_import_run_sql(spec))
        assert f"FROM {spec.table}" in sql
        assert spec.count_column in sql
        for column in spec.identity_columns:
            assert column in sql
