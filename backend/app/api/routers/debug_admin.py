"""debug_modeのランタイム切替・直近ログ取得の管理API（改善計画T379）。

T318の本番調査で「本番debug_modeの一時有効化に毎回SSHが必要」という運用上の
ボトルネックが判明したことへの対応。axis_admin.pyと同じ`require_admin_basic_auth`
（HTTP Basic認証）で保護する——ログ出力の内容にはルート生成のリクエスト座標等が
含まれうるため、`/api/debug/stats`（集計値のみ、認可不要）とは異なり認可を要求する。
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.admin_auth import require_admin_basic_auth
from app.config import settings
from app.infrastructure.debug_control import get_recent_logs, set_debug_mode

router = APIRouter(prefix="/api/admin/debug", tags=["debug-admin"], dependencies=[Depends(require_admin_basic_auth)])

# 改善計画T517（ユーザー指摘「デバッグレベルだけでいい？エラーだけとかログレベルによる
# 汎化もできない？」）: contains（部分一致）とは別の軸として、Python標準loggingの
# レベル名で「このレベル以上」に絞り込めるようにする。名前→数値の対応はlogging標準の
# ものをそのまま使う。
_LOG_LEVEL_NAME = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
_LOG_LEVEL_NUMBERS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


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
def read_recent_logs(
    limit: int | None = Query(default=None, gt=0),
    contains: str | None = None,
    min_level: _LOG_LEVEL_NAME | None = None,
) -> list[str]:
    """直近のログ行を返す（プロセス内メモリのリングバッファ、既定で最大1000件保持）。

    `min_level`で「このレベル以上」に絞り込める（例: `WARNING`を渡すとWARNING/ERROR/
    CRITICALだけになる、改善計画T517）。`contains`で部分一致フィルタ（例: T318調査の
    `distance filter rejected`）、両方指定するとAND条件。`limit`でフィルタ後の末尾N件に
    絞り込める。debug_modeがOFFの間はDEBUGレベルの行自体がそもそも記録されない点に注意
    （先に`POST /mode`で有効化すること。WARNING以上はdebug_modeに関わらず常時記録される、
    docs/logging.md参照）。

    改善計画T467: `limit`に0以下を渡すとget_recent_logs内部の`lines[-limit:]`が
    Pythonのスライス仕様上「末尾からN件」ではなく異なる範囲を返してしまう
    （例: limit=-5は「先頭5件を除く全件」になる）ため、`gt=0`で弾く。上限側は
    リングバッファ自体が最大1000件しか保持していないため、大きすぎる値を渡しても
    保持件数以上は返らず実害が無い（バリデーションで別途上限を設けない）。
    """
    min_level_number = _LOG_LEVEL_NUMBERS[min_level] if min_level is not None else None
    return get_recent_logs(limit=limit, contains=contains, min_level=min_level_number)
