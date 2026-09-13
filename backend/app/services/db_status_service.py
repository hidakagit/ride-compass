"""本番DBの状態を「注意が要るか」まで判定してレポートにするサービス層。

`infrastructure/db_status.py`が数えた生値を受け取り、読み手が見るべきものだけが目に入る形へ
畳む（`derived_data_freshness_service.py`と同じ役割分担——リポジトリは数えるだけ、
判定はここ、表示はfrontend）。

**判定のしきい値はこのモジュールが持つ**。しきい値そのものより「なぜその値か」が重要なため、
定数ごとに根拠を書く。
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime

from app.infrastructure.db_status import DbStatusCounts, DbStatusQuery, RoadGraphTile
from app.infrastructure.debug_log import log_external_call

logger = logging.getLogger("ridecompass.db_status")

#: `idle in transaction`がこれより長く続いていれば注意。放置されたトランザクションは
#: VACUUMが古い行を回収するのを止め、テーブルを肥大化させる（T714が別角度で扱う問題）。
#: 本番のルート生成は冷パスでも最大316秒の実測のため、通常の処理で超える値ではない。
IDLE_TRANSACTION_WARN_SECONDS = 600.0

#: 接続数がmax_connectionsのこの割合を超えたら注意（残り枠が尽きると新規接続が失敗する）。
CONNECTION_USAGE_WARN_RATIO = 0.8

#: 不要行（dead tuple）が行全体のこの割合を超えたら注意。VACUUMが追いついていない。
DEAD_TUPLE_WARN_RATIO = 0.2

#: 統計が無いことを注意として出す行数の下限。これを下回るテーブルは、プランナが行数を
#: どう推定しても全走査で足りるため実行計画が変わらない——注意を出しても打つ手が無い。
STATISTICS_WARN_MIN_ROWS = 10_000

#: 不要行を注意として出す絶対数の下限。割合だけで見ると、行数の少ないテーブル（軸定義は
#: 15行に対し不要行38件）が常に注意になるが、回収できる容量が無く行動につながらない。
DEAD_TUPLE_WARN_MIN_ROWS = 1_000


@dataclass(frozen=True)
class ImportRunEntry:
    label: str
    latest_id: int | None
    latest_status: str | None
    latest_finished_at: datetime | None
    latest_identity: dict[str, str]
    latest_item_count: int | None
    latest_succeeded_id: int | None
    latest_succeeded_finished_at: datetime | None
    #: 最新runが成功していない（失敗したまま、または記録が1件も無い）。
    needs_attention: bool
    note: str


@dataclass(frozen=True)
class TableEntry:
    table_name: str
    row_count: int
    total_bytes: int
    dead_tuples: int
    analyzed_at: datetime | None
    vacuumed_at: datetime | None
    #: 統計が一度も取られていない、または不要行が溜まっている。
    needs_attention: bool
    note: str


@dataclass(frozen=True)
class ConnectionEntry:
    total: int
    max_connections: int
    idle_in_transaction: int
    longest_idle_transaction_seconds: float
    longest_query_seconds: float
    needs_attention: bool
    note: str


@dataclass(frozen=True)
class DbStatusReport:
    computed_at: datetime
    imports: list[ImportRunEntry]
    tables: list[TableEntry]
    connections: ConnectionEntry
    database_bytes: int


def _import_entry(counts) -> ImportRunEntry:
    if counts.latest_id is None:
        return ImportRunEntry(
            label=counts.label,
            latest_id=None,
            latest_status=None,
            latest_finished_at=None,
            latest_identity={},
            latest_item_count=None,
            latest_succeeded_id=None,
            latest_succeeded_finished_at=None,
            needs_attention=True,
            note="取込の記録が1件も無い。派生データの世代比較はこの記録を基準にするため、基準そのものが無い",
        )
    failed = counts.latest_status != "succeeded"
    note = ""
    if failed:
        note = f"最後の取込が{counts.latest_status}のまま。"
        if counts.latest_succeeded_id is not None:
            note += f"派生データの基準は成功した#{counts.latest_succeeded_id}のままで、それ以降の取り込みは反映されていない"
        else:
            note += "成功した取込が1件も無い"
    return ImportRunEntry(
        label=counts.label,
        latest_id=counts.latest_id,
        latest_status=counts.latest_status,
        latest_finished_at=counts.latest_finished_at,
        latest_identity=dict(counts.latest_identity),
        latest_item_count=counts.latest_item_count,
        latest_succeeded_id=counts.latest_succeeded_id,
        latest_succeeded_finished_at=counts.latest_succeeded_finished_at,
        needs_attention=failed,
        note=note,
    )


def _table_entry(counts) -> TableEntry:
    reasons: list[str] = []
    if counts.analyzed_at is None and counts.row_count >= STATISTICS_WARN_MIN_ROWS:
        reasons.append(
            "統計を一度も取っていない（プランナの行数推定が実数から外れ、クエリが遅いプランを選びうる）"
        )
    live = max(counts.row_count, 1)
    dead_ratio = counts.dead_tuples / (live + counts.dead_tuples)
    if counts.dead_tuples >= DEAD_TUPLE_WARN_MIN_ROWS and dead_ratio > DEAD_TUPLE_WARN_RATIO:
        reasons.append(f"不要行が{counts.dead_tuples:,}件（VACUUMが追いついていない）")
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
    reasons: list[str] = []
    if counts.longest_idle_transaction_seconds > IDLE_TRANSACTION_WARN_SECONDS:
        minutes = counts.longest_idle_transaction_seconds / 60
        reasons.append(
            f"開いたまま放置されたトランザクションが{minutes:.0f}分（VACUUMが古い行を回収できず肥大化する）"
        )
    if counts.max_connections and counts.total / counts.max_connections > CONNECTION_USAGE_WARN_RATIO:
        reasons.append(f"接続が{counts.total}/{counts.max_connections}（残り枠が尽きると新規接続が失敗する）")
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

    async def get_road_graph_tiles(self) -> tuple[RoadGraphTile, ...]:
        """split済みタイルの全件。良し悪しの判定は持たない——「どこが済んでいるか」は
        件数ではなく地図の形でしか読めないため、判断は見る人に委ねる。"""
        return await self._repository.fetch_road_graph_tiles()

    async def get_status_report(self) -> DbStatusReport:
        started = time.monotonic()
        with log_external_call("db_status", operation="fetch_counts") as fields:
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
