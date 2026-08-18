import asyncio
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from app.api.dependencies import (
    RouteGenerationBuilder,
    client_id,
    get_route_generation_builder,
    get_routing_service,
)
from app.config import settings
from app.domain.errors import RoutingError
from app.domain.evaluation import RoutePreference
from app.domain.recipe import (
    DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
    ROAD_SUITABILITY_BASE_BY_HIGHWAY,
    MotorVehicleDensityRecipe,
    RoadSuitabilityRecipe,
    validate_threshold_order,
)
from app.domain.route import Coordinates, RouteCandidate, RouteSegment
from app.domain.safety import SafetyRecipe
from app.domain.traffic import DEFAULT_TRAFFIC_STRESS_RECIPE, TrafficStressRecipe
from app.infrastructure.debug_log import record_rate_limit_rejection
from app.infrastructure.rate_limiter import check_rate_limit
from app.services.route_generator import JST
from app.services.routing_service import RoutingService

router = APIRouter()

# ルート生成の同時実行上限（settings.generate_max_concurrent、config.pyのコメント参照）。
# 上限を超えた分は待たせず429で即座に返し、ブラウザのリトライや連打で外部サービスへの
# 負荷が積み上がることを防ぐ。
_generate_semaphore = asyncio.Semaphore(settings.generate_max_concurrent)


class RoutePreviewRequest(BaseModel):
    origin: Coordinates
    destination: Coordinates


@router.post("/api/routes/preview", response_model=RouteSegment)
async def preview_route(
    request: RoutePreviewRequest,
    http_request: Request,
    routing_service: RoutingService = Depends(get_routing_service),
) -> RouteSegment:
    if not check_rate_limit(f"preview:{client_id(http_request)}", settings.preview_rate_limit_per_minute):
        record_rate_limit_rejection(
            "preview", client_id(http_request), f"{settings.preview_rate_limit_per_minute}/min"
        )
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    try:
        return await routing_service.get_route([request.origin, request.destination])
    except RoutingError as exc:
        raise HTTPException(status_code=502, detail=f"ルート取得に失敗しました: {exc}") from exc


class ScoringWeights(BaseModel):
    """total_score算出（候補集合内の相対評価、RouteScorer）の重み。キーはscoring.yamlと同じ。

    値は非負なら任意（合成時に有効な指標の重み和で正規化するため、合計を1.0にする必要は
    無い）。すべて0にした場合は合成不能としてtotal_score=Noneになる（RouteScorer参照）。
    """

    distance_weight: float = Field(ge=0)
    elevation_weight: float = Field(ge=0)
    wind_weight: float = Field(ge=0)
    road_weight: float = Field(ge=0)


class RoutePreferenceWeights(BaseModel):
    """Edge評価・区間難易度（絶対評価、EvaluationService/難易度合成）の重み。
    キーはroute_preference.yamlと同じ。

    domain/evaluation.pyのRoutePreferenceと同形だが、API境界では「フィールド省略時に
    クラス既定値が黙って入る」ことを避けるため、全フィールド必須の別モデルにしている
    （上書きするなら全軸を明示する）。
    """

    elevation_weight: float = Field(ge=0)
    road_weight: float = Field(ge=0)
    wind_weight: float = Field(ge=0)
    stop_weight: float = Field(ge=0)
    traffic_weight: float = Field(ge=0)
    infra_weight: float = Field(ge=0)
    intersection_weight: float = Field(ge=0)
    accident_weight: float = Field(ge=0)
    safety_weight: float = Field(ge=0)


