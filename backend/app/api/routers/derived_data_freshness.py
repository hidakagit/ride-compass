"""派生データ鮮度台帳の管理API。

`GET /api/admin/derived-data/freshness`（Basic認証必須）は、ソースごとの**鮮度**（今の派生を作った取込が
成功した最新の取込か）と、派生データの表ごとの**完成度**（値の列にNULLが何件あるか）・**被覆**（親にあって
行が無い件数）を返す。対象の表・列は宣言（ORM）から導くため、表や列を足しても増やす手当ては要らない。

`GET /api/admin/material-catalog/coverage`（材料の欠損割合）とは別の切り口——あちらは
「材料として値が取れるか」を材料の宣言から見る。認可を要求する理由・DB例外の扱いは
同じ（全表走査を伴うため認可なしに公開しない、DB例外は503へ変換し空レポートへ倒さない）。
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.admin_auth import require_admin_basic_auth
from app.api.dependencies import get_derived_data_freshness_service
from app.infrastructure.database import DB_UNAVAILABLE_ERRORS
from app.services.derived_data_freshness_service import (
    DerivedDataFreshnessReport,
    DerivedDataFreshnessService,
)

router = APIRouter(dependencies=[Depends(require_admin_basic_auth)])


@router.get(
    "/api/admin/derived-data/freshness",
    response_model=DerivedDataFreshnessReport,
)
async def get_derived_data_freshness(
    service: DerivedDataFreshnessService = Depends(get_derived_data_freshness_service),
) -> DerivedDataFreshnessReport:
    """ソースごとの鮮度と、派生データの表ごとの被覆・値の列ごとの未計算件数を返す。"""
    try:
        return await service.get_freshness_report()
    except DB_UNAVAILABLE_ERRORS as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="派生データ鮮度台帳の集計に失敗しました（DB接続の状況を確認してください）",
        ) from exc
