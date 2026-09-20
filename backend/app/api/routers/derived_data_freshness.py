"""派生データ鮮度台帳の管理API。

`GET /api/admin/derived-data/freshness`（Basic認証必須）は、派生データの表ごとに
**鮮度**（その行がどの取込世代から作られたか）と**完成度**（値の列にNULLが何件あるか）を
返す。対象の表・列は宣言（ORM）から導くため、表や列を足しても増やす手当ては要らない。

`GET /api/admin/material-catalog/coverage`（材料の欠損割合）とは別の切り口——あちらは
「材料として値が取れるか」を材料の宣言から見る。認可を要求する理由・DB例外の扱いは
同じ（全表走査を伴うため認可なしに公開しない、DB例外は503へ変換し空レポートへ倒さない）。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import DBAPIError

from app.api.admin_auth import require_admin_basic_auth
from app.api.dependencies import get_derived_data_freshness_service
from app.domain.strict_model import StrictModel
from app.services.derived_data_freshness_service import DerivedDataFreshnessService

router = APIRouter()


class ColumnEntry(StrictModel):
    """値の列1本ぶんの完成度。

    NULLが「まだ計算していない」を意味する列と、「確定して値が無い」を意味する列がある。
    件数は常に返し、鳴らすかどうか（`is_incomplete`）だけを区別する。
    """

    column: str
    null_count: int
    is_incomplete: bool


class TableEntry(StrictModel):
    table_name: str
    row_count: int
    #: その行を作った取込のソース名（`source_runs.source`）。行が無ければNone。
    source: str | None
    oldest_run_id: int | None
    latest_run_id: int | None
    #: 生データを取り直したのに派生を流し直していない。
    is_stale: bool
    columns: list[ColumnEntry]


class DerivedDataFreshnessResponse(StrictModel):
    computed_at: str
    tables: list[TableEntry]


@router.get(
    "/api/admin/derived-data/freshness",
    response_model=DerivedDataFreshnessResponse,
    dependencies=[Depends(require_admin_basic_auth)],
)
async def get_derived_data_freshness(
    service: DerivedDataFreshnessService = Depends(get_derived_data_freshness_service),
) -> DerivedDataFreshnessResponse:
    """派生データの表ごとの鮮度と、値の列ごとの未計算件数を返す。"""
    try:
        report = await service.get_freshness_report()
    except DBAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="派生データ鮮度台帳の集計に失敗しました（DB接続の状況を確認してください）",
        ) from exc
    return DerivedDataFreshnessResponse(
        computed_at=report.computed_at.isoformat(),
        tables=[
            TableEntry(
                table_name=table.table_name,
                row_count=table.row_count,
                source=table.source,
                oldest_run_id=table.oldest_run_id,
                latest_run_id=table.latest_run_id,
                is_stale=table.is_stale,
                columns=[
                    ColumnEntry(
                        column=column.column,
                        null_count=column.null_count,
                        is_incomplete=column.is_incomplete,
                    )
                    for column in table.columns
                ],
            )
            for table in report.tables
        ],
    )
