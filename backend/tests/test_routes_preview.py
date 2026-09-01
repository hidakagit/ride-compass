import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_preview_builder
from app.config import settings
from app.domain.attributes import EdgeMaterialBundle, SearchMaterials
from app.domain.evaluation import build_static_edge_score_matrix
from app.domain.errors import RoutingError
from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.domain.route import Coordinates, RouteSegment
from app.infrastructure import rate_limiter
from app.main import app

# 改善計画T350: 本番相当の14軸（実軸id前提のロジック用）はtests/conftest.pyのセッション
# スコープautouseフィクスチャが全テスト共通で用意する（tests/realistic_axis_fixtures.py参照）。

client = TestClient(app)

REQUEST_BODY = {
    "origin": {"latitude": 35.7597, "longitude": 139.7387},
    "destination": {"latitude": 35.71, "longitude": 139.75},
}


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    # rate_limiterはプロセス内グローバルの固定窓カウンタのため、テスト間で
    # 消し込まないと前のテストのリクエストが今のテストの上限に食い込む。
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


def test_preview_route_returns_segment_on_success():
    # `get_preview_builder`自体を丸ごとフェイクへ差し替える（実DBアクセスを避けつつ、
    # ルータが返すレスポンス整形を検証する）。
    segment = RouteSegment(
        distance_km=5.0,
        duration_minutes=10.0,
        geometry={"type": "LineString", "coordinates": [[139.7387, 35.7597], [139.75, 35.71]]},
    )

    async def fake_preview(origin, destination):
        return segment

    app.dependency_overrides[get_preview_builder] = lambda: fake_preview

    try:
        response = client.post("/api/routes/preview", json=REQUEST_BODY)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["distance_km"] == 5.0
    assert body["duration_minutes"] == 10.0


def test_preview_route_returns_502_on_routing_error():
    async def fake_preview(origin, destination):
        raise RoutingError("road_graph: no path found between origin and destination")

    app.dependency_overrides[get_preview_builder] = lambda: fake_preview

    try:
        response = client.post("/api/routes/preview", json=REQUEST_BODY)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert "ルート取得に失敗しました" in response.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        {"origin": {"latitude": 91, "longitude": 139.7387}, "destination": REQUEST_BODY["destination"]},
        {"origin": {"latitude": 35.7597, "longitude": 181}, "destination": REQUEST_BODY["destination"]},
        {"origin": REQUEST_BODY["origin"], "destination": {"latitude": -91, "longitude": 139.75}},
    ],
)
def test_preview_route_rejects_out_of_range_coordinates(body):
    response = client.post("/api/routes/preview", json=body)

    assert response.status_code == 422


def test_preview_route_is_rate_limited_per_client():
    segment = RouteSegment(
        distance_km=5.0,
        duration_minutes=10.0,
        geometry={"type": "LineString", "coordinates": [[139.7387, 35.7597], [139.75, 35.71]]},
    )

    async def fake_preview(origin, destination):
        return segment

    app.dependency_overrides[get_preview_builder] = lambda: fake_preview

    try:
        for _ in range(settings.preview_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit("preview:testclient", settings.preview_rate_limit_per_minute)
        assert client.post("/api/routes/preview", json=REQUEST_BODY).status_code == 200
        response = client.post("/api/routes/preview", json=REQUEST_BODY)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429


def test_preview_route_uses_preview_builder_and_returns_road_graph_result():
    """ルータが`get_preview_builder`経由であること自体を、直接オーバーライドで確認する
    （`get_route_generation_builder`と同じ、ビルダーを丸ごと差し替えるテスト方式）。"""
    segment = RouteSegment(
        distance_km=3.3, duration_minutes=9.9, geometry={"type": "LineString", "coordinates": []}
    )
    captured = {}

    async def fake_preview(origin, destination):
        captured["origin"] = origin
        captured["destination"] = destination
        return segment

    app.dependency_overrides[get_preview_builder] = lambda: fake_preview

    try:
        response = client.post("/api/routes/preview", json=REQUEST_BODY)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["distance_km"] == 3.3
    assert captured["origin"].latitude == REQUEST_BODY["origin"]["latitude"]


def test_preview_route_returns_502_when_preview_builder_raises():
    async def fake_preview(origin, destination):
        raise RoutingError("road_graph: no path found between origin and destination")

    app.dependency_overrides[get_preview_builder] = lambda: fake_preview

    try:
        response = client.post("/api/routes/preview", json=REQUEST_BODY)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502


class _FakeGraphServiceForPreview:
    def __init__(self, graph: RoadGraph | None):
        self._graph = graph

    async def get_search_materials_for_bbox(self, bbox):
        if self._graph is None or not self._graph.edges:
            return None
        materials = {
            edge_id: EdgeMaterialBundle(
                surface=None, way_tags={"highway": edge.highway}, attribute_counts=None,
                elevation_attribute=None, is_designated=False,
            )
            for edge_id, edge in self._graph.edges.items()
        }
        # 改善計画T536: get_search_materials_for_bboxは(SearchMaterials, StaticEdgeScoreMatrix)
        # のタプルを返す契約になった（road_graph_engine.py: _build_search_graph参照）。
        score_matrix = build_static_edge_score_matrix(self._graph, materials, 0)
        return SearchMaterials(graph=self._graph, materials=materials), score_matrix

    async def get_accident_years_covered(self) -> int:
        return 0

    async def get_edges_with_geometry(self, edge_ids):
        return {}


class _FakeWeatherServiceForPreview:
    async def get_conditions(self, point, at=None):
        return None


async def test_get_preview_builder_calls_preview_segment():
    """`get_preview_builder`自体を、HTTP経由ではなく直接呼んで検証する（router越しの
    オーバーライドでは配線ロジック自体のバグを検知できないため）。"""
    node_a = Node(node_id="a", latitude=35.0, longitude=139.0)
    node_b = Node(node_id="b", latitude=35.01, longitude=139.0)
    edge = DirectedEdge(
        edge_id="e1", from_node_id="a", to_node_id="b",
        geometry=[[35.0, 139.0], [35.01, 139.0]], distance_m=1111.0, highway="residential",
    )
    graph = RoadGraph(graph_version="test", nodes={"a": node_a, "b": node_b}, edges={"e1": edge})

    build = get_preview_builder(
        graph_service=_FakeGraphServiceForPreview(graph),
        elevation_attribute_service=None,
        weather_service=_FakeWeatherServiceForPreview(),
    )

    segment = await build(
        Coordinates(latitude=35.0, longitude=139.0), Coordinates(latitude=35.01, longitude=139.0)
    )

    assert segment.distance_km == 1.11
    assert segment.duration_minutes > 0


async def test_get_preview_builder_raises_routing_error_when_unreachable():
    build = get_preview_builder(
        graph_service=_FakeGraphServiceForPreview(None),
        elevation_attribute_service=None,
        weather_service=_FakeWeatherServiceForPreview(),
    )

    with pytest.raises(RoutingError):
        await build(Coordinates(latitude=35.0, longitude=139.0), Coordinates(latitude=35.01, longitude=139.0))
