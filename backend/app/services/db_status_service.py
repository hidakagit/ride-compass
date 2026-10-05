"""本番DBの数を読み、注意が要るかの印を付けたレポートにするサービス層。

レポートの型は`GET /api/admin/db-status`の応答の型を兼ねる。
"""

import logging
import time
from datetime import datetime

from app.domain.db_status import connection_attention, table_attention
from app.domain.strict_model import StrictModel
from app.infrastructure.db_status import DbStatusCounts, DbStatusQuery
from app.infrastructure.debug_log import log_external_call
from app.infrastructure.source_models import SOURCE_RUN_STATUS_LABELS, SourceRunStatus

logger = logging.getLogger("ridecompass.db_status")

class LatestRunEntry(StrictModel):
    id: int
    status: str
    #: 走っている間はNone。
    finished_at: datetime | None
    #: runを識別する情報（PBF名・対象年・種別など、テーブルごとに中身が違う）。
    identity: dict[str, str]
    item_count: int | None


class SucceededRunEntry(StrictModel):
    id: int
    finished_at: datetime


class ImportRunEntry(StrictModel):
    """生データ取込1種別の最終実行。派生データの世代比較はこの記録を基準にするため、
    ここが失敗したままだと鮮度の判定そのものが古い基準の上で行われる。"""

    label: str
    #: 最新のrun。
    latest: LatestRunEntry
    #: 成功した最新のrun。成功が1件も無ければNone。
    latest_succeeded: SucceededRunEntry | None
    #: 最新runが成功していない。
    needs_attention: bool
    note: str


class TableEntry(StrictModel):
    """テーブル1つの実数・容量とメンテナンス状態。行数は統計値ではなく実数を数えている
    （統計はANALYZE前のテーブルで大きくずれ、取り込み漏れの検出に使えないため）。"""

    table_name: str
    row_count: int
    total_bytes: int
    dead_tuples: int
    analyzed_at: datetime | None
    vacuumed_at: datetime | None
    #: 統計が一度も取られていない、または不要行が溜まっている。
    needs_attention: bool
    note: str


class ConnectionEntry(StrictModel):
    total: int
    max_connections: int
    idle_in_transaction: int
    longest_idle_transaction_seconds: float
    longest_query_seconds: float
    needs_attention: bool
    note: str


class DbStatusReport(StrictModel):
    computed_at: datetime
    imports: list[ImportRunEntry]
    tables: list[TableEntry]
    connections: ConnectionEntry
    database_bytes: int


def _import_entry(counts) -> ImportRunEntry:
    failed = counts.latest_status != SourceRunStatus.SUCCEEDED
    note = ""
    if failed:
        note = f"最後の取込が「{SOURCE_RUN_STATUS_LABELS.get(counts.latest_status, counts.latest_status)}」。"
        if counts.latest_succeeded is not None:
            note += f"派生データの基準は成功した#{counts.latest_succeeded.id}のままで、それ以降の取り込みは反映されていない"
        else:
            note += "成功した取込が1件も無い"
    return ImportRunEntry(
        label=counts.label,
        latest=LatestRunEntry(
            id=counts.latest_id,
            status=counts.latest_status,
            finished_at=counts.latest_finished_at,
            identity=dict(counts.latest_identity),
            item_count=counts.latest_item_count,
        ),
        latest_succeeded=(
            None
            if counts.latest_succeeded is None
            else SucceededRunEntry(id=counts.latest_succeeded.id, finished_at=counts.latest_succeeded.finished_at)
        ),
        needs_attention=failed,
        note=note,
    )


def _table_entry(counts) -> TableEntry:
    reasons = table_attention(counts.row_count, counts.dead_tuples, analyzed=counts.analyzed_at is not None)
    return TableEntry(
        table_name=counts.table_name,
        row_count=counts.row_count,
        total_bytes=counts.total_bytes,
        dead_tuples=counts.dead_tuples,
        analyzed_at=counts.analyzed_at,
        vacuumed_at=counts.vacuumed_at,
        needs_attention=bool(reasons),
        note="／".join(reasons),
    )


def _connection_entry(counts) -> ConnectionEntry:
    reasons = connection_attention(counts.total, counts.max_connections, counts.longest_idle_transaction_seconds)
    return ConnectionEntry(
        total=counts.total,
        max_connections=counts.max_connections,
        idle_in_transaction=counts.idle_in_transaction,
        longest_idle_transaction_seconds=counts.longest_idle_transaction_seconds,
        longest_query_seconds=counts.longest_query_seconds,
        needs_attention=bool(reasons),
        note="／".join(reasons),
    )


def build_db_status_report(counts: DbStatusCounts, computed_at: datetime) -> DbStatusReport:
    return DbStatusReport(
        computed_at=computed_at,
        imports=[_import_entry(entry) for entry in counts.imports],
        tables=[_table_entry(entry) for entry in counts.tables],
        connections=_connection_entry(counts.connections),
        database_bytes=counts.database_bytes,
    )


class DbStatusService:
    def __init__(self, repository: DbStatusQuery):
        self._repository = repository

    async def get_status_report(self) -> DbStatusReport:
        started = time.monotonic()
        with log_external_call("admin:db-status", operation="fetch_counts") as fields:
            counts = await self._repository.fetch_counts()
            fields["tables"] = len(counts.tables)
        report = build_db_status_report(counts, datetime.now().astimezone())
        logger.info(
            "db-status 集計完了 tables=%d 要注意=%d elapsed_ms=%d",
            len(report.tables),
            sum(entry.needs_attention for entry in report.tables),
            round((time.monotonic() - started) * 1000),
        )
        return report
