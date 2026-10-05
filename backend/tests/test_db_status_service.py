"""`services/db_status_service.py`——DBの数を、管理画面で「注意が要るか」の印を付けたレポートにする判断。

入口は`build_db_status_report`（数を値で受ける）。しきい値の境界の入力は本物の定数から組み立てる。

ここで見ないもの: 数の読み出し → `infrastructure/db_status.py`、応答への受け渡し・503 → `test_db_status_routes.py`
"""

from datetime import datetime, timezone

import pytest

from app.infrastructure.db_status import (
    ConnectionCounts,
    DbStatusCounts,
    ImportRunCounts,
    SucceededRunCounts,
    TableCounts,
)
from app.services.db_status_service import (
    CONNECTION_USAGE_WARN_RATIO,
    DEAD_TUPLE_WARN_MIN_ROWS,
    DEAD_TUPLE_WARN_RATIO,
    IDLE_TRANSACTION_WARN_SECONDS,
    STATISTICS_WARN_MIN_ROWS,
    build_db_status_report,
)

AT = datetime(2026, 9, 14, tzinfo=timezone.utc)
MAX_CONNECTIONS = 100
#: 接続の割合のしきい値ちょうどの接続数（これを超えると注意）。
AT_CONNECTION_LIMIT = round(MAX_CONNECTIONS * CONNECTION_USAGE_WARN_RATIO)


def _table(*, rows: int = 100, dead: int = 0, analyzed: datetime | None = AT) -> TableCounts:
    return TableCounts(table_name="road_edges", row_count=rows, total_bytes=0, dead_tuples=dead,
                       analyzed_at=analyzed, vacuumed_at=AT)


def _connections(*, total: int = 2, longest_idle: float = 0.0) -> ConnectionCounts:
    return ConnectionCounts(total=total, max_connections=MAX_CONNECTIONS, idle_in_transaction=0,
                            longest_idle_transaction_seconds=longest_idle, longest_query_seconds=0.0)


def _import(status: str, succeeded: SucceededRunCounts | None) -> ImportRunCounts:
    return ImportRunCounts(label="OSM取込", latest_id=5, latest_status=status, latest_finished_at=AT,
                           latest_identity={}, latest_item_count=None, latest_succeeded=succeeded)


def _report(*, tables=(), connections=None, imports=()):
    return build_db_status_report(
        DbStatusCounts(imports=tuple(imports), tables=tuple(tables), connections=connections or _connections(),
                       database_bytes=0),
        AT,
    )


#: 不要行が行全体に占める割合がしきい値を超える生きた行の数（不要行の数を固定したとき）。
def _live_rows_for_dead_share_above_threshold(dead: int) -> int:
    return int(dead * (1 - DEAD_TUPLE_WARN_RATIO) / DEAD_TUPLE_WARN_RATIO) - 1


@pytest.mark.parametrize(("table", "needs_attention"), [
    (_table(rows=STATISTICS_WARN_MIN_ROWS, analyzed=None), True),
    (_table(rows=STATISTICS_WARN_MIN_ROWS - 1, analyzed=None), False),  # 小さな表は全走査で足りる
    (_table(rows=STATISTICS_WARN_MIN_ROWS), False),  # 統計がある
    (_table(rows=_live_rows_for_dead_share_above_threshold(DEAD_TUPLE_WARN_MIN_ROWS), dead=DEAD_TUPLE_WARN_MIN_ROWS),
     True),
    # 割合は超えても、数が少なければ回収できる容量が無い
    (_table(rows=_live_rows_for_dead_share_above_threshold(DEAD_TUPLE_WARN_MIN_ROWS - 1),
            dead=DEAD_TUPLE_WARN_MIN_ROWS - 1), False),
    # 数は多くても、割合がしきい値以下なら VACUUM が追いついている
    (_table(rows=DEAD_TUPLE_WARN_MIN_ROWS * 4, dead=DEAD_TUPLE_WARN_MIN_ROWS), False),
])
def test_a_table_needs_attention_without_statistics_or_with_many_dead_rows(table, needs_attention):
    (entry,) = _report(tables=[table]).tables

    assert entry.needs_attention is needs_attention


@pytest.mark.parametrize(("connections", "needs_attention"), [
    (_connections(longest_idle=IDLE_TRANSACTION_WARN_SECONDS + 1), True),
    (_connections(longest_idle=IDLE_TRANSACTION_WARN_SECONDS), False),
    (_connections(total=AT_CONNECTION_LIMIT + 1), True),
    (_connections(total=AT_CONNECTION_LIMIT), False),
])
def test_connections_need_attention_when_a_transaction_is_left_open_or_slots_run_out(connections, needs_attention):
    assert _report(connections=connections).connections.needs_attention is needs_attention


def test_a_failed_import_says_which_run_the_derived_data_still_stands_on():
    (failed, never, succeeded) = _report(imports=[
        _import("failed", SucceededRunCounts(4, AT)),
        _import("failed", None),
        _import("succeeded", SucceededRunCounts(5, AT)),
    ]).imports

    assert failed.needs_attention and "#4" in failed.note
    assert never.needs_attention and "1件も無い" in never.note
    assert not succeeded.needs_attention and succeeded.note == ""
