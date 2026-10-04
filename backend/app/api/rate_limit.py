"""ルーターが要求ごとに呼ぶper-IPレート制限（超過を429へ翻訳する）。"""

import logging

from fastapi import HTTPException, Request

from app.infrastructure.debug_log import record_rate_limit_rejection
from app.infrastructure.rate_limiter import check_rate_limit

logger = logging.getLogger("ridecompass.rate_limit")


def client_id(request: Request) -> str:
    """per-IPレート制限のキーに使うクライアント識別子。

    リバースプロキシ配下では、uvicornの`--proxy-headers`＋`--forwarded-allow-ips`
    （backend/Dockerfile）が正しくないと全アクセスがプロキシの単一IPへ潰れる。

    `request.client`がNoneのときは全リクエストが"unknown"の1バケットへ相乗りし、
    無関係なクライアントの通信量が合算される。プロキシ構成の調査に使えるよう記録する。
    """
    if request.client is None:
        logger.warning("request.client is None; rate-limit key falls back to shared 'unknown' bucket")
        return "unknown"
    return request.client.host


def enforce_rate_limit(request: Request, prefix: str, limit_per_minute: int) -> None:
    """per-IPレート制限を確認し、超過していれば記録した上で429を送出する。

    `prefix`はレート制限のキー・rejection集計カテゴリの両方を兼ねる。
    """
    client = client_id(request)
    if not check_rate_limit(f"{prefix}:{client}", limit_per_minute):
        record_rate_limit_rejection(prefix, client, f"{limit_per_minute}/min")
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
