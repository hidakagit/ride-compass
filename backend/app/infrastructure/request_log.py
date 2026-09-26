"""リクエスト1件=1行のHTTPアクセスサマリログと、ログ1行の書式(方針は docs/conventions/logging.md)。

リクエストIDの引き継ぎ・発行・応答ヘッダへの付与は`asgi_correlation_id.CorrelationIdMiddleware`
（`main.py`で登録）が持ち、ここはそのIDをログ行と500応答へ載せる側だけを持つ。
"""

import logging
import time
from datetime import datetime

from asgi_correlation_id import CorrelationIdFilter, correlation_id
from fastapi import Request, Response
from fastapi.responses import PlainTextResponse

from app.domain.time_zone import JST

access_logger = logging.getLogger("ridecompass.access")

# タイル系は通常操作でも毎分数百リクエストになるため、成功時のアクセスログは
# DEBUG(debug_mode時のみ実質出力)へ落とし、ログを埋めないようにする。
HIGH_FREQUENCY_PATH_PREFIXES = ("/api/basemap", "/api/region/road-surface-tiles")


#: ログ1行の書式。`%(correlation_id)s`は`format_log_lines`が付けるフィルタが入れる。
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s [req:%(correlation_id)s]: %(message)s"


class JstLogFormatter(logging.Formatter):
    """時刻をJSTで、**オフセット付き**で出すフォーマッタ。

    コンテナの`TZ`ではなく整形する側を変えるのは、`TZ`が素の`datetime.now()`の意味まで
    変えてしまうため（スケジューラ・DBへ書く時刻へ波及する）。
    """

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        at = datetime.fromtimestamp(record.created, JST)
        if datefmt:
            return at.strftime(datefmt)
        return f"{at.strftime('%Y-%m-%d %H:%M:%S')},{int(record.msecs):03d}{at.strftime('%z')}"


def format_log_lines(handler: logging.Handler) -> None:
    """ハンドラへログ1行の書式（JSTの時刻・リクエストID）を付ける。

    標準出力（main.py）と管理画面のリングバッファ（debug_control.py）が同じ行を出すよう、
    書式とリクエストIDの入れ方はここだけに置く。リクエストの外で出た行のIDは`-`になる。
    """
    handler.addFilter(CorrelationIdFilter(default_value="-"))
    handler.setFormatter(JstLogFormatter(LOG_FORMAT))


async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    """FastAPIの`Exception`ハンドラとして登録する(main.py: `app.add_exception_handler`)。

    500応答は本来Starletteの`ServerErrorMiddleware`（リクエストIDのミドルウェアの外側）が
    作るため、そこにはX-Request-IDが付かない。FastAPIのExceptionハンドラはその中で
    呼ばれるので、ここで同じ形のプレーンテキスト応答を組み立ててヘッダを載せる。
    """
    del request, exc  # スタックトレースはrequest_log_middleware側で既にERRORログ済み
    return PlainTextResponse(
        "Internal Server Error", status_code=500, headers={"X-Request-ID": correlation_id.get() or "-"}
    )


def _access_level(method: str, path: str, status_code: int) -> int:
    if status_code >= 500:
        return logging.ERROR
    if status_code == 429:
        # 429はrecord_rate_limit_rejection(debug_log.py)が抑制付きWARNINGで別途記録する
        # ため、アクセスログ側で重ねてWARNINGにしない。
        return logging.DEBUG
    if status_code >= 400:
        return logging.WARNING
    # DEBUGへ落とすのは高頻度なタイル**取得**(GET)のみ。同じプレフィックス配下でも
    # 状態を変える操作(POST /api/admin/basemap/refresh のキャッシュ全消去等)は常時INFOで残す。
    if method == "GET" and path.startswith(HIGH_FREQUENCY_PATH_PREFIXES):
        return logging.DEBUG
    return logging.INFO


async def request_log_middleware(request: Request, call_next) -> Response:
    started = time.monotonic()
    client = request.client.host if request.client else "unknown"
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        access_logger.exception(
            "%s %s -> unhandled exception after %dms client=%s",
            request.method,
            request.url.path,
            elapsed_ms,
            client,
        )
        raise
    elapsed_ms = round((time.monotonic() - started) * 1000)
    access_logger.log(
        _access_level(request.method, request.url.path, response.status_code),
        "%s %s -> %d in %dms client=%s",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
        client,
    )
    return response
