"""`api/routers/region.py`——地域の配信（路面・点・土地被覆のタイル、動的材料の値、区間インスペクタ）のHTTPの入口。

確かめるのは、経路ごとの受け渡し（要求のどの値がサービスへ渡り、サービスの結果が応答のどこへ出るか）と、この口が
使う判断: タイル座標の範囲（`_tile_http.py: validate_tile_coords`。土地被覆は自分のズーム範囲）、一時的に取れなかった
タイルをキャッシュさせないこと（`_tile_http.py: tile_response`）、宣言に無い点のレイヤー・配信できない軸の404、
条件の欠けの422（`domain/dynamic_way_values.py: assemble_conditions`）、土地被覆のラスタが無いときの503、
区間インスペクタが条件の揃った材料だけを足すこと（`services/dedicated_way_values.py: DirectionalMaterialService`）、
種類ごとに別に数えるレート制限。

差し替えるのは、注入されるサービス（`RegionService`・配信サービス。区間インスペクタは、代役の`RegionService`と材料で
組んだ本物の`AxisInspectorService`を注入する）・土地被覆のタイルの取得・道路網の読み出し・レート制限の記録だけ。

ここで見ないもの:
- タイルの中身とキャッシュ → `test_region_service.py`・`test_landcover_tile.py`
- 地図が塗る値への写し方 → `test_dynamic_way_values.py`
- 重みの検証（公開軸をすべて明示する等） → `test_routes_generate.py`（同じ`RoutePreferenceWeights`）
- キャッシュの方針の表・圧縮する種類 → `test_cache_policy.py`・`test_response_compression.py`
- レート制限の数え方そのもの → `test_rate_limiter.py`
- 同時実行の上限（semaphore）。待たせるだけで、応答には現れない
"""

import inspect
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import dependencies
from app.api.cache_policy import BATCH_TILE, NO_STORE
from app.api.dependencies import (
    get_axis_inspector_service,
    get_dedicated_way_value_service,
    get_region_service,
)
from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisDefinition, BreakpointLinearShape, MaterialTerm
from app.config import settings
from app.domain.axis_inspector import AxisInspectorAxis, AxisInspectorResult, InspectorComposite
from app.domain.region import ROAD_TILE_MAX_ZOOM, ROAD_TILE_MIN_ZOOM
from app.infrastructure import rate_limiter
from app.infrastructure.derived_data_meta import DataRevisions
from app.infrastructure.point_tile_layers import POINT_TILE_LAYERS
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.tile_serving import TileResponse
from app.domain.dynamic_way_values import transform_dedicated_way_values
from app.services.dedicated_way_values import DirectionalMaterialService
from app.services.region_service import AxisInspectorService
from app.services.gradient_way_service import GradientConditions
from app.services.wind_way_service import WindConditions
from app.main import app
from app.api.routers import region as region_router
from app.domain.landcover import LANDCOVER_TILE_MAX_ZOOM, LANDCOVER_TILE_MIN_ZOOM
from tests.axis_system_fixture import axis_definition, replaced_axis_definitions
from tests.bound_fake import bound

client = TestClient(app)

POINT_LAYER = next(iter(POINT_TILE_LAYERS))


class FakeRegionService:
    def __init__(self, tile_bytes=b"\x00\x01\x02", axis_inspector_result=None, cacheable=True):
        self._tile_bytes = tile_bytes
        self._axis_inspector_result = axis_inspector_result
        self._cacheable = cacheable
        # 頼まれたタイル（点のレイヤーの名前・路面ならNone、z、x、y）
        self.tile_request = None
        self.last_axis_inspector_request = None

    async def get_road_surface_tile(self, z, x, y):
        self.tile_request = (None, z, x, y)
        return TileResponse(self._tile_bytes, cacheable=self._cacheable)

    async def get_point_tile(self, layer, z, x, y):
        self.tile_request = (layer.name, z, x, y)
        return TileResponse(self._tile_bytes, cacheable=self._cacheable)

    async def get_axis_inspector(self, osm_way_id, edge_id=None, dynamic_materials=None, preference=None):
        self.last_axis_inspector_request = (osm_way_id, edge_id, dynamic_materials)
        self.last_axis_inspector_preference = preference
        return self._axis_inspector_result


