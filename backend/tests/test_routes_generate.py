import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import RouteGenerationSetup, get_route_generation_builder
from app.api.routers.routes import _generate_semaphore
from app.config import settings
from app.domain.evaluation import RoutePreference
from app.domain.route import RouteCandidate
from app.domain.safety import SafetyRecipe
from app.domain.traffic import TrafficStressRecipe
from app.infrastructure import rate_limiter
from app.infrastructure.elevation_client import ElevationClient
from app.infrastructure.ors_client import ORSClient
from app.infrastructure.overpass_client import OverpassClient
from app.infrastructure.weather_client import WeatherClient
from app.main import app
from app.services.elevation_attribute_service import ElevationAttributeService
from app.services.elevation_service import ElevationService
from app.services.evaluation_service import load_route_preference
from app.services.graph_service import GraphService
from app.services.route_scorer import load_scoring_weights
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

DEFAULT_SCORING_WEIGHTS = {
    "distance_weight": 0.30,
    "elevation_weight": 0.15,
    "wind_weight": 0.30,
    "road_weight": 0.25,
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


def override_generation_builder(candidates: list[RouteCandidate], captured: dict | None = None):
    """get_route_generation_builderのDI上書き。capturedを渡すと、エンドポイントが
    ビルダーへ渡した重み上書き（無ければNone）を記録する。"""

    def build(
        preference_override=None,
        scoring_weights_override=None,
        traffic_stress_recipe_override=None,
        safety_recipe_override=None,
    ) -> RouteGenerationSetup:
        if captured is not None:
            captured["preference"] = preference_override
            captured["scoring"] = scoring_weights_override
            captured["traffic_stress_recipe"] = traffic_stress_recipe_override
            captured["safety_recipe"] = safety_recipe_override
        return RouteGenerationSetup(
            generator=FakeRouteGenerator(candidates),
            scoring_weights=scoring_weights_override or DEFAULT_SCORING_WEIGHTS,
            route_preference=preference_override or RoutePreference(),
            traffic_stress_recipe=traffic_stress_recipe_override or TrafficStressRecipe(),
            safety_recipe=safety_recipe_override or SafetyRecipe(),
        )

    return lambda: build


def test_generate_routes_returns_candidates_and_engine():
    candidates = [
        RouteCandidate(
            id="route-000",
            direction_label="北",
            distance_km=29.8,
            geometry={"type": "LineString", "coordinates": [[139.7387, 35.7597], [139.75, 35.8]]},
        )
    ]
    app.dependency_overrides[get_route_generation_builder] = override_generation_builder(candidates)

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
    app.dependency_overrides[get_route_generation_builder] = override_generation_builder([])

    try:
        response = client.post("/api/routes/generate", json=REQUEST_BODY)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["routes"] == []
    assert body["engine"] == "fake-engine"


def test_generate_routes_echoes_applied_conditions():
    # 実験の記録・再現用に、実際に適用された条件（重み含む）をレスポンスへエコーする
    # （研究インターフェース改善 §10-6）。上書き無しの場合は既定重みがそのまま入る。
    app.dependency_overrides[get_route_generation_builder] = override_generation_builder([])

    try:
        response = client.post("/api/routes/generate", json=REQUEST_BODY)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    conditions = response.json()["conditions"]
    assert conditions["latitude"] == REQUEST_BODY["latitude"]
    assert conditions["longitude"] == REQUEST_BODY["longitude"]
    assert conditions["distance_km"] == REQUEST_BODY["distance_km"]
    assert conditions["distance_tolerance_km"] == REQUEST_BODY["distance_tolerance_km"]
    assert conditions["scoring_weights"] == DEFAULT_SCORING_WEIGHTS
    assert conditions["route_preference"] == RoutePreference().model_dump()
    # ISO8601（JST）。厳密な時刻は環境依存のため形式だけ確認する
    assert "+09:00" in conditions["generated_at"]


def test_generate_routes_applies_weight_overrides_and_echoes_them():
    # リクエストの重み上書きがビルダーへ渡り、conditionsに適用値がエコーされる
    # （研究インターフェース改善 §10-1）。
    captured: dict = {}
    app.dependency_overrides[get_route_generation_builder] = override_generation_builder([], captured)
    scoring_weights = {"distance_weight": 0.1, "elevation_weight": 0.2, "wind_weight": 0.3, "road_weight": 0.4}
    route_preference = {
        "elevation_weight": 0.5, "road_weight": 0.25, "wind_weight": 0.2, "stop_weight": 0.05,
        "traffic_weight": 0.0, "infra_weight": 0.0, "intersection_weight": 0.0, "accident_weight": 0.0,
        "safety_weight": 0.0,
    }

    try:
        response = client.post(
            "/api/routes/generate",
            json={**REQUEST_BODY, "scoring_weights": scoring_weights, "route_preference": route_preference},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured["scoring"] == scoring_weights
    assert captured["preference"] == RoutePreference(**route_preference)
    conditions = response.json()["conditions"]
    assert conditions["scoring_weights"] == scoring_weights
    assert conditions["route_preference"] == route_preference


def test_generate_routes_is_rate_limited_per_client():
    # ルート生成は最も高コストなエンドポイント（外部APIクォータ・数十秒の処理時間）のため、
    # per-IPの上限を超えたリクエストは429で拒否する。
    app.dependency_overrides[get_route_generation_builder] = override_generation_builder([])

    try:
        for _ in range(settings.generate_rate_limit_per_minute):
            assert client.post("/api/routes/generate", json=REQUEST_BODY).status_code == 200
        response = client.post("/api/routes/generate", json=REQUEST_BODY)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429


async def test_generate_routes_rejects_when_concurrency_limit_reached():
    # 同時実行数の上限に達している間は待たせず429を返す（外部サービスへの負荷の積み上げ防止）。
    app.dependency_overrides[get_route_generation_builder] = override_generation_builder([])

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


def _lightweight_generation_builder():
    # get_route_generation_builderはFastAPIのDependsで解決される前提の関数だが、ここでは
    # 依存を直接渡して「settings.routing_engineに応じたエンジン選択」と重みの既定値/上書きの
    # 反映だけを検証する。いずれの依存もコンストラクタではI/Oを行わないため、http_clientはNoneでよい。
    return get_route_generation_builder(
        routing_service=RoutingService(ORSClient("test-key", http_client=None)),
        elevation_service=ElevationService(ElevationClient(), http_client=None),
        wind_service=WindService(WeatherService(WeatherClient(), http_client=None)),
        graph_service=GraphService(OverpassClient(), http_client=None),
        elevation_attribute_service=ElevationAttributeService(ElevationClient(), http_client=None),
        weather_service=WeatherService(WeatherClient(), http_client=None),
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"latitude": 91},
        {"latitude": -91},
        {"longitude": 181},
        {"longitude": -181},
        {"distance_km": 0},
        {"distance_km": -5},
        {"distance_tolerance_km": 0},
        {"route_type": "not-a-real-type"},
        # 重み上書きは非負のみ許可。部分指定（フィールド欠け）は「クラス既定値が黙って入る」
        # 事故を避けるため全フィールド必須（routes.py: RoutePreferenceWeights参照）
        {"scoring_weights": {"distance_weight": -0.1, "elevation_weight": 0.2, "wind_weight": 0.3, "road_weight": 0.4}},
        {"scoring_weights": {"distance_weight": 0.5}},
        {"route_preference": {"elevation_weight": 0.5, "road_weight": -0.1, "wind_weight": 0.25}},
        {"route_preference": {"elevation_weight": 0.5}},
        # レビュー指摘の回帰テスト: maxspeed_low_threshold >= maxspeed_high_thresholdは
        # domain/traffic.pyのif/elif判定順序で「高い方の補正」を無効化してしまうため拒否する
        # （routes.py: TrafficStressRecipeOverride._check_threshold_order）。
        {
            "traffic_stress_recipe": {
                **TrafficStressRecipe().model_dump(),
                "maxspeed_low_threshold": 60,
                "maxspeed_high_threshold": 30,
            }
        },
        {
            "traffic_stress_recipe": {
                **TrafficStressRecipe().model_dump(),
                "lanes_low_threshold": 4,
                "lanes_high_threshold": 1,
            }
        },
        # SafetyRecipeOverrideにも同種の検証漏れがあったため（domain/safety.py:
        # safety_breakdownも同じif/elif判定順序）、同じ回帰テストを追加
        # （routes.py: SafetyRecipeOverride._check_threshold_order）。
        {
            "safety_recipe": {
                **SafetyRecipe().model_dump(),
                "maxspeed_low_threshold": 60,
                "maxspeed_high_threshold": 30,
            }
        },
    ],
)
def test_generate_routes_rejects_invalid_request_body(overrides):
    app.dependency_overrides[get_route_generation_builder] = override_generation_builder([])

    try:
        response = client.post("/api/routes/generate", json={**REQUEST_BODY, **overrides})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_generation_builder_selects_engine_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "routing_engine", "openrouteservice")
    assert _lightweight_generation_builder()(None, None).generator.engine_name == "openrouteservice"

    monkeypatch.setattr(settings, "routing_engine", "road_graph")
    assert _lightweight_generation_builder()(None, None).generator.engine_name == "road_graph"


def test_generation_builder_uses_yaml_defaults_when_no_override():
    setup = _lightweight_generation_builder()(None, None)

    assert setup.scoring_weights == load_scoring_weights()
    assert setup.route_preference == load_route_preference()


def test_generation_builder_uses_overrides_when_provided():
    preference = RoutePreference(elevation_weight=1.0, road_weight=0.0, wind_weight=0.0)
    scoring_weights = {"distance_weight": 1.0, "elevation_weight": 0.0, "wind_weight": 0.0, "road_weight": 0.0}

    setup = _lightweight_generation_builder()(preference, scoring_weights)

    assert setup.route_preference is preference
    assert setup.scoring_weights == scoring_weights
