import gzip

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from app.infrastructure.response_compression import (
    ContentTypeGZipMiddleware,
    DEFAULT_MINIMUM_SIZE,
    is_compressible_content_type,
)

LARGE_JSON = {"values": list(range(2000))}
LARGE_BYTES = bytes(range(256)) * 20


def _build_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(ContentTypeGZipMiddleware)

    @app.get("/json")
    def json_endpoint():
        return LARGE_JSON

    @app.get("/small")
    def small_endpoint():
        return {"ok": True}

    @app.get("/mvt")
    def mvt_endpoint():
        return Response(content=LARGE_BYTES, media_type="application/vnd.mapbox-vector-tile")

    @app.get("/png")
    def png_endpoint():
        return Response(content=LARGE_BYTES, media_type="image/png")

    @app.get("/text")
    def text_endpoint():
        return Response(content="a" * 5000, media_type="text/plain; charset=utf-8")

    return TestClient(app)


def test_is_compressible_content_type():
    assert is_compressible_content_type("application/json")
    assert is_compressible_content_type("application/vnd.mapbox-vector-tile")
    assert is_compressible_content_type("Text/Plain; charset=utf-8")
    assert not is_compressible_content_type("image/png")
    assert not is_compressible_content_type(None)
    assert not is_compressible_content_type("")


def test_large_json_is_gzipped_when_client_accepts_gzip():
    client = _build_client()
    response = client.get("/json", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert "Accept-Encoding" in response.headers["vary"]
    # httpxが透過的に展開するため、本文は元のJSONとして読める
    assert response.json() == LARGE_JSON


def test_mvt_is_gzipped_and_roundtrips():
    client = _build_client()
    response = client.get("/mvt", headers={"Accept-Encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    assert response.content == LARGE_BYTES


def test_png_is_not_gzipped():
    client = _build_client()
    response = client.get("/png", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in response.headers
    assert response.content == LARGE_BYTES


def test_text_is_gzipped():
    client = _build_client()
    response = client.get("/text", headers={"Accept-Encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    assert response.text == "a" * 5000


def test_small_response_is_not_gzipped():
    client = _build_client()
    response = client.get("/small", headers={"Accept-Encoding": "gzip"})
    assert len(response.content) < DEFAULT_MINIMUM_SIZE
    assert "content-encoding" not in response.headers


def test_not_gzipped_without_accept_encoding():
    client = _build_client()
    response = client.get("/json", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in response.headers
    assert response.json() == LARGE_JSON


def test_raw_gzip_body_is_valid():
    """展開をhttpxに任せず、生のgzipバイト列として妥当であることを確認する。"""
    client = _build_client()
    response = client.send(
        client.build_request("GET", "/mvt", headers={"Accept-Encoding": "gzip"}), stream=True
    )
    raw = b"".join(response.iter_raw())
    assert gzip.decompress(raw) == LARGE_BYTES
    assert int(response.headers["content-length"]) == len(raw)