class NoDirectionalMaterials:
    """専用配信の材料を引かない代役（材料の受け渡しを見ないテストが使う）。"""

    async def materials(self, *args):
        return {}


#: 区間インスペクタの要求が必ず運ぶもの（押した道・押したタイル・走行方位）。
INSPECTED = {"osm_way_id": 12345, "z": 14, "x": 14551, "y": 6447, "bearing_deg": 90.0}


# 一時的な失敗（DB障害・混雑）で取れなかった空タイルを1時間キャッシュさせると、サーバーが回復した後も
# 利用者のブラウザにはその区画の空白が残り続ける。
@pytest.mark.parametrize(
    ("path", "cacheable", "requested", "cache_control"),
    [
        ("/api/region/road-surface-tiles/14/14551/6447.pbf", True, (None, 14, 14551, 6447), BATCH_TILE),
        ("/api/region/road-surface-tiles/14/14551/6447.pbf", False, (None, 14, 14551, 6447), NO_STORE),
        (f"/api/region/point-tiles/{POINT_LAYER}/14/14551/6447.pbf", False, (POINT_LAYER, 14, 14551, 6447), NO_STORE),
    ],
)
def test_region_tiles_hand_the_services_mvt_over(path, cacheable, requested, cache_control):
    tile = bytes(range(256)) * 40  # 圧縮する大きさを超える
    fake = FakeRegionService(tile_bytes=tile, cacheable=cacheable)
    app.dependency_overrides[get_region_service] = lambda: fake

    try:
        response = client.get(path, headers={"Accept-Encoding": "gzip"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.content == tile
    assert response.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["cache-control"] == cache_control.header()
    assert fake.tile_request == requested


@pytest.mark.usefixtures("dedicated_axes")
@pytest.mark.parametrize(
    "path",
    [
        f"/api/region/road-surface-tiles/{ROAD_TILE_MIN_ZOOM - 1}/0/0.pbf",
        f"/api/region/road-surface-tiles/{ROAD_TILE_MAX_ZOOM + 1}/0/0.pbf",
        "/api/region/road-surface-tiles/14/-1/6447.pbf",
        f"/api/region/road-surface-tiles/14/{2**14}/6447.pbf",
        f"/api/region/road-surface-tiles/14/14551/{2**14}.pbf",
        f"/api/region/point-tiles/{POINT_LAYER}/{ROAD_TILE_MIN_ZOOM - 1}/0/0.pbf",
        f"/api/region/dynamic-way-values/axis_way_value_signed/{ROAD_TILE_MIN_ZOOM - 1}/0/0?bearing_deg=0",
    ],
)
def test_region_tiles_outside_the_served_range_are_refused(path):
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService()
    app.dependency_overrides[get_dedicated_way_value_service] = lambda: FakeDynamicWayValueService()

    try:
        response = client.get(path)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400


def test_region_point_tile_rejects_an_undeclared_layer():
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService()

    try:
        response = client.get("/api/region/point-tiles/no-such-layer/14/14551/6447.pbf")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


@pytest.mark.usefixtures("dedicated_axes")
def test_each_kind_of_region_request_is_counted_on_its_own():
    """路面・点のレイヤーごと・動的材料・区間インスペクタは、それぞれ別の回数で上限に当たる。

    回数を分け合うと、1つの種類の取得だけでほかの種類の上限を先に使い切り、地図の別のレイヤーが描かれなくなる。
    """
    limit = settings.road_tile_rate_limit_per_minute
    exhausted_layer, *other_layers = POINT_TILE_LAYERS
    road = "/api/region/road-surface-tiles/14/14551/6447.pbf"
    point = "/api/region/point-tiles/{}/14/14551/6447.pbf"
    app.dependency_overrides[get_region_service] = lambda: FakeRegionService()
    app.dependency_overrides[get_dedicated_way_value_service] = lambda: FakeDynamicWayValueService()
    app.dependency_overrides[get_axis_inspector_service] = lambda: AxisInspectorService(
        FakeRegionService(), NoDirectionalMaterials()
    )

    try:
        # 上限-1件は実HTTPを経由せず記録を直接埋め、境界の1回だけ実リクエストで見る。
        for key in ("road-tile", f"{exhausted_layer}-tile"):
            for _ in range(limit - 1):
                rate_limiter.check_rate_limit(f"{key}:testclient", limit)
        exhausted_point = point.format(exhausted_layer)
        exhausted = [client.get(path).status_code for path in (road, road, exhausted_point, exhausted_point)]
        others = [client.get(point.format(layer)).status_code for layer in other_layers]
        others.append(
            client.get(
                "/api/region/dynamic-way-values/axis_way_value_signed/14/14551/6447", params={"bearing_deg": 0}
            ).status_code
        )
        others.append(client.post("/api/region/axis-inspector", json=INSPECTED).status_code)
    finally:
        app.dependency_overrides.clear()

    assert exhausted == [200, 429, 200, 429]
    assert other_layers
    assert others == [200] * len(others)


def test_region_axis_inspector_hands_the_maps_direction_and_the_result_over():
    """地図が指定している走行方位・時刻・想定速度が、方向依存の材料を引く側まで届き、引いた値と
    クリックされたフィーチャーの識別子がサービスへ渡り、その結果が応答になる。

    届かないと、1本の道が往復2方向で違う値を持つ材料（勾配・風）を算出できず、地図が色を塗っている
    軸だけが内訳で「データなし」になる。識別子が届かないと、地図が区間単位で塗っている道でも内訳だけが
    way単位になり、同じ場所で色と数字が食い違う。
    """
    result = AxisInspectorResult(
        highway="primary",
        tags={},
        axes=[AxisInspectorAxis(axis_id="axis_b", difficulty=75.0, weight=0.2, contribution=75.0)],
        composite_difficulty=InspectorComposite(value=75.0, covered_weight_fraction=1.0),
    )
    fake = FakeRegionService(axis_inspector_result=result)
    seen = {}

    class FakeDirectionalMaterialService:
        async def materials(self, *args):
            seen["args"] = args
            return {"some_material": 4.2}

    app.dependency_overrides[get_axis_inspector_service] = lambda: AxisInspectorService(
        fake, FakeDirectionalMaterialService()
    )
    try:
        response = client.post(
            "/api/region/axis-inspector",
            json={
                "osm_way_id": 12345,
                "feature_key": "way-12345-seg0-fwd",
                "z": 14,
                "x": 14551,
                "y": 6447,
                "bearing_deg": 90.0,
                "at": "2026-09-21T09:00:00+00:00",
                "speed_kmh": 20.0,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == result.model_dump()
    assert seen["args"] == (
        12345,
        "way-12345-seg0-fwd",
        14,
        14551,
        6447,
        datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc),
        90.0,
        20.0,
    )
    assert fake.last_axis_inspector_request == (
        12345,
        "way-12345-seg0-fwd",
        {"some_material": 4.2},
    )


# 地図の配信なら422になる欠けは、内訳ではその材料だけを「データなし」にする（同じ組み立てで判定する）。
@pytest.mark.usefixtures("dedicated_axes")
@pytest.mark.parametrize(
    ("given", "found"),
    [
        ({}, {"gradient_percent": 2.0}),
        ({"speed_kmh": 20.0}, {"gradient_percent": 2.0, "wind_drag_ratio": 1.0}),
    ],
)
def test_region_axis_inspector_leaves_out_materials_whose_conditions_are_missing(given, found):
    fake = FakeRegionService(axis_inspector_result=None)
    services = {
        "wind_drag_ratio": FakeDynamicWayValueService({"12345": 1.0}, "wind_drag_ratio", WindConditions),
        "gradient_percent": FakeDynamicWayValueService({"12345": 2.0}, "gradient_percent", GradientConditions),
    }
    app.dependency_overrides[get_axis_inspector_service] = lambda: AxisInspectorService(
        fake, DirectionalMaterialService(services.__getitem__)
    )

    try:
        response = client.post("/api/region/axis-inspector", json={**INSPECTED, **given})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fake.last_axis_inspector_request[2] == found


class FakeDynamicWayValueService:
    """DBを読む配信サービスの代役。受け取る条件の型は本物のサービスのものを渡す——要求から
    何を組み立てるか（`assemble_conditions`）は本物を通したいため。"""

    def __init__(self, values=None, material_id="gradient_percent", conditions_type=GradientConditions):
        self._values = values if values is not None else {}
        self.material_id = material_id
        self.conditions_type = conditions_type
        self.last_request = None

    async def get_way_values(self, z, x, y, conditions):
        self.last_request = (z, x, y, conditions)
        return self._values


#: 専用way値配信を持つ軸。時刻・方位・速度を要るもの（得点を塗る）と、方位だけを要るもの
#: （符号付きの生値を塗る）の2本。
DEDICATED_AXES = {
    "axis_way_value_scored": AxisDefinition(
        axis_id="axis_way_value_scored",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="wind_drag_ratio")],
            breakpoints=[(-1.0, 0.0), (0.0, 20.0), (4.0, 100.0)],
        ),
        default_weight=0.2,
        label="軸ウ",
        dedicated_way_value_layer=True,
    ),
    "axis_way_value_signed": AxisDefinition(
        axis_id="axis_way_value_signed",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="gradient_percent")],
            preprocess="abs",
            breakpoints=[(0.0, 0.0), (5.0, 50.0), (10.0, 100.0)],
        ),
        default_weight=0.2,
        label="軸グ",
        dedicated_way_value_layer=True,
    ),
}


