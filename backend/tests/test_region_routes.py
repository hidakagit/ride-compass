from collections import defaultdict

from fastapi.testclient import TestClient

from app.api.routes import get_region_service
from app.infrastructure import rate_limiter
from app.main import app

client = TestClient(app)


class FakeRegionService:
    def __init__(self, tile_bytes=b"\x00\x01\x02"):
        self._tile_bytes = tile_bytes
        self.last_request = None

    async def get_road_surface_tile(self, z, x, y):
        self.last_request = (z, x, y)
        return self._tile_bytes


def test_region_road_surface_tile_returns_mvt_bytes():
    fake = FakeRegionService(tile_bytes=b"\x01\x02\x03")
    app.dependency_overrides[get_region_service] = lambda: fake

    try:
        response = client.get("/api/region/road-surface-tiles/14/14551/6447.pbf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.content == b"\x01\x02\x03"
    assert response.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    assert fake.last_request == (14, 14551, 6447)


def test_region_road_surface_tile_rejects_too_low_zoom():
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService()

    try:
        response = client.get("/api/region/road-surface-tiles/5/10/10.pbf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400


def test_region_road_surface_tile_rejects_too_high_zoom():
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService()

    try:
        response = client.get("/api/region/road-surface-tiles/20/100/100.pbf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400


def test_road_surface_tile_rate_limit_is_independent_from_basemap_rate_limit(monkeypatch):
    # 回帰テスト: check_rate_limitのキーが両エンドポイントとも生のクライアントIPだけだった頃は
    # 路面タイル(120/分)とbasemapタイル(300/分)が同じカウンタを共有していた。地図初期化・パン/ズームで
    # 継続的に発生するbasemapタイルの取得だけで路面タイルの上限を先に使い切ってしまい、路面レイヤーの
    # チェックボックスをONにしても地図に何も描画されなくなる不具合があった("road-tile:"/"basemap:"の
    # プレフィックスで分離して修正済み)。
    monkeypatch.setattr(rate_limiter, "_hits", defaultdict(list))
    for _ in range(130):
        rate_limiter.check_rate_limit("basemap:testclient", max_requests=300)

    app.dependency_overrides[get_region_service] = lambda: FakeRegionService()
    try:
        response = client.get("/api/region/road-surface-tiles/14/14551/6447.pbf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
