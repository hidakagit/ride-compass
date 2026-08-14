import pytest
from fastapi.testclient import TestClient

from app.api.routes import (
    GENERATE_RATE_LIMIT_PER_MINUTE,
    _generate_semaphore,
    get_route_generator,
)
from app.config import settings
from app.domain.evaluation import RoutePreference
from app.domain.route import RouteCandidate
from app.infrastructure import rate_limiter
from app.infrastructure.elevation_client import ElevationClient
from app.infrastructure.ors_client import ORSClient
from app.infrastructure.overpass_client import OverpassClient
from app.infrastructure.weather_client import WeatherClient
from app.main import app
from app.services.elevation_attribute_service import ElevationAttributeService
from app.services.elevation_service import ElevationService
from app.services.evaluation_service import EvaluationService
from app.services.graph_service import GraphService
from app.services.route_scorer import RouteScorer
from app.services.routing_service import RoutingService
from app.services.weather_service import WeatherService
from app.services.wind_service import WindService

client = TestClient(app)

REQUEST_BODY = {
    "latitude": 35.7597,
    "longitude": 139.7387,
    "distance_km": 30,
    "distance_tolerance_km": 5,
    "route_type": "loop",
}


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    # rate_limiterはプロセス内グローバルの固定窓カウンタのため、テスト間で
    # 消し込まないと前のテストのリクエストが今のテストの上限に食い込む。
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


class FakeRouteGenerator:
    engine_name = "fake-engine"

    def __init__(self, candidates: list[RouteCandidate]):
        self._candidates = candidates

    async def generate_loops(self, origin, distance_km, distance_tolerance_km):
        return self._candidates


def test_generate_routes_returns_candidates_and_engine():
    candidates = [
        RouteCandidate(
            id="route-000",
            direction_label="北",
            distance_km=29.8,
            geometry={"type": "LineString", "coordinates": [[139.7387, 35.7597], [139.75, 35.8]]},
        )
    ]
    app.dependency_overrides[get_route_generator] = lambda: FakeRouteGenerator(candidates)

    try:
        response = client.post("/api/routes/generate", json=REQUEST_BODY)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert len(body["routes"]) == 1
    assert body["routes"][0]["id"] == "route-000"
    assert body["routes"][0]["direction_label"] == "北"
    assert body["engine"] == "fake-engine"


def test_generate_routes_returns_empty_list_when_no_candidates_match():
    app.dependency_overrides[get_route_generator] = lambda: FakeRouteGenerator([])

    try:
        response = client.post("/api/routes/generate", json=REQUEST_BODY)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["routes"] == []
    assert body["engine"] == "fake-engine"


def test_generate_routes_is_rate_limited_per_client():
    # ルート生成は最も高コストなエンドポイント（外部APIクォータ・数十秒の処理時間）のため、
    # per-IPの上限を超えたリクエストは429で拒否する。
    app.dependency_overrides[get_route_generator] = lambda: FakeRouteGenerator([])

    try:
        for _ in range(GENERATE_RATE_LIMIT_PER_MINUTE):
            assert client.post("/api/routes/generate", json=REQUEST_BODY).status_code == 200
        response = client.post("/api/routes/generate", json=REQUEST_BODY)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429


async def test_generate_routes_rejects_when_concurrency_limit_reached():
    # 同時実行数の上限に達している間は待たせず429を返す（外部サービスへの負荷の積み上げ防止）。
    app.dependency_overrides[get_route_generator] = lambda: FakeRouteGenerator([])

    acquired = 0
    try:
        while not _generate_semaphore.locked():
            await _generate_semaphore.acquire()
            acquired += 1
        response = client.post("/api/routes/generate", json=REQUEST_BODY)
    finally:
        for _ in range(acquired):
            _generate_semaphore.release()
        app.dependency_overrides.clear()

    assert response.status_code == 429


def _build_route_generator_with_lightweight_deps():
    # get_route_generatorはFastAPIのDependsで解決される前提の関数だが、ここでは
    # 依存を直接渡して「settings.routing_engineに応じたエンジン選択」だけを検証する。
    # いずれの依存もコンストラクタではI/Oを行わないため、http_clientはNoneでよい。
    preference = RoutePreference()
    return get_route_generator(
        routing_service=RoutingService(ORSClient("test-key", http_client=None)),
        elevation_service=ElevationService(ElevationClient(), http_client=None),
        wind_service=WindService(WeatherService(WeatherClient(), http_client=None)),
        graph_service=GraphService(OverpassClient(), http_client=None),
        elevation_attribute_service=ElevationAttributeService(ElevationClient(), http_client=None),
        evaluation_service=EvaluationService(preference),
        weather_service=WeatherService(WeatherClient(), http_client=None),
        route_scorer=RouteScorer({"distance_weight": 0.30, "elevation_weight": 0.15, "wind_weight": 0.30, "road_weight": 0.25}),
        route_preference=preference,
    )


def test_get_route_generator_selects_engine_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "routing_engine", "openrouteservice")
    assert _build_route_generator_with_lightweight_deps().engine_name == "openrouteservice"

    monkeypatch.setattr(settings, "routing_engine", "road_graph")
    assert _build_route_generator_with_lightweight_deps().engine_name == "road_graph"
