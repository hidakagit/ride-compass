"""`infrastructure/response_compression.py`——content-typeで対象を絞ったgzipミドルウェア。

ここで見ないもの:
- どの応答にこのミドルウェアが掛かるか（アプリへの組み込み） → `test_main.py`
- タイル配信そのもののCache-Control・本文 → 各ルーターのテスト

**応答は生のASGIアプリで組み立てる。** 圧縮の判断はcontent-typeと本文の長さだけで決まるので、
実物のエンドポイントを通すと関係のない依存（DB・キャッシュ）まで用意することになる。
"""

import pytest
from starlette.testclient import TestClient

from app.infrastructure.response_compression import (
    COMPRESSIBLE_CONTENT_TYPES,
    DEFAULT_MINIMUM_SIZE,
    ContentTypeGZipMiddleware,
    is_compressible_content_type,
)

LISTED_TYPE = next(iter(COMPRESSIBLE_CONTENT_TYPES))
GZIP = {"Accept-Encoding": "gzip"}


def _app(content_type: str, body: bytes, *, chunks: int = 1):
    """content-typeと本文だけを返すASGIアプリ。`chunks=2`で本文を2メッセージに分けて送る。"""
    parts = [body[: len(body) // 2], body[len(body) // 2 :]] if chunks == 2 else [body]

    async def app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", content_type.encode())],
            }
        )
        for index, part in enumerate(parts):
            await send({"type": "http.response.body", "body": part, "more_body": index < len(parts) - 1})

    return app


def _get(content_type: str, body: bytes, *, headers=GZIP, chunks: int = 1):
    client = TestClient(ContentTypeGZipMiddleware(_app(content_type, body, chunks=chunks)))
    return client.get("/", headers=headers)


def test_a_missing_content_type_is_not_compressible():
    assert not is_compressible_content_type(None)
    assert not is_compressible_content_type("")


def test_any_text_type_is_compressible_whatever_its_parameters_and_case():
    assert is_compressible_content_type("Text/HTML; charset=UTF-8")
    assert is_compressible_content_type(" text/plain ")


def test_a_listed_application_type_is_matched_after_normalisation():
    """一覧との照合そのものは`in`が保証するので見ない。見るのは、照合へ渡す前に大小と
    パラメータ部を落としている側——落とし損ねると、実際に配信されるcontent-typeの形
    （`; charset=utf-8`付き）が一覧に当たらず、まるごと圧縮されなくなる。
    """
    assert COMPRESSIBLE_CONTENT_TYPES

    assert is_compressible_content_type(LISTED_TYPE.upper() + "; charset=utf-8")


def test_media_types_outside_the_list_are_not_compressible():
    """ラスタタイル（PNG等）は既に圧縮済みで、gzipしてもほぼ縮まずCPUだけ食う。"""
    assert not is_compressible_content_type("image/png")
    assert not is_compressible_content_type("application/octet-stream")
    assert not is_compressible_content_type("application/pdf")


def test_a_large_text_response_is_gzipped_for_a_client_that_accepts_it():
    body = b"a" * (DEFAULT_MINIMUM_SIZE * 2)

    response = _get("text/plain; charset=utf-8", body)

    assert response.headers["content-encoding"] == "gzip"
    assert "Accept-Encoding" in response.headers["vary"]
    assert response.content == body


def test_a_binary_response_is_passed_through_across_all_its_chunks():
    """先頭メッセージで下した判断を後続の本文にも効かせないと、ヘッダはgzipでないのに
    本文だけ圧縮された応答になり、クライアントが復号できない。
    """
    body = bytes(range(256)) * 8

    response = _get("image/png", body, chunks=2)

    assert "content-encoding" not in response.headers
    assert response.content == body


def test_nothing_is_compressed_when_the_client_does_not_accept_gzip():
    body = b"a" * (DEFAULT_MINIMUM_SIZE * 2)

    response = _get("text/plain", body, headers={"Accept-Encoding": "identity"})

    assert "content-encoding" not in response.headers
    assert response.content == body


def test_a_response_below_the_minimum_size_is_not_compressed():
    """短い本文はgzipヘッダのぶんだけ大きくなる。"""
    body = b"a" * (DEFAULT_MINIMUM_SIZE // 10)

    response = _get("text/plain", body)

    assert "content-encoding" not in response.headers
    assert response.content == body


@pytest.mark.asyncio
async def test_non_http_scopes_never_reach_the_header_lookup():
    """lifespanのscopeは`headers`を持たない。先にtypeを見ないと起動時にKeyErrorで落ちる。"""
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["type"])

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(message):
        return None

    await ContentTypeGZipMiddleware(app)({"type": "lifespan"}, receive, send)

    assert seen == ["lifespan"]
