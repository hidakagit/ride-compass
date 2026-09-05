from collections import defaultdict

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_dynamic_way_value_service, get_region_service
from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisDefinition, BreakpointLinearShape, MaterialTerm
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


class FakeDynamicWayValueService:
    """改善計画T405→T414→T423で材料id駆動へ汎用化: /api/region/dynamic-way-values/
    {material_id}向けフェイク。風・勾配どちらのテストにも使う（get_way_valuesという
    統一インターフェース、region.py参照）。"""

    def __init__(self, values=None, material_id="gradient_percent"):
        self._values = values if values is not None else {}
        self.material_id = material_id
        self.last_request = None

    async def get_way_values(self, z, x, y, at, bearing_deg, speed_kmh=None):
        self.last_request = (z, x, y, at, bearing_deg, speed_kmh)
        return self._values


# 応答はサービスの生値ではなく地図が塗る値（domain/dynamic_way_values.py:
# transform_dedicated_way_values）。風は軸のbreakpoints[(0,0),(8,100)]で難易度へ、勾配は
# 符号付き材料のまま返る。
@pytest.mark.parametrize(
    ("axis_id", "material_id", "expected"),
    [("wind", "wind_penalty", {"1": 25.0, "2": 0.0}), ("gradient", "gradient_percent", {"1": 2.0, "2": -1.5})],
)
def test_region_dynamic_way_values_returns_map_values_json(axis_id, material_id, expected):
    fake = FakeDynamicWayValueService(values={1: 2.0, 2: -1.5}, material_id=material_id)
    app.dependency_overrides[get_dynamic_way_value_service] = lambda: fake

    try:
        response = client.get(f"/api/region/dynamic-way-values/{axis_id}/14/14551/6447", params={"bearing_deg": 90})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    # JSONのキーは常に文字列（intキーは自動的にstrへ変換される、Python標準のjson.dumps挙動）。
    assert response.json() == expected
    assert fake.last_request == (14, 14551, 6447, None, 90.0, None)


@pytest.mark.parametrize("material_id", ["wind", "gradient"])
def test_region_dynamic_way_values_requires_bearing_deg_query_param(material_id):
    app.dependency_overrides[get_dynamic_way_value_service] = lambda: FakeDynamicWayValueService()

    try:
        response = client.get(f"/api/region/dynamic-way-values/{material_id}/14/14551/6447")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


# 改善計画T450: needs_bearing=Falseの材料は現状（wind/gradientともTrue）存在しないため、
# この分岐（bearing_deg省略でも422にならない）が未テストのまま宣言されていた。改善計画
# T458: dynamic_way_value_materials()はAXIS_DEFINITIONSから毎回導出する関数になった
# （固定dictではないためmonkeypatch.setitemで直接差し込めない）ため、region.py側が
# 読むAXIS_DEFINITIONS自体へダミー軸をmonkeypatchで差し込む。
def test_region_dynamic_way_values_needs_bearing_false_does_not_require_bearing_deg(monkeypatch):
    dummy_axis = AxisDefinition(
        axis_id="dummy_no_bearing",
        shape=BreakpointLinearShape(terms=[MaterialTerm(material="gradient_percent")], breakpoints=[(0.0, 0.0), (10.0, 100.0)]),
        default_weight=0.1,
        label="ダミー",
        dedicated_way_value_layer=True,
        dynamic_way_value_needs_time=False,
        dynamic_way_value_needs_bearing=False,
    )
    monkeypatch.setitem(AXIS_DEFINITIONS, "dummy_no_bearing", dummy_axis)
    fake = FakeDynamicWayValueService(values={1: 1.0})
    app.dependency_overrides[get_dynamic_way_value_service] = lambda: fake

    try:
        response = client.get("/api/region/dynamic-way-values/dummy_no_bearing/14/14551/6447")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fake.last_request == (14, 14551, 6447, None, None, None)


