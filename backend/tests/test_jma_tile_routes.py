import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_jma_tile_client
from app.config import settings
from app.infrastructure import rate_limiter
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


class FakeJmaTileClient:
    def __init__(self, result):
        self._result = result

    async def get(self, path):
        return self._result


def test_jma_tile_proxy_returns_cached_content_with_correct_media_type():
    app.dependency_overrides[get_jma_tile_client] = lambda: FakeJmaTileClient((b"\x89PNG", "image/png"))

    try:
        response = client.get(
            "/api/jma-tile/bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/805.png"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == b"\x89PNG"


def test_jma_tile_proxy_returns_502_on_upstream_failure():
    app.dependency_overrides[get_jma_tile_client] = lambda: FakeJmaTileClient(None)

    try:
        response = client.get("/api/jma-tile/bosai/jmatile/data/risk/targetTimes.json")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502


def test_jma_tile_proxy_is_rate_limited_per_client():
    app.dependency_overrides[get_jma_tile_client] = lambda: FakeJmaTileClient((b"{}", "application/json"))

    try:
        for _ in range(settings.jma_tile_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit("jma-tile:testclient", settings.jma_tile_rate_limit_per_minute)
        assert client.get("/api/jma-tile/bosai/jmatile/data/risk/targetTimes.json").status_code == 200
        response = client.get("/api/jma-tile/bosai/jmatile/data/risk/targetTimes.json")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429