class RoadSuitabilityRecipeOverride(BaseModel):
    """「道路適正」（highway別基準値＋cycleway補正）の上書き。キーはdomain/recipe.py:
    RoadSuitabilityRecipeと同じ。RoutePreferenceWeightsと同じ「全フィールド必須」の
    別モデル（上書きするなら全項目を明示する）。

    交通ストレス・安全度の両方が共通して参照する「車との近さ」(N2)の材料の1つ
    （改善計画: 車との近さ材料の共有元化）。研究モードで1箇所を上書きすると両軸へ
    反映される（軸ごとに別の値へ上書きする自由度は無い、意図した設計）。閾値ペアが
    無いため順序検証は不要。

    `base_by_highway`は「全12highwayキーを明示した完全な置き換え」を前提とする
    （このモデル自体の「全フィールド必須」方針と同じ考え方）。domain/recipe.py:
    road_suitability()はキー欠落を「そのhighwayは評価対象外」(base=None)として
    静かに扱うため、部分的なdictを許すと、そのhighway種別が交通ストレス・安全度の
    両方から同時に消える（道路適正の共有化によって影響範囲が2軸分に広がった）。
    """

    base_by_highway: dict[str, int]
    cycleway_track_adjustment: int
    cycleway_lane_adjustment: int
    cycleway_shared_adjustment: int

    @model_validator(mode="after")
    def _check_base_by_highway_keys(self) -> "RoadSuitabilityRecipeOverride":
        expected = ROAD_SUITABILITY_BASE_BY_HIGHWAY.keys()
        actual = self.base_by_highway.keys()
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            detail_parts = []
            if missing:
                detail_parts.append(f"missing={missing}")
            if extra:
                detail_parts.append(f"unknown={extra}")
            raise ValueError(f"base_by_highway must specify exactly the {len(expected)} known highway keys ({', '.join(detail_parts)})")
        return self


class MotorVehicleDensityRecipeOverride(BaseModel):
    """「自動車密度」（制限速度・車線数[多い方]・指定路線該当）の上書き。キーは
    domain/recipe.py: MotorVehicleDensityRecipeと同じ。RoadSuitabilityRecipeOverrideと
    合わせて「車との近さ」(N2)を構成する、交通ストレス・安全度が共有するもう1つの材料
    （改善計画: 車との近さ材料の共有元化）。
    """

    maxspeed_low_threshold: int
    maxspeed_low_adjustment: int
    maxspeed_high_threshold: int
    maxspeed_high_adjustment: int
    lanes_high_threshold: int
    lanes_high_adjustment: int
    designation_adjustment: int

    @model_validator(mode="after")
    def _check_threshold_order(self) -> "MotorVehicleDensityRecipeOverride":
        # domain/recipe.py: validate_threshold_orderのdocstring参照（low>=highだと
        # threshold_adjustmentの2条件が排他的でなくなる）。
        validate_threshold_order(self.maxspeed_low_threshold, self.maxspeed_high_threshold, "maxspeed")
        return self


class TrafficStressRecipeOverride(BaseModel):
    """交通ストレス軸だけが持つ判定レシピ（対面通行の少車線道路への緩和）の上書き。
    キーはdomain/traffic.py: TrafficStressRecipeと同じ。RoutePreferenceWeightsと同じ
    「全フィールド必須」の別モデル（上書きするなら全項目を明示する）。

    highway別基準値・cycleway補正・制限速度補正・車線数[多い方]補正・指定路線補正は
    RoadSuitabilityRecipeOverride/MotorVehicleDensityRecipeOverride側で上書きする
    （改善計画: 車との近さ材料の共有元化）。少車線側(lanes_low_threshold)は多車線側
    (MotorVehicleDensityRecipeOverride.lanes_high_threshold)と別モデルに分かれた
    ため、このモデル単体では閾値の大小関係を検証できない。実際の順序検証は
    `_validate_lanes_threshold_order`で、両モデルを併せ持つ`RouteGenerateRequest`/
    `TrafficStressBreakdownRequest`側の`model_validator`から行う（domain/traffic.py:
    traffic_stress_breakdown参照。low>=highだとthreshold_adjustmentの2条件が排他的で
    なくなり、両方が同時に発火して打ち消し合う）。
    """

    lanes_low_threshold: int
    lanes_low_adjustment: int