@pytest.fixture
def dedicated_axes():
    with replaced_axis_definitions(DEDICATED_AXES):
        yield


# 応答はサービスの生値ではなく**地図が塗る値**（domain/dynamic_way_values.py:
# transform_dedicated_way_values）。写像そのものの検証はtest_dynamic_way_values.pyが持つため、ここでは
# 軸の折れ点を写経せず同じ関数へ通した結果と突き合わせる——見たいのは「エンドポイントがこの写像を通すか」。
# 要るクエリはサービスが受け取る条件の型が決め、型に無いもの（勾配の時刻・速度）は省いても配る。
@pytest.mark.usefixtures("dedicated_axes")
@pytest.mark.parametrize(
    ("axis_id", "material_id", "params", "conditions"),
    [
        (
            "axis_way_value_scored",
            "wind_drag_ratio",
            {"bearing_deg": 90, "speed_kmh": 20.0, "at": "2026-08-30T09:00:00"},
            WindConditions(bearing_deg=90.0, speed_kmh=20.0, at=datetime(2026, 8, 30, 9, 0)),
        ),
        ("axis_way_value_signed", "gradient_percent", {"bearing_deg": 90}, GradientConditions(bearing_deg=90.0)),
    ],
)
def test_region_dedicated_way_values_returns_map_values_json(axis_id, material_id, params, conditions):
    raw = {"1": 2.0, "2": -1.5}
    expected = transform_dedicated_way_values(AXIS_DEFINITIONS[axis_id], material_id, raw)
    fake = FakeDynamicWayValueService(values=dict(raw), material_id=material_id, conditions_type=type(conditions))
    app.dependency_overrides[get_dedicated_way_value_service] = lambda: fake

    try:
        response = client.get(f"/api/region/dynamic-way-values/{axis_id}/14/14551/6447", params=params)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == expected
    assert fake.last_request == (14, 14551, 6447, conditions)


