import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_gsi_relief_tile_client
from app.config import settings
from app.infrastructure import rate_limiter
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


class FakeGsiReliefTileClient:
    def __init__(self, result):
        self._result = result

    async def get(self, path):
        return self._result


def test_gsi_relief_tile_proxy_returns_content_with_correct_media_type():
    app.dependency_overrides[get_gsi_relief_tile_client] = lambda: FakeGsiReliefTileClient((b"\x89PNG", "image/png"))

    try:
        response = client.get("/api/gsi-relief-tile/xyz/relief/12/3637/1612.png")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == b"\x89PNG"


def test_gsi_relief_tile_proxy_returns_502_on_upstream_failure():
    app.dependency_overrides[get_gsi_relief_tile_client] = lambda: FakeGsiReliefTileClient(None)

    try:
        response = client.get("/api/gsi-relief-tile/xyz/relief/12/3637/1612.png")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502


def test_gsi_relief_tile_proxy_returns_404_when_tile_not_found_upstream():
    # 改善計画T605: 整備区域外（404、珍しくない正常系）は502ではなく404を返す。
    from app.infrastructure.gsi_relief_tile_client import RELIEF_TILE_NOT_FOUND

    app.dependency_overrides[get_gsi_relief_tile_client] = lambda: FakeGsiReliefTileClient(RELIEF_TILE_NOT_FOUND)

    try:
        response = client.get("/api/gsi-relief-tile/xyz/relief/12/3637/1612.png")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


def test_gsi_relief_tile_proxy_is_rate_limited_per_client():
    app.dependency_overrides[get_gsi_relief_tile_client] = lambda: FakeGsiReliefTileClient((b"x", "image/png"))

    try:
        for _ in range(settings.gsi_relief_tile_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit("gsi-relief-tile:testclient", settings.gsi_relief_tile_rate_limit_per_minute)
        assert client.get("/api/gsi-relief-tile/xyz/relief/12/3637/1612.png").status_code == 200
        response = client.get("/api/gsi-relief-tile/xyz/relief/12/3637/1612.png")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429