def validate_lanes_threshold_order(
    traffic_stress_recipe: "TrafficStressRecipeOverride | None",
    motor_vehicle_density_recipe: "MotorVehicleDensityRecipeOverride | None",
) -> None:
    """`lanes_low_threshold`（TrafficStressRecipeOverride）と`lanes_high_threshold`
    （MotorVehicleDensityRecipeOverride）は別モデルに分かれているため、Pydanticの
    単一モデル`model_validator`では検証できない。どちらか一方だけが上書きされる
    ケースもあるため、省略された側は既定値（DEFAULT_TRAFFIC_STRESS_RECIPE/
    DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE）を補って「実際に適用される値」どうしを
    比較する。両モデルを併せ持つリクエストボディ（`RouteGenerateRequest`/
    `TrafficStressBreakdownRequest`）の`model_validator(mode="after")`から呼ぶ。
    """
    lanes_low = (
        traffic_stress_recipe.lanes_low_threshold
        if traffic_stress_recipe is not None
        else DEFAULT_TRAFFIC_STRESS_RECIPE.lanes_low_threshold
    )
    lanes_high = (
        motor_vehicle_density_recipe.lanes_high_threshold
        if motor_vehicle_density_recipe is not None
        else DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE.lanes_high_threshold
    )
    validate_threshold_order(lanes_low, lanes_high, "lanes")


class SafetyRecipeOverride(BaseModel):
    """安全度軸だけが持つ判定レシピ（街灯・トンネル補正）の上書き。キーはdomain/safety.py:
    SafetyRecipeと同じ。TrafficStressRecipeOverrideと同じ「全フィールド必須」の別モデル
    （上書きするなら全項目を明示する）。

    highway別基準値・cycleway補正・制限速度補正・車線数[多い方]補正・指定路線補正は
    交通ストレスと共有する（RoadSuitabilityRecipeOverride/MotorVehicleDensityRecipeOverride、
    改善計画: 車との近さ材料の共有元化）ため、ここには含まない。
    """

    lit_adjustment: int
    tunnel_adjustment: int


class RouteGenerateRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    # 上限が無いと1リクエストで外部API無料枠（openrouteservice: 日次2000）を枯渇させたり、
    # road_graphエンジンでbboxが際限なく広がりタイル問い合わせが長時間ハングしうる。
    # 既存の実機検証は30kmまでのため、余裕を見つつも無制限は避ける値として100kmとする。
    distance_km: float = Field(gt=0, le=100)
    distance_tolerance_km: float = Field(gt=0, le=50, default=5.0)
    route_type: Literal["loop"] = "loop"
    # 評価重みのリクエスト単位の上書き（研究用、docs/research-interface-review-2026-08-15.md
    # §10-1）。省略時はYAML既定値（scoring.yaml / route_preference.yaml）を使う。
    # 実際に適用された値はレスポンスのconditionsへエコーされる。
    scoring_weights: ScoringWeights | None = None
    route_preference: RoutePreferenceWeights | None = None
    traffic_stress_recipe: TrafficStressRecipeOverride | None = None
    safety_recipe: SafetyRecipeOverride | None = None
    road_suitability_recipe: RoadSuitabilityRecipeOverride | None = None
    motor_vehicle_density_recipe: MotorVehicleDensityRecipeOverride | None = None

    @model_validator(mode="after")
    def _check_lanes_threshold_order(self) -> "RouteGenerateRequest":
        validate_lanes_threshold_order(self.traffic_stress_recipe, self.motor_vehicle_density_recipe)
        return self


class GenerationConditions(BaseModel):
    """この生成に実際に適用された条件のエコー（実験の記録・再現用、研究IF改善 §10-6）。

    scoring_weights / route_preference は「リクエストで上書きされた値」または
    「YAML既定値」のうち実際に使われた方。レスポンスJSONを保存すれば、同じ条件を
    scoring_weights / route_preference としてそのまま再送して再現できる。
    """

    latitude: float
    longitude: float
    distance_km: float
    distance_tolerance_km: float
    scoring_weights: ScoringWeights
    route_preference: RoutePreferenceWeights
    traffic_stress_recipe: TrafficStressRecipeOverride
    safety_recipe: SafetyRecipeOverride
    road_suitability_recipe: RoadSuitabilityRecipeOverride
    motor_vehicle_density_recipe: MotorVehicleDensityRecipeOverride
    # ISO8601（JST）。周回の風評価は生成時刻に依存するため、厳密な再現はできない点に注意
    generated_at: str


