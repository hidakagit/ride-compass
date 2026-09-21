"""リクエストIDの付与と、リクエスト1件=1行のHTTPアクセスサマリログ(方針は docs/conventions/logging.md)。

クライアントが`X-Request-ID`ヘッダを送ってきた場合はそれを引き継ぐ（フロントやcurlから
調査用に指定できる）。レスポンスにも同じヘッダで返すため、CORS越しに読めるよう
`main.py`の`expose_headers`へ入れておく必要がある。

**リクエストIDはcontextvarと`request.state`の両方へ置く。** 本ミドルウェアの`finally`節は、
未処理例外の伝播中に（`ServerErrorMiddleware`側のハンドラ実行より先に）contextvarを
リセットする。そのため500応答を組み立てる`unhandled_exception_handler`はcontextvarから
読めず、ASGI scopeに紐づいて巻き戻しの影響を受けない`request.state`から読む。
"""

import contextvars
import logging
import time
import uuid
from datetime import datetime

from fastapi import Request, Response
from fastapi.responses import PlainTextResponse

from app.domain.time_zone import JST

access_logger = logging.getLogger("ridecompass.access")

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

# タイル系は通常操作でも毎分数百リクエストになるため、成功時のアクセスログは
# DEBUG(debug_mode時のみ実質出力)へ落とし、ログを埋めないようにする。
HIGH_FREQUENCY_PATH_PREFIXES = ("/api/basemap", "/api/region/road-surface-tiles")


#: ログ1行の書式。標準出力（main.py）と管理画面のリングバッファ（debug_control.py）が
#: 同じ行を出すよう、ここだけに置く。`%(request_id)s`は下の`RequestIdLogFilter`が入れる。
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s [req:%(request_id)s]: %(message)s"


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


class RequestIdLogFilter(logging.Filter):
    """全ログレコードへcontextvarのrequest_idを注入する(main.pyでrootハンドラに装着)。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    """FastAPIの`Exception`ハンドラとして登録する(main.py: `app.add_exception_handler`)。

    500応答は本来Starletteの`ServerErrorMiddleware`（本ミドルウェアの外側）が作るため、
    そこにはX-Request-IDを付けられない。FastAPIのExceptionハンドラはそれより先に
    呼ばれるので、ここで同じ形のプレーンテキスト応答を組み立ててヘッダを載せる。
    """
    del exc  # スタックトレースはrequest_log_middleware側で既にERRORログ済み
    request_id = getattr(request.state, "request_id", None) or "-"
    return PlainTextResponse("Internal Server Error", status_code=500, headers={"X-Request-ID": request_id})


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
    request_id = request.headers.get("X-Request-ID") or new_request_id()
    request.state.request_id = request_id  # モジュールdocstring参照
    token = request_id_var.set(request_id)
    started = time.monotonic()
    client = request.client.host if request.client else "unknown"
    try:
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
        response.headers["X-Request-ID"] = request_id
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
    finally:
        request_id_var.reset(token)
