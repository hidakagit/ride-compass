"""`infrastructure/response_compression.py`——content-typeで対象を絞った応答のgzip圧縮（`ContentTypeGZipMiddleware`）。

応答の形（content-type・大きさ・分けて送るか）を自由に作れるよう、ASGIのアプリを手で書いて包む。

ここで見ないもの:
- ミドルウェアの登録の順 → `main.py`（結線のみ）
- 圧縮の強さ（`compresslevel`）。縮み方と所要時間の兼ね合いで、応答の中身には現れない
"""

import gzip
from contextlib import asynccontextmanager

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from app.infrastructure.response_compression import DEFAULT_MINIMUM_SIZE, ContentTypeGZipMiddleware

LARGE_BODY = b"x" * DEFAULT_MINIMUM_SIZE


def app_answering(content_type: str | None, chunks: list[bytes]):
    """`content_type`（Noneなら付けない）で、`chunks`を1つずつ分けて送るアプリ。"""

    async def app(scope, receive, send):
        headers = [] if content_type is None else [(b"content-type", content_type.encode())]
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        for index, chunk in enumerate(chunks):
            await send({"type": "http.response.body", "body": chunk, "more_body": index < len(chunks) - 1})

    return app


def fetch(content_type: str | None, chunks: list[bytes], accept_encoding: str = "gzip, deflate, br"):
    client = TestClient(ContentTypeGZipMiddleware(app_answering(content_type, chunks)))
    # TestClient（httpx）は受け取ったgzipを自分で解くので、届いた生のバイト列を読む。
    with client.stream("GET", "/", headers={"Accept-Encoding": accept_encoding}) as response:
        return response, b"".join(response.iter_raw())


@pytest.mark.parametrize(
    "content_type",
    [
        "application/json",
        "application/json; charset=utf-8",
        "Application/JSON",
        "text/csv",
    ],
)
def test_a_large_compressible_response_is_gzipped(content_type):
    response, raw = fetch(content_type, [LARGE_BODY])

    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["vary"] == "Accept-Encoding"
    assert gzip.decompress(raw) == LARGE_BODY


@pytest.mark.parametrize("content_type", ["image/png", "image/webp", None])
def test_a_response_that_is_not_compressible_passes_through_unchanged(content_type):
    """ラスタのタイルは圧縮済みで、gzipしても縮まずCPUだけを使う。"""
    response, raw = fetch(content_type, [LARGE_BODY])

    assert "content-encoding" not in response.headers
    assert raw == LARGE_BODY


def test_a_compressible_response_is_not_gzipped_for_a_client_that_does_not_accept_it():
    response, raw = fetch("application/json", [LARGE_BODY], accept_encoding="identity")

    assert "content-encoding" not in response.headers
    assert raw == LARGE_BODY


def test_a_compressible_response_below_the_minimum_size_is_sent_as_is():
    response, raw = fetch("application/json", [LARGE_BODY[:-1]])

    assert "content-encoding" not in response.headers
    assert raw == LARGE_BODY[:-1]


def test_a_streamed_compressible_response_is_gzipped_as_a_whole():
    chunks = [b"a" * 10, b"b" * 10, b"c" * 10]

    response, raw = fetch("application/json", chunks)

    assert response.headers["content-encoding"] == "gzip"
    assert gzip.decompress(raw) == b"".join(chunks)


def test_every_part_of_a_streamed_response_that_is_not_compressible_passes_through():
    chunks = [b"\x89PNG" * 300, b"\x00" * 10, b"\xff" * 10]

    response, raw = fetch("image/png", chunks)

    assert "content-encoding" not in response.headers
    assert raw == b"".join(chunks)


def test_the_application_still_starts_and_stops_behind_the_middleware():
    """起動と停止の通知（lifespan）も同じミドルウェアを通る。"""
    events: list[str] = []

    @asynccontextmanager
    async def lifespan(_app):
        events.append("startup")
        yield
        events.append("shutdown")

    with TestClient(ContentTypeGZipMiddleware(Starlette(lifespan=lifespan))):
        assert events == ["startup"]

    assert events == ["startup", "shutdown"]