class RouteGenerateResponse(BaseModel):
    routes: list[RouteCandidate]
    # どちらのルーティングエンジンが生成した候補かの識別子（"openrouteservice" | "road_graph"）。
    # wind_score等はエンジンによって算出の意味が異なる（openrouteservice_engine.py参照）ため、
    # 評価値の精査・比較時にどちらの定義の数値かを判別できるようにする。
    engine: str
    conditions: GenerationConditions


@router.post("/api/routes/generate", response_model=RouteGenerateResponse)
async def generate_routes(
    request: RouteGenerateRequest,
    http_request: Request,
    build_generation: RouteGenerationBuilder = Depends(get_route_generation_builder),
) -> RouteGenerateResponse:
    if not check_rate_limit(f"generate:{client_id(http_request)}", settings.generate_rate_limit_per_minute):
        record_rate_limit_rejection(
            "generate", client_id(http_request), f"{settings.generate_rate_limit_per_minute}/min"
        )
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    # 同時実行数の上限に達している場合は待たせず即座に429を返す（外部サービスへの負荷が
    # 積み上がるのを防ぐ。locked()確認とacquireの間に隙間はあるが、多少の超過は許容する簡易実装）。
    if _generate_semaphore.locked():
        record_rate_limit_rejection(
            "generate-concurrency", client_id(http_request), f"concurrent={settings.generate_max_concurrent}"
        )
        raise HTTPException(status_code=429, detail="ルート生成が混み合っています。しばらく待ってから再試行してください。")

    # 重みの上書き（省略時はビルダー側でYAML既定値を読む）。適用された値はconditionsへエコーする。
    preference_override = (
        RoutePreference(**request.route_preference.model_dump()) if request.route_preference else None
    )
    scoring_override = request.scoring_weights.model_dump() if request.scoring_weights else None
    traffic_stress_recipe_override = (
        TrafficStressRecipe(**request.traffic_stress_recipe.model_dump()) if request.traffic_stress_recipe else None
    )
    safety_recipe_override = (
        SafetyRecipe(**request.safety_recipe.model_dump()) if request.safety_recipe else None
    )
    road_suitability_recipe_override = (
        RoadSuitabilityRecipe(**request.road_suitability_recipe.model_dump())
        if request.road_suitability_recipe
        else None
    )
    motor_vehicle_density_recipe_override = (
        MotorVehicleDensityRecipe(**request.motor_vehicle_density_recipe.model_dump())
        if request.motor_vehicle_density_recipe
        else None
    )
    setup = build_generation(
        preference_override,
        scoring_override,
        traffic_stress_recipe_override,
        safety_recipe_override,
        road_suitability_recipe_override,
        motor_vehicle_density_recipe_override,
    )

    async with _generate_semaphore:
        origin = Coordinates(latitude=request.latitude, longitude=request.longitude)
        candidates = await setup.generator.generate_loops(
            origin=origin,
            distance_km=request.distance_km,
            distance_tolerance_km=request.distance_tolerance_km,
        )
    return RouteGenerateResponse(
        routes=candidates,
        engine=setup.generator.engine_name,
        conditions=GenerationConditions(
            latitude=request.latitude,
            longitude=request.longitude,
            distance_km=request.distance_km,
            distance_tolerance_km=request.distance_tolerance_km,
            scoring_weights=ScoringWeights(**setup.scoring_weights),
            route_preference=RoutePreferenceWeights(**setup.route_preference.model_dump()),
            traffic_stress_recipe=TrafficStressRecipeOverride(**setup.traffic_stress_recipe.model_dump()),
            safety_recipe=SafetyRecipeOverride(**setup.safety_recipe.model_dump()),
            road_suitability_recipe=RoadSuitabilityRecipeOverride(**setup.road_suitability_recipe.model_dump()),
            motor_vehicle_density_recipe=MotorVehicleDensityRecipeOverride(
                **setup.motor_vehicle_density_recipe.model_dump()
            ),
            generated_at=datetime.now(JST).isoformat(),
        ),
    )
