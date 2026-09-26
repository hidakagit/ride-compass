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
from app.services.db_status_service import DbStatusReport, DbStatusService

router = APIRouter(dependencies=[Depends(require_admin_basic_auth)])


@router.get(
    "/api/admin/db-status",
    response_model=DbStatusReport,
)
async def get_db_status(
    service: DbStatusService = Depends(get_db_status_service),
) -> DbStatusReport:
    try:
        return await service.get_status_report()
    except DBAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DB状態の集計に失敗しました（DB接続と、テーブルが作られているかを確認してください）",
        ) from exc
