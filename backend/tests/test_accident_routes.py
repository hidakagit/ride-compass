import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_accident_service, get_region_service
from app.config import settings
from app.infrastructure import rate_limiter
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


class FakeAccidentService:
    def __init__(self, tile_bytes=b"\x00\x01\x02"):
        self._tile_bytes = tile_bytes
        self.last_request = None

    async def get_accident_tile(self, z, x, y):
        self.last_request = (z, x, y)
        return self._tile_bytes


def test_region_accident_tile_returns_mvt_bytes():
    fake = FakeAccidentService(tile_bytes=b"\x01\x02\x03")
    app.dependency_overrides[get_accident_service] = lambda: fake

    try:
        response = client.get("/api/region/accident-tiles/14/14551/6447.pbf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.content == b"\x01\x02\x03"
    assert response.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    assert fake.last_request == (14, 14551, 6447)


def test_region_accident_tile_rejects_too_low_zoom():
    app.dependency_overrides[get_accident_service] = lambda: FakeAccidentService()

    try:
        response = client.get("/api/region/accident-tiles/5/10/10.pbf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400


def test_region_accident_tile_rejects_x_at_or_beyond_tile_index_max():
    app.dependency_overrides[get_accident_service] = lambda: FakeAccidentService()

    try:
        response = client.get("/api/region/accident-tiles/14/16384/6447.pbf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400


def test_region_accident_tile_is_rate_limited_per_client():
    app.dependency_overrides[get_accident_service] = lambda: FakeAccidentService()

    try:
        for _ in range(settings.accident_tile_rate_limit_per_minute):
            assert client.get("/api/region/accident-tiles/14/14551/6447.pbf").status_code == 200
        response = client.get("/api/region/accident-tiles/14/14551/6447.pbf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429


class _FakeRoadTileService:
    async def get_road_surface_tile(self, z, x, y):
        return b"\x00"


def test_accident_tile_rate_limit_is_independent_from_road_tile_rate_limit():
    # road-surface-tiles(120/分)と同じ上限値でも、キーのprefix("accident-tile:"/"road-tile:")が
    # 分かれているため片方の連打がもう片方の上限を先に使い切らないこと（region.pyの
    # 回帰テストと同じ懸念の事故タイル版）。
    app.dependency_overrides[get_region_service] = lambda: _FakeRoadTileService()
    app.dependency_overrides[get_accident_service] = lambda: FakeAccidentService()
    try:
        for _ in range(settings.road_tile_rate_limit_per_minute):
            client.get("/api/region/road-surface-tiles/14/14551/6447.pbf")
        response = client.get("/api/region/accident-tiles/14/14551/6447.pbf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
