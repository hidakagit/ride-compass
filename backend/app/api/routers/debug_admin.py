"""debug_modeのランタイム切替・直近ログ取得の管理API（改善計画T378）。

T318の本番調査で「本番debug_modeの一時有効化に毎回SSHが必要」という運用上の
ボトルネックが判明したことへの対応。axis_admin.pyと同じ`require_admin_basic_auth`
（HTTP Basic認証）で保護する——ログ出力の内容にはルート生成のリクエスト座標等が
含まれうるため、`/api/debug/stats`（集計値のみ、認可不要）とは異なり認可を要求する。
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.admin_auth import require_admin_basic_auth
from app.config import settings
from app.infrastructure.debug_control import get_recent_logs, set_debug_mode

router = APIRouter(prefix="/api/admin/debug", tags=["debug-admin"], dependencies=[Depends(require_admin_basic_auth)])


class DebugModeRequest(BaseModel):
    enabled: bool


class DebugModeResponse(BaseModel):
    debug_mode: bool


@router.post("/mode")
def update_debug_mode(payload: DebugModeRequest) -> DebugModeResponse:
    """debug_modeをランタイムで切り替える（`.env`は書き換えない、プロセス再起動不要）。

    再起動・再デプロイのたびに環境変数の値（既定false）へ自動的に戻る
    （debug_control.pyのdocstring参照。戻し忘れのリスクを構造的に避ける設計）。
    """
    return DebugModeResponse(debug_mode=set_debug_mode(payload.enabled))


@router.get("/mode")
def read_debug_mode() -> DebugModeResponse:
    return DebugModeResponse(debug_mode=settings.debug_mode)


@router.get("/logs")
def read_recent_logs(limit: int | None = None, contains: str | None = None) -> list[str]:
    """直近のログ行を返す（プロセス内メモリのリングバッファ、既定で最大1000件保持）。

    `contains`で部分一致フィルタ（例: T318調査の`distance filter rejected`）、
    `limit`でフィルタ後の末尾N件に絞り込める。debug_modeがOFFの間はDEBUGレベルの
    行自体がそもそも記録されない点に注意（先に`POST /mode`で有効化すること）。
    """
    return get_recent_logs(limit=limit, contains=contains)