def test_region_dynamic_way_values_needs_speed_requires_speed_kmh_and_passes_it(monkeypatch):
    dummy_axis = AxisDefinition(
        axis_id="dummy_needs_speed",
        shape=BreakpointLinearShape(terms=[MaterialTerm(material="wind_drag_ratio")], breakpoints=[(0.0, 0.0), (5.0, 100.0)]),
        default_weight=0.1,
        label="ダミー",
        dedicated_way_value_layer=True,
        dynamic_way_value_needs_bearing=True,
        dynamic_way_value_needs_speed=True,
    )
    monkeypatch.setitem(AXIS_DEFINITIONS, "dummy_needs_speed", dummy_axis)
    fake = FakeDynamicWayValueService(values={1: 2.5}, material_id="wind_drag_ratio")
    app.dependency_overrides[get_dynamic_way_value_service] = lambda: fake

    try:
        missing = client.get("/api/region/dynamic-way-values/dummy_needs_speed/14/14551/6447", params={"bearing_deg": 0})
        ok = client.get(
            "/api/region/dynamic-way-values/dummy_needs_speed/14/14551/6447", params={"bearing_deg": 0, "speed_kmh": 25}
        )
    finally:
        app.dependency_overrides.clear()

    assert missing.status_code == 422
    assert ok.status_code == 200
    assert ok.json() == {"1": 50.0}
    assert fake.last_request == (14, 14551, 6447, None, 0.0, 25.0)


def test_region_dynamic_way_values_unknown_material_id_returns_404():
    # dependency_overridesを使わず実際のget_dynamic_way_value_serviceを通す
    # （material_idバリデーション自体の検証、改善計画T423のT411実施部分）。
    response = client.get("/api/region/dynamic-way-values/rain/14/14551/6447", params={"bearing_deg": 0})

    assert response.status_code == 404


def test_region_dynamic_way_values_wind_passes_at_query_param():
    fake = FakeDynamicWayValueService()
    app.dependency_overrides[get_dynamic_way_value_service] = lambda: fake

    try:
        response = client.get(
            "/api/region/dynamic-way-values/wind/14/14551/6447",
            params={"at": "2026-08-30T09:00:00", "bearing_deg": 0},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fake.last_request[3].isoformat() == "2026-08-30T09:00:00"


def test_region_dynamic_way_values_gradient_does_not_require_at_query_param():
    # 勾配は時刻に依存しないため、atを省略しても200（wind同様Noneが渡るだけ）。
    fake = FakeDynamicWayValueService()
    app.dependency_overrides[get_dynamic_way_value_service] = lambda: fake

    try:
        response = client.get("/api/region/dynamic-way-values/gradient/14/14551/6447", params={"bearing_deg": 0})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fake.last_request == (14, 14551, 6447, None, 0.0, None)


def test_region_dynamic_way_values_rejects_too_low_zoom():
    app.dependency_overrides[get_dynamic_way_value_service] = lambda: FakeDynamicWayValueService()

    try:
        response = client.get("/api/region/dynamic-way-values/wind/5/10/10", params={"bearing_deg": 0})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400


def test_region_dynamic_way_values_rate_limit_is_independent_from_road_surface_tile_rate_limit():
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService()
    app.dependency_overrides[get_dynamic_way_value_service] = lambda: FakeDynamicWayValueService()

    try:
        for _ in range(settings.road_tile_rate_limit_per_minute):
            rate_limiter.check_rate_limit("road-tile:testclient", settings.road_tile_rate_limit_per_minute)
        assert client.get("/api/region/road-surface-tiles/14/14551/6447.pbf").status_code == 429

        response = client.get("/api/region/dynamic-way-values/wind/14/14551/6447", params={"bearing_deg": 0})
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


def test_region_road_surface_tile_is_gzipped_for_gzip_clients():
    tile = bytes(range(256)) * 40
    fake = FakeRegionService(tile_bytes=tile)
    app.dependency_overrides[get_region_service] = lambda: fake

    try:
        response = client.get(
            "/api/region/road-surface-tiles/14/14551/6447.pbf", headers={"Accept-Encoding": "gzip"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    assert response.headers["cache-control"] == "public, max-age=3600"
    assert response.content == tile
