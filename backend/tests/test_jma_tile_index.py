"""`infrastructure/jma_tile_index.py`（在否判定）と配信エンドポイントのテスト。"""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.dependencies import get_jma_tile_client
from app.infrastructure.jma_tile_index import is_empty_tile
from app.main import app

client = TestClient(app)


def _png(color, size=256):
    buffer = io.BytesIO()
    Image.new("RGBA", (size, size), color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_fully_transparent_raster_is_empty():
    assert is_empty_tile(_png((0, 0, 0, 0)), "png") is True


def test_raster_with_any_opaque_pixel_is_not_empty():
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    # 1画素でも描かれていれば「中身あり」。危険度は局所的に出るため、わずかな塗りを
    # 取りこぼすと危険情報が表示されなくなる。
    image.putpixel((128, 128), (242, 231, 0, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    assert is_empty_tile(buffer.getvalue(), "png") is False


def test_partially_transparent_pixel_counts_as_content():
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    image.putpixel((10, 10), (255, 40, 0, 40))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    assert is_empty_tile(buffer.getvalue(), "png") is False


@pytest.mark.parametrize(("content", "expected"), [(b"", True), (b"\x1a\x02\x0a", False)])
def test_vector_tile_emptiness_is_decided_by_length(content, expected):
    assert is_empty_tile(content, "pbf") is expected


def test_undecodable_content_is_treated_as_having_content():
    # 判定できないものを「空」にすると危険情報が表示されなくなるため、中身ありへ倒す。
    assert is_empty_tile(b"not-a-png", "png") is False


def test_index_endpoint_reports_unavailable_when_not_stored(monkeypatch):
    async def _no_index():
        return None

    monkeypatch.setattr("app.api.routers.jma_tile.get_index", _no_index)

    response = client.get("/api/jma-tile-index")

    assert response.status_code == 200
    # インデックスが無いことで表示が欠けてはならない。クライアントは従来どおり全タイルを取る。
    assert response.json() == {"available": False}


def test_index_endpoint_returns_stored_index(monkeypatch):
    stored = {
        "coverage": {
            "min_longitude": 138.35,
            "min_latitude": 34.85,
            "max_longitude": 140.95,
            "max_latitude": 37.20,
        },
        "elements": {
            "rain_mesh": {
                "basetime": "20260907025000",
                "validtime": "20260907025000",
                "member": "immed0",
                "zooms": {"10": [[909, 403]]},
            }
        },
    }

    async def _stored_index():
        return stored

    monkeypatch.setattr("app.api.routers.jma_tile.get_index", _stored_index)

    response = client.get("/api/jma-tile-index")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["elements"]["rain_mesh"]["zooms"]["10"] == [[909, 403]]
    assert body["coverage"]["min_longitude"] == 138.35


def test_index_endpoint_is_short_lived():
    # プリウォーム（10分間隔）ごとに内容が変わる。古いものを掴むと「中身があるのに
    # 取りに行かない」ことになるため短命にする。
    async def _no_index():
        return None

    app.dependency_overrides[get_jma_tile_client] = lambda: None
    try:
        response = client.get("/api/jma-tile-index")
    finally:
        app.dependency_overrides.clear()

    assert response.headers["cache-control"] == "public, max-age=60"
