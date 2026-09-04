"""応答のgzip圧縮（content-typeで対象を絞ったGZipMiddleware）。

StarletteのGZipMiddlewareはcontent-typeを見ずに全応答を圧縮するため、そのまま使うと
basemap/JMA/国土地理院のラスタタイル（PNG等、既に圧縮済みでgzipしても縮まない）にも
CPUを使ってしまう。ここでは`COMPRESSIBLE_CONTENT_TYPES`に該当する応答だけを圧縮し、
それ以外はそのまま素通しする。

圧縮はイベントループ上で同期的に行われる（GZipResponderの実装）ため、compresslevelは
高くしない。路面タイル（z12で約680KB）の実測ではlevel 3で約57%、level 9で約55%と
縮小率がほぼ同じ一方、所要時間は6倍近く違う。
"""

from starlette.datastructures import Headers
from starlette.middleware.gzip import GZipMiddleware, GZipResponder
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# 圧縮対象のcontent-type（パラメータ部を除いた小文字比較）。`text/`で始まるものは
# 個別に列挙せず常に対象とする。
COMPRESSIBLE_CONTENT_TYPES = frozenset(
    {
        "application/json",
        "application/vnd.mapbox-vector-tile",
        "application/x-protobuf",
        "application/javascript",
    }
)
DEFAULT_MINIMUM_SIZE = 1000
DEFAULT_COMPRESS_LEVEL = 3


def is_compressible_content_type(content_type: str | None) -> bool:
    if not content_type:
        return False
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type.startswith("text/") or media_type in COMPRESSIBLE_CONTENT_TYPES


class _ContentTypeGZipResponder(GZipResponder):
    """応答ヘッダのcontent-typeが圧縮対象外なら、以後のメッセージを無加工で送る。"""

    def __init__(self, app: ASGIApp, minimum_size: int, compresslevel: int) -> None:
        super().__init__(app, minimum_size, compresslevel=compresslevel)
        self._passthrough = False

    async def send_with_gzip(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            headers = Headers(raw=message["headers"])
            self._passthrough = not is_compressible_content_type(headers.get("content-type"))
        if self._passthrough:
            await self.send(message)
            return
        await super().send_with_gzip(message)


class ContentTypeGZipMiddleware(GZipMiddleware):
    """`Accept-Encoding: gzip`のリクエストに対し、圧縮対象content-typeの応答だけをgzipする。"""

    def __init__(
        self,
        app: ASGIApp,
        minimum_size: int = DEFAULT_MINIMUM_SIZE,
        compresslevel: int = DEFAULT_COMPRESS_LEVEL,
    ) -> None:
        super().__init__(app, minimum_size=minimum_size, compresslevel=compresslevel)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and "gzip" in Headers(scope=scope).get("Accept-Encoding", ""):
            responder = _ContentTypeGZipResponder(self.app, self.minimum_size, compresslevel=self.compresslevel)
            await responder(scope, receive, send)
            return
        await self.app(scope, receive, send)
