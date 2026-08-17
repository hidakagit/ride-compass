import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_basemap_client
from app.config import settings
from app.infrastructure import rate_limiter, tile_cache
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


class FakeBasemapClient:
    def __init__(self, result):
        self._result = result

    async def get(self, path):
        return self._result


def test_basemap_proxy_returns_cached_content_with_correct_media_type():
    app.dependency_overrides[get_basemap_client] = lambda: FakeBasemapClient((b'{"version":8}', "application/json"))

    try:
        response = client.get("/api/basemap/styles/liberty")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.content == b'{"version":8}'


def test_basemap_proxy_returns_502_on_upstream_failure():
    app.dependency_overrides[get_basemap_client] = lambda: FakeBasemapClient(None)

    try:
        response = client.get("/api/basemap/planet/1/2/3.pbf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502


def test_basemap_proxy_is_rate_limited_per_client():
    app.dependency_overrides[get_basemap_client] = lambda: FakeBasemapClient((b"x", "application/json"))

    try:
        for _ in range(settings.basemap_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit("basemap:testclient", settings.basemap_rate_limit_per_minute)
        assert client.get("/api/basemap/styles/liberty").status_code == 200
        response = client.get("/api/basemap/styles/liberty")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429


def test_basemap_refresh_clears_tile_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(tile_cache, "CACHE_DIR", tmp_path / "tile_cache")
    tile_cache.set("styles/liberty", b"cached", "application/json")

    response = client.post("/api/basemap/refresh")

    assert response.status_code == 200
    assert tile_cache.get("styles/liberty") is None


def test_basemap_refresh_is_rate_limited_per_client(tmp_path, monkeypatch):
    monkeypatch.setattr(tile_cache, "CACHE_DIR", tmp_path / "tile_cache")

    for _ in range(settings.basemap_refresh_rate_limit_per_minute):
        assert client.post("/api/basemap/refresh").status_code == 200
    response = client.post("/api/basemap/refresh")

    assert response.status_code == 429
