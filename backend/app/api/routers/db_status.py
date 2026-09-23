"""本番DBの状態を返す管理API。

`GET /api/admin/db-status`（Basic認証必須）は、派生データの鮮度
（`derived_data_freshness.py`）が拠って立つ**土台**の側を返す——生データ取込そのものが
失敗していないか、行が本当に入っているか、プランナが使う統計が取れているか、
トランザクションが放置されていないか。

認可を要求する理由・DB例外の扱いは`get_derived_data_freshness`と同じ（全表走査を伴うため
認可なしに公開しない、DB例外は503へ変換し空レポートへ倒さない）。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import DBAPIError

from app.api.admin_auth import require_admin_basic_auth
from app.api.dependencies import get_db_status_service
from app.domain.strict_model import StrictModel
from app.services.db_status_service import DbStatusService

router = APIRouter()


class ImportRunEntry(StrictModel):
    """生データ取込1種別の最終実行。派生データの世代比較はこの記録を基準にするため、
    ここが失敗したままだと鮮度の判定そのものが古い基準の上で行われる。"""

    label: str
    latest_id: int | None
    latest_status: str | None
    latest_finished_at: str | None
    #: runを識別する情報（PBF名・対象年・種別など、テーブルごとに中身が違う）。
    latest_identity: dict[str, str]
    latest_item_count: int | None
    latest_succeeded_id: int | None
    latest_succeeded_finished_at: str | None
    needs_attention: bool
    note: str


class TableEntry(StrictModel):
    """テーブル1つの実数・容量とメンテナンス状態。行数は統計値ではなく実数を数えている
    （統計はANALYZE前のテーブルで大きくずれ、取り込み漏れの検出に使えないため）。"""

    table_name: str
    row_count: int
    total_bytes: int
    dead_tuples: int
    analyzed_at: str | None
    vacuumed_at: str | None
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


class DbStatusResponse(StrictModel):
    computed_at: str
    imports: list[ImportRunEntry]
    tables: list[TableEntry]
    connections: ConnectionEntry
    database_bytes: int


def _iso(value) -> str | None:
    return None if value is None else value.isoformat()


@router.get(
    "/api/admin/db-status",
    response_model=DbStatusResponse,
    dependencies=[Depends(require_admin_basic_auth)],
)
async def get_db_status(
    service: DbStatusService = Depends(get_db_status_service),
) -> DbStatusResponse:
    try:
        report = await service.get_status_report()
    except DBAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DB状態の集計に失敗しました（DB接続・migration適用状況を確認してください）",
        ) from exc
    return DbStatusResponse(
        computed_at=report.computed_at.isoformat(),
        imports=[
            ImportRunEntry(
                label=entry.label,
                latest_id=entry.latest_id,
                latest_status=entry.latest_status,
                latest_finished_at=_iso(entry.latest_finished_at),
                latest_identity=entry.latest_identity,
                latest_item_count=entry.latest_item_count,
                latest_succeeded_id=entry.latest_succeeded_id,
                latest_succeeded_finished_at=_iso(entry.latest_succeeded_finished_at),
                needs_attention=entry.needs_attention,
                note=entry.note,
            )
            for entry in report.imports
        ],
        tables=[
            TableEntry(
                table_name=entry.table_name,
                row_count=entry.row_count,
                total_bytes=entry.total_bytes,
                dead_tuples=entry.dead_tuples,
                analyzed_at=_iso(entry.analyzed_at),
                vacuumed_at=_iso(entry.vacuumed_at),
                needs_attention=entry.needs_attention,
                note=entry.note,
            )
            for entry in report.tables
        ],
        connections=ConnectionEntry(
            total=report.connections.total,
            max_connections=report.connections.max_connections,
            idle_in_transaction=report.connections.idle_in_transaction,
            longest_idle_transaction_seconds=report.connections.longest_idle_transaction_seconds,
            longest_query_seconds=report.connections.longest_query_seconds,
            needs_attention=report.connections.needs_attention,
            note=report.connections.note,
        ),
        database_bytes=report.database_bytes,
    )
