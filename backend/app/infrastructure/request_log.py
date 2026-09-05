"""リクエストIDの付与と、リクエスト1件=1行のHTTPアクセスサマリログ(方針は docs/logging.md)。

- 全リクエストにリクエストIDを割り当てる。クライアントが`X-Request-ID`ヘッダを
  送ってきた場合はそれを引き継ぎ(フロントや curl から調査用に指定できる)、無ければ生成する。
- リクエストIDはcontextvarに置き、`RequestIdLogFilter`が**全ログレコード**へ
  `request_id`属性として注入する(main.pyのフォーマット文字列`%(request_id)s`が参照)。
  これにより、リクエスト処理中に出た外部API呼び出しログ(debug_log.py)・ルート生成
  ステージログ(route_generator.py)等がすべて同じIDで紐づき、Renderのログ検索で
  1リクエスト分の流れを一発で追える。
- レスポンスにも`X-Request-ID`ヘッダで返す(フロントのDebugConsoleに表示され、
  ユーザー報告からサーバーログを特定できる。CORS越しに読むためmain.pyの
  expose_headers設定が必要)。
- 完了時にメソッド・パス・ステータス・所要時間・クライアントIPを1行でログする。
  レベルはステータスと経路で変える(_access_level参照)。
- ルーティング内で発生した未処理例外はスタックトレース付きERRORで記録して再送出する
  (「エラー発生箇所」の特定用。HTTPExceptionはFastAPI側で処理済みのためここには来ない)。
- 未処理例外(500)発生時もX-Request-IDヘッダを付与する。このミドルウェアは
  例外を再送出するだけで実際の500レスポンスは持たない(Starletteの
  ServerErrorMiddlewareが外側で生成する)ため、ヘッダはここでは設定できない。代わりに
  `unhandled_exception_handler`をFastAPIの`Exception`ハンドラとして登録する(main.py)。
  request_idの受け渡しはcontextvarではなく`request.state`を使う——本ミドルウェアの
  `finally`節がcall_next()の例外伝播中に(ServerErrorMiddleware側のハンドラ実行より先に)
  contextvarをリセットしてしまい、ハンドラ側でrequest_id_var.get()を呼ぶと既定値
  "-"しか読めないタイミング問題があるため。`request.state`はASGI scopeに
  紐づき、ミドルウェアの巻き戻しの影響を受けない。
"""

import contextvars
import logging
import time
import uuid

from fastapi import Request, Response
from fastapi.responses import PlainTextResponse

access_logger = logging.getLogger("ridecompass.access")

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

# タイル系は通常操作でも毎分数百リクエストになるため、成功時のアクセスログは
# DEBUG(debug_mode時のみ実質出力)へ落とし、Renderのログを埋めないようにする。
HIGH_FREQUENCY_PATH_PREFIXES = ("/api/basemap", "/api/region/road-surface-tiles")


class RequestIdLogFilter(logging.Filter):
    """全ログレコードへcontextvarのrequest_idを注入する(main.pyでrootハンドラに装着)。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    """FastAPIの`Exception`ハンドラとして登録する(main.py: `app.add_exception_handler`)。

    request_log_middlewareは未処理例外をログした上でそのまま再送出するだけで、実際の
    500レスポンス自体はStarletteのServerErrorMiddleware(このミドルウェアより外側)が
    生成するため、ここでヘッダを設定する機会が無い。FastAPIの
    Exceptionハンドラはミドルウェアより内側・ServerErrorMiddlewareより先に呼ばれるため、
    ここでレスポンスを構築すればX-Request-IDを含められる。本文・ステータスコードは
    ServerErrorMiddleware既定のプレーンテキスト応答と同じ形（デバッグ情報は含めない、
    詳細はサーバーログをrequest_idで追う運用）。request_idは`request.state`から読む
    （モジュールdocstring参照、contextvarはこの時点で既にリセット済みのため使えない）。
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
    # 状態を変える操作(POST /api/basemap/refresh のキャッシュ全消去等)は常時INFOで残す。
    if method == "GET" and path.startswith(HIGH_FREQUENCY_PATH_PREFIXES):
        return logging.DEBUG
    return logging.INFO


async def request_log_middleware(request: Request, call_next) -> Response:
    request_id = request.headers.get("X-Request-ID") or new_request_id()
    # unhandled_exception_handlerがcontextvarのリセット後でも読めるよう、
    # ASGI scopeに紐づくrequest.stateへも複製しておく（モジュールdocstring参照）。
    request.state.request_id = request_id
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
