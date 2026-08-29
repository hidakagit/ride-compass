from collections import defaultdict

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_region_service, get_wind_way_service
from app.config import settings
from app.domain.evaluation import AxisInspectorAxis, AxisInspectorResult
from app.infrastructure import rate_limiter
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


class FakeRegionService:
    def __init__(self, tile_bytes=b"\x00\x01\x02", axis_inspector_result=None):
        self._tile_bytes = tile_bytes
        self._axis_inspector_result = axis_inspector_result
        self.last_request = None
        self.last_poi_request = None
        self.last_axis_inspector_request = None

    async def get_road_surface_tile(self, z, x, y):
        self.last_request = (z, x, y)
        return self._tile_bytes

    async def get_poi_tile(self, z, x, y):
        self.last_poi_request = (z, x, y)
        return self._tile_bytes

    async def get_axis_inspector(self, osm_way_id):
        self.last_axis_inspector_request = osm_way_id
        return self._axis_inspector_result


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


def test_region_axis_inspector_returns_result_json():
    # 改善計画T292: 車ストレス専用の内訳エンドポイント（旧/api/region/car-stress-breakdown）は
    # 廃止し、軸別の汎用内訳エンドポイント（本エンドポイント）へ統合した。
    result = AxisInspectorResult(
        highway="primary",
        tags={},
        is_designated=False,
        axes=[AxisInspectorAxis(axis_id="car_stress", difficulty=75.0, weight=0.2, available=True)],
        composite_difficulty=75.0,
        covered_weight_fraction=1.0,
    )
    fake = FakeRegionService(axis_inspector_result=result)
    app.dependency_overrides[get_region_service] = lambda: fake

    try:
        response = client.post("/api/region/axis-inspector", json={"osm_way_id": 12345})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == result.model_dump()
    assert fake.last_axis_inspector_request == 12345


def test_region_axis_inspector_returns_null_when_service_returns_none():
    # DBなし構成・該当wayが無い場合はRegionService側がNoneを返す
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService(axis_inspector_result=None)

    try:
        response = client.post("/api/region/axis-inspector", json={"osm_way_id": 12345})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() is None


def test_region_axis_inspector_rejects_non_integer_osm_way_id():
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService()

    try:
        response = client.post("/api/region/axis-inspector", json={"osm_way_id": "not-a-number"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_region_axis_inspector_rate_limit_is_independent_from_road_surface_tile_rate_limit():
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService()

    try:
        for _ in range(settings.road_tile_rate_limit_per_minute):
            rate_limiter.check_rate_limit("road-tile:testclient", settings.road_tile_rate_limit_per_minute)
        assert client.get("/api/region/road-surface-tiles/14/14551/6447.pbf").status_code == 429

        response = client.post("/api/region/axis-inspector", json={"osm_way_id": 12345})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200


class FakeWindWayService:
    """改善計画T405: /api/region/dynamic-way-values/wind向けフェイク。"""

    def __init__(self, penalties=None):
        self._penalties = penalties if penalties is not None else {}
        self.last_request = None

    async def get_way_wind_penalties(self, z, x, y, at):
        self.last_request = (z, x, y, at)
        return self._penalties


def test_region_dynamic_way_values_wind_returns_penalties_json():
    fake = FakeWindWayService(penalties={1: 2.34, 2: -1.5})
    app.dependency_overrides[get_wind_way_service] = lambda: fake

    try:
        response = client.get("/api/region/dynamic-way-values/wind/14/14551/6447")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    # JSONのキーは常に文字列（intキーは自動的にstrへ変換される、Python標準のjson.dumps挙動）。
    assert response.json() == {"1": 2.34, "2": -1.5}
    assert fake.last_request == (14, 14551, 6447, None)


def test_region_dynamic_way_values_wind_passes_at_query_param():
    fake = FakeWindWayService()
    app.dependency_overrides[get_wind_way_service] = lambda: fake

    try:
        response = client.get(
            "/api/region/dynamic-way-values/wind/14/14551/6447", params={"at": "2026-08-30T09:00:00"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fake.last_request[3].isoformat() == "2026-08-30T09:00:00"


def test_region_dynamic_way_values_wind_rejects_too_low_zoom():
    app.dependency_overrides[get_wind_way_service] = lambda: FakeWindWayService()

    try:
        response = client.get("/api/region/dynamic-way-values/wind/5/10/10")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400


def test_region_dynamic_way_values_wind_rate_limit_is_independent_from_road_surface_tile_rate_limit():
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService()
    app.dependency_overrides[get_wind_way_service] = lambda: FakeWindWayService()

    try:
        for _ in range(settings.road_tile_rate_limit_per_minute):
            rate_limiter.check_rate_limit("road-tile:testclient", settings.road_tile_rate_limit_per_minute)
        assert client.get("/api/region/road-surface-tiles/14/14551/6447.pbf").status_code == 429

        response = client.get("/api/region/dynamic-way-values/wind/14/14551/6447")
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
