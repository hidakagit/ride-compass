from collections import defaultdict

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_region_service
from app.config import settings
from app.domain.traffic import TrafficStressBreakdown, TrafficStressRecipe
from app.infrastructure import rate_limiter
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


class FakeRegionService:
    def __init__(self, tile_bytes=b"\x00\x01\x02", traffic_stress_breakdown=None):
        self._tile_bytes = tile_bytes
        self._traffic_stress_breakdown = traffic_stress_breakdown
        self.last_request = None
        self.last_poi_request = None
        self.last_breakdown_request = None
        self.last_breakdown_recipe = None
        self.last_breakdown_road_suitability_recipe = None
        self.last_breakdown_motor_vehicle_density_recipe = None

    async def get_road_surface_tile(self, z, x, y):
        self.last_request = (z, x, y)
        return self._tile_bytes

    async def get_poi_tile(self, z, x, y):
        self.last_poi_request = (z, x, y)
        return self._tile_bytes

    async def get_traffic_stress_breakdown(
        self, osm_way_id, recipe=None, road_suitability_recipe=None, motor_vehicle_density_recipe=None
    ):
        self.last_breakdown_request = osm_way_id
        self.last_breakdown_recipe = recipe
        self.last_breakdown_road_suitability_recipe = road_suitability_recipe
        self.last_breakdown_motor_vehicle_density_recipe = motor_vehicle_density_recipe
        return self._traffic_stress_breakdown


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


def test_region_road_surface_tile_rejects_negative_x():
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService()

    try:
        response = client.get("/api/region/road-surface-tiles/14/-1/6447.pbf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400


def test_region_road_surface_tile_rejects_x_at_or_beyond_tile_index_max():
    # zoom=14では有効なxの範囲は0 <= x < 2**14=16384
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService()

    try:
        response = client.get("/api/region/road-surface-tiles/14/16384/6447.pbf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400


def test_region_road_surface_tile_rejects_y_out_of_range():
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService()

    try:
        response = client.get("/api/region/road-surface-tiles/14/14551/99999999999999999999.pbf")
    finally:
        app.dependency_overrides.clear()

    # 巨大なyは経路パラメータのintパースに失敗し422(範囲チェックまで到達しない)。
    # domain/region.pyのtile_bounds_lonlatがOverflowErrorを送出しうる極端な値を弾く
    # 目的自体は、パース可能な範囲内の値(2**z以上)のケースで検証する。
    assert response.status_code in (400, 422)


def test_region_road_surface_tile_is_rate_limited_per_client():
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService()

    try:
        # 上限-1件は実HTTPを経由せずrate_limiter側を直接埋める（実HTTP120回のラウンドトリップは
        # 境界値の検証には不要で、テスト実行時間だけを押し上げるため）。境界の1回だけ実リクエストで検証する。
        for _ in range(settings.road_tile_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit("road-tile:testclient", settings.road_tile_rate_limit_per_minute)
        assert client.get("/api/region/road-surface-tiles/14/14551/6447.pbf").status_code == 200
        response = client.get("/api/region/road-surface-tiles/14/14551/6447.pbf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429


def test_region_poi_tile_returns_mvt_bytes():
    fake = FakeRegionService(tile_bytes=b"\x04\x05\x06")
    app.dependency_overrides[get_region_service] = lambda: fake

    try:
        response = client.get("/api/region/poi-tiles/14/14551/6447.pbf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.content == b"\x04\x05\x06"
    assert response.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    assert fake.last_poi_request == (14, 14551, 6447)


def test_region_poi_tile_rejects_too_low_zoom():
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService()

    try:
        response = client.get("/api/region/poi-tiles/5/10/10.pbf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400


def test_region_poi_tile_rate_limit_is_independent_from_road_surface_tile_rate_limit():
    # T54: poi-tileはroad-tileと同じsettings.road_tile_rate_limit_per_minuteを使うが、
    # レート制限キーのprefixは別（region.py: _check_tile_rate_limit）。road-tile側の
    # 上限を使い切ってもpoi-tileには影響しないこと（road_surface_tile_rate_limit_is_
    # independent_from_basemap_rate_limitと同じ回帰観点）。
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService()

    try:
        for _ in range(settings.road_tile_rate_limit_per_minute):
            rate_limiter.check_rate_limit("road-tile:testclient", settings.road_tile_rate_limit_per_minute)
        assert client.get("/api/region/road-surface-tiles/14/14551/6447.pbf").status_code == 429

        response = client.get("/api/region/poi-tiles/14/14551/6447.pbf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200


def test_region_traffic_stress_breakdown_returns_breakdown_json():
    breakdown = TrafficStressBreakdown(
        base=4,
        cycleway_adjustment=0,
        maxspeed_adjustment=1,
        lanes_adjustment=0,
        designation_adjustment=0,
        motor_vehicle_no_override=False,
        level=4,
    )
    fake = FakeRegionService(traffic_stress_breakdown=breakdown)
    app.dependency_overrides[get_region_service] = lambda: fake

    try:
        response = client.post("/api/region/traffic-stress-breakdown", json={"osm_way_id": 12345})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == breakdown.model_dump()
    assert fake.last_breakdown_request == 12345
    assert fake.last_breakdown_recipe is None


def test_region_traffic_stress_breakdown_returns_null_when_service_returns_none():
    # DBなし構成・該当wayが無い場合はRegionService側がNoneを返す
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService(traffic_stress_breakdown=None)

    try:
        response = client.post("/api/region/traffic-stress-breakdown", json={"osm_way_id": 12345})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() is None


def test_region_traffic_stress_breakdown_rejects_non_integer_osm_way_id():
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService()

    try:
        response = client.post("/api/region/traffic-stress-breakdown", json={"osm_way_id": "not-a-number"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_region_traffic_stress_breakdown_rejects_inverted_lanes_thresholds_across_recipes():
    # lanes_low_threshold(traffic_stress_recipe)とlanes_high_threshold
    # (motor_vehicle_density_recipe、省略時は既定値4)は別モデルに分かれているため、
    # routes.py: validate_lanes_threshold_order（TrafficStressBreakdownRequest.
    # model_validator経由）が両モデルを跨いで検証することを確認する
    # （test_routes_generate.pyの同種テストと対の回帰テスト）。
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService()

    try:
        response = client.post(
            "/api/region/traffic-stress-breakdown",
            json={
                "osm_way_id": 12345,
                "traffic_stress_recipe": {**TrafficStressRecipe().model_dump(), "lanes_low_threshold": 5},
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_region_traffic_stress_breakdown_rate_limit_is_independent_from_road_surface_tile_rate_limit():
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService()

    try:
        for _ in range(settings.road_tile_rate_limit_per_minute):
            rate_limiter.check_rate_limit("road-tile:testclient", settings.road_tile_rate_limit_per_minute)
        assert client.get("/api/region/road-surface-tiles/14/14551/6447.pbf").status_code == 429

        response = client.post("/api/region/traffic-stress-breakdown", json={"osm_way_id": 12345})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200


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
