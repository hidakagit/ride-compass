"""本番で起きたエラーの報告を受ける口（`POST /api/client-errors`）と読む口（`GET /api/debug/errors`）。

記録の置き場と1件の中身は`infrastructure/error_reports.py`が持つ。
"""

import logging
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import AwareDatetime, Field, ValidationError

from app.api.rate_limit import enforce_rate_limit
from app.config import settings
from app.domain.strict_model import StrictModel
from app.infrastructure import error_reports
from app.infrastructure.error_reports import ErrorReport

router = APIRouter()
logger = logging.getLogger(__name__)

#: 読む口が返す直近の件数。知らせを受けた人が、どこで何が起きたかの見当を付けるのに足りる数。
RECENT_REPORTS = 20


class ClientErrorReport(StrictModel):
    """画面が送る報告。名前とパスは決まった文字と長さだけを受ける——記録は認証なしで読めるので、利用者の入力・座標・
    例外の文が入り込む欄を持たない。"""

    #: 捕まえていない例外・Promiseの拒否・描画の例外・backendへの通信の失敗・その時間切れ。
    kind: Literal["exception", "rejection", "render", "network", "timeout"]
    #: 例外の型（`TypeError`等）か、失敗したAPIの分類（`api:weather`等）。
    name: str = Field(pattern=r"^[A-Za-z0-9_.:\-]{1,80}$")
    #: 起きた画面のパス（問い合わせ・断片を除く）。
    page: str = Field(pattern=r"^/[A-Za-z0-9_.\-/]{0,199}$")


_CLIENT_ERROR_BODY = {
    "requestBody": {
        "required": True,
        "content": {"text/plain": {"schema": ClientErrorReport.model_json_schema()}},
    }
}


@router.post("/api/client-errors", status_code=204, openapi_extra=_CLIENT_ERROR_BODY)
async def receive_client_error(request: Request) -> Response:
    """画面で起きたエラーを1件記録する。本文は`text/plain`で送られるJSON（`navigator.sendBeacon`はCORSの事前の
    問い合わせが起きない形でしか送れず、CORSの設定が食い違ったときも届く）。形に合わない報告は記録せず422。"""
    enforce_rate_limit(request, "client-errors", settings.client_error_rate_limit_per_minute)
    try:
        report = ClientErrorReport.model_validate_json(await request.body())
    except ValidationError:
        return Response(status_code=422)
    logger.warning("画面のエラー kind=%s name=%s page=%s", report.kind, report.name, report.page)
    error_reports.record(
        ErrorReport(
            at=datetime.now().astimezone(),
            source="frontend",
            kind=report.kind,
            name=report.name,
            page=report.page,
            request_id=None,
        )
    )
    return Response(status_code=204)


class ErrorReportsResponse(StrictModel):
    count: int
    #: 直近の`RECENT_REPORTS`件まで（古い順）。
    recent: list[ErrorReport]


@router.get("/api/debug/errors", response_model=ErrorReportsResponse)
def read_error_reports(since: Annotated[AwareDatetime, Query()]) -> ErrorReportsResponse:
    """`since`以後に記録したエラーの件数と直近の数件。"""
    reports = error_reports.reports_since(since)
    return ErrorReportsResponse(count=len(reports), recent=reports[-RECENT_REPORTS:])
