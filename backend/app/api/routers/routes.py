import asyncio
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.dependencies import (
    RouteGenerationBuilder,
    client_id,
    get_route_generation_builder,
    get_routing_service,
)
from app.config import settings
from app.domain.errors import RoutingError
from app.domain.evaluation import RoutePreference
from app.domain.route import Coordinates, RouteCandidate, RouteSegment
from app.domain.traffic import TrafficStressRecipe
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


class TrafficStressRecipeOverride(BaseModel):
    """交通ストレス軸の判定レシピ（一次情報→二次情報の変換式そのもの）の上書き。
    キーはdomain/traffic.py: TrafficStressRecipeと同じ。RoutePreferenceWeightsと同じ
    「全フィールド必須」の別モデル（上書きするなら全項目を明示する）。

    RoutePreferenceWeights（軸間の重み）とは別階層で、こちらは交通ストレス軸自体の中身
    （highway別基準値・各補正の閾値・補正量）を上書きする。研究モードでのレシピ調整用。
    """

    base_by_highway: dict[str, int]
    cycleway_track_adjustment: int
    cycleway_lane_adjustment: int
    cycleway_shared_adjustment: int
    maxspeed_low_threshold: int
    maxspeed_low_adjustment: int
    maxspeed_high_threshold: int
    maxspeed_high_adjustment: int
    lanes_high_threshold: int
    lanes_high_adjustment: int
    lanes_low_threshold: int
    lanes_low_adjustment: int
    designation_adjustment: int


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
    setup = build_generation(preference_override, scoring_override, traffic_stress_recipe_override)

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
            generated_at=datetime.now(JST).isoformat(),
        ),
    )
