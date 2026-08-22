import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import RouteGenerationSetup, get_route_generation_builder
from app.api.routers.routes import _generate_semaphore
from app.config import settings
from app.domain.evaluation import RoutePreference
from app.domain.recipe import MotorVehicleDensityRecipe, RoadSuitabilityRecipe
from app.domain.route import RouteCandidate
from app.domain.traffic import CarStressRecipe
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
        car_stress_recipe_override=None,
        road_suitability_recipe_override=None,
        motor_vehicle_density_recipe_override=None,
        penalty_strength: float = 1.0,
        max_average_grade_percent: float | None = None,
    ) -> RouteGenerationSetup:
        if captured is not None:
            captured["preference"] = preference_override
            captured["scoring"] = scoring_weights_override
            captured["car_stress_recipe"] = car_stress_recipe_override
            captured["road_suitability_recipe"] = road_suitability_recipe_override
            captured["motor_vehicle_density_recipe"] = motor_vehicle_density_recipe_override
            captured["penalty_strength"] = penalty_strength
            captured["max_average_grade_percent"] = max_average_grade_percent
        return RouteGenerationSetup(
            generator=FakeRouteGenerator(candidates),
            scoring_weights=scoring_weights_override or DEFAULT_SCORING_WEIGHTS,
            route_preference=preference_override or RoutePreference(),
            car_stress_recipe=car_stress_recipe_override or CarStressRecipe(),
            road_suitability_recipe=road_suitability_recipe_override or RoadSuitabilityRecipe(),
            motor_vehicle_density_recipe=motor_vehicle_density_recipe_override or MotorVehicleDensityRecipe(),
            penalty_strength=penalty_strength,
            max_average_grade_percent=max_average_grade_percent,
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
        "car_stress_weight": 0.0, "accident_weight": 0.0,
        "night_weight": 0.0,
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


def test_generate_routes_applies_road_suitability_and_motor_vehicle_density_overrides_independently_of_car_stress():
    # 改善計画: 車との近さ材料の共有元化。道路適正・自動車密度・車ストレス(軸固有部分)を
    # 同時に上書きしても、それぞれ独立してビルダーへ渡り、conditionsへエコーされることを
    # 確認する（3つの独立したトグルが組み合わさる想定）。
    captured: dict = {}
    app.dependency_overrides[get_route_generation_builder] = override_generation_builder([], captured)
    road_suitability_recipe = {**RoadSuitabilityRecipe().model_dump(), "cycleway_track_adjustment": -3}
    motor_vehicle_density_recipe = {**MotorVehicleDensityRecipe().model_dump(), "designation_adjustment": 2}
    car_stress_recipe = {**CarStressRecipe().model_dump(), "lanes_low_adjustment": -2}

    try:
        response = client.post(
            "/api/routes/generate",
            json={
                **REQUEST_BODY,
                "road_suitability_recipe": road_suitability_recipe,
                "motor_vehicle_density_recipe": motor_vehicle_density_recipe,
                "car_stress_recipe": car_stress_recipe,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured["road_suitability_recipe"] == RoadSuitabilityRecipe(**road_suitability_recipe)
    assert captured["motor_vehicle_density_recipe"] == MotorVehicleDensityRecipe(**motor_vehicle_density_recipe)
    assert captured["car_stress_recipe"] == CarStressRecipe(**car_stress_recipe)
    conditions = response.json()["conditions"]
    assert conditions["road_suitability_recipe"] == road_suitability_recipe
    assert conditions["motor_vehicle_density_recipe"] == motor_vehicle_density_recipe
    assert conditions["car_stress_recipe"] == car_stress_recipe


def test_generate_routes_is_rate_limited_per_client():
    # ルート生成は最も高コストなエンドポイント（外部APIクォータ・数十秒の処理時間）のため、
    # per-IPの上限を超えたリクエストは429で拒否する。
    app.dependency_overrides[get_route_generation_builder] = override_generation_builder([])

    try:
        for _ in range(settings.generate_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit("generate:testclient", settings.generate_rate_limit_per_minute)
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
        # domain/recipe.pyのif/elif判定順序（threshold_adjustment）で「高い方の補正」を
        # 無効化してしまうため拒否する。改善計画: 車との近さ材料の共有元化でmaxspeed補正は
        # MotorVehicleDensityRecipeOverrideへ移設済み（routes.py:
        # MotorVehicleDensityRecipeOverride._check_threshold_order）。
        {
            "motor_vehicle_density_recipe": {
                **MotorVehicleDensityRecipe().model_dump(),
                "maxspeed_low_threshold": 60,
                "maxspeed_high_threshold": 30,
            }
        },
        # レビュー指摘の回帰テスト: lanes_low_threshold(CarStressRecipeOverride)と
        # lanes_high_threshold(MotorVehicleDensityRecipeOverride)は別モデルに分かれて
        # いるため、単体のmodel_validatorでは検証できない。routes.py:
        # validate_lanes_threshold_order（RouteGenerateRequest.model_validator経由）が
        # 両モデルを跨いで検証することを確認する。motor_vehicle_density_recipeは省略し、
        # 既定値(lanes_high_threshold=4)への暗黙フォールバックも含めて検証する。
        {"car_stress_recipe": {**CarStressRecipe().model_dump(), "lanes_low_threshold": 5}},
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