@pytest.mark.usefixtures("dedicated_axes")
def test_region_dedicated_way_values_names_the_missing_condition():
    fake = FakeDynamicWayValueService(material_id="wind_drag_ratio", conditions_type=WindConditions)
    app.dependency_overrides[get_dedicated_way_value_service] = lambda: fake

    try:
        response = client.get(
            "/api/region/dynamic-way-values/axis_way_value_scored/14/14551/6447", params={"speed_kmh": 20.0}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "bearing_deg" in response.json()["detail"]


class UncoveredRepository:
    """どのタイルも取込範囲外と答えるDBの代役。"""

    async def get_data_revisions(self):
        return DataRevisions(derived=1, imported=1)

    async def get_feature_gradient_inputs_in_tile(self, *args, **kwargs):
        inspect.signature(RoadGraphRepository.get_feature_gradient_inputs_in_tile).bind(self, *args, **kwargs)
        return None


# 配信のサービスは軸の名前ではなく、軸が参照する材料で引く。実際の
# get_dedicated_way_value_serviceを通し、初めて見る名前の軸が材料だけで配信されること・
# 配信の実装が無い材料だけを参照する軸と、無い軸は404になることを見る（Noneは軸を置かない）。
@pytest.mark.parametrize(("material", "status"), [("gradient_percent", 200), ("maxspeed_kmh", 404), (None, 404)])
def test_region_dedicated_way_values_resolves_the_service_by_the_axis_material(monkeypatch, material, status):
    if material is not None:
        axis = axis_definition("axis_new_name", material=material, dedicated_way_value_layer=True)
        monkeypatch.setitem(AXIS_DEFINITIONS, "axis_new_name", axis)
    monkeypatch.setattr(dependencies, "RoadGraphRepository", lambda session: UncoveredRepository())

    response = client.get("/api/region/dynamic-way-values/axis_new_name/14/14551/6447", params={"bearing_deg": 0})

    assert response.status_code == status


# ---- 土地被覆ラスタタイル（`/api/region/landcover-tiles`） ----


@pytest.fixture
def landcover_tiles(monkeypatch):
    """配信の口が呼ぶタイルの取得（サービス）の代役。返す値は`result`で決め、呼ばれた座標を`calls`に残す。"""
    state = {"result": TileResponse(b"png-bytes"), "calls": []}

    async def fake(z, x, y):
        state["calls"].append((z, x, y))
        return state["result"]

    monkeypatch.setattr(region_router, "get_landcover_tile", bound(region_router.get_landcover_tile, fake))
    return state


def test_landcover_tile_endpoint_returns_the_tile_as_png(landcover_tiles):
    response = client.get("/api/region/landcover-tiles/10/905/403.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == b"png-bytes"
    assert landcover_tiles["calls"] == [(10, 905, 403)]


def test_landcover_tile_endpoint_without_raster_reports_unavailable(landcover_tiles):
    # ラスタが1枚も無いのは「範囲外で空」ではない。空を返すと、地図のチップは正常なのに白紙になる
    landcover_tiles["result"] = None

    assert client.get("/api/region/landcover-tiles/10/905/403.png").status_code == 503


@pytest.mark.usefixtures("landcover_tiles")
@pytest.mark.parametrize(
    ("z", "status"),
    [
        (LANDCOVER_TILE_MIN_ZOOM - 1, 400),
        (LANDCOVER_TILE_MIN_ZOOM, 200),
        (LANDCOVER_TILE_MAX_ZOOM, 200),
        (LANDCOVER_TILE_MAX_ZOOM + 1, 400),
    ],
)
def test_landcover_tile_endpoint_serves_only_its_own_zoom_range(z, status):
    assert client.get(f"/api/region/landcover-tiles/{z}/1/1.png").status_code == status


#: 重みを送る検査に使う公開軸。
_WEIGHTED_AXES = {
    axis_id: axis_definition(axis_id, is_published=True) for axis_id in ("axis_p", "axis_q")
}


@pytest.fixture
def weighted_axes():
    with replaced_axis_definitions(_WEIGHTED_AXES):
        yield


@pytest.mark.usefixtures("weighted_axes")
def test_region_axis_inspector_uses_the_weights_it_is_sent():
    """合成は利用者がいま設定している重みで計算する。送らなければ既定の重み。"""
    fake = FakeRegionService(axis_inspector_result=None)
    app.dependency_overrides[get_axis_inspector_service] = lambda: AxisInspectorService(fake, NoDirectionalMaterials())
    weights = {axis_id: 0.0 for axis_id in _WEIGHTED_AXES}
    try:
        sent = client.post("/api/region/axis-inspector", json={**INSPECTED, "route_preference": weights})
        sent_preference = fake.last_axis_inspector_preference
        omitted = client.post("/api/region/axis-inspector", json=INSPECTED)
    finally:
        app.dependency_overrides.clear()

    assert sent.status_code == 200
    assert sent_preference.weights == weights
    assert omitted.status_code == 200
    assert fake.last_axis_inspector_preference is None
