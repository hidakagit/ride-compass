"""本番DBの状態を返す管理API。

`GET /api/admin/db-status`（Basic認証必須）は、派生データの鮮度
（`derived_data_freshness.py`）が拠って立つ**土台**の側を返す——生データ取込そのものが
失敗していないか、行が本当に入っているか、プランナが使う統計が取れているか、
トランザクションが放置されていないか。

認可を要求する理由・DB例外の扱いは`get_derived_data_freshness`と同じ（全表走査を伴うため
認可なしに公開しない、DB例外は空レポートへ倒さず503（`api/admin_db_errors.py`）で返す）。
"""

from fastapi import APIRouter, Depends

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
    return await service.get_status_report()
