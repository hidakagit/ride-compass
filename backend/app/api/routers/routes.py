import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.dependencies import client_id, get_route_generator, get_routing_service
from app.config import settings
from app.domain.errors import RoutingError
from app.domain.route import Coordinates, RouteCandidate, RouteSegment
from app.infrastructure.debug_log import record_rate_limit_rejection
from app.infrastructure.rate_limiter import check_rate_limit
from app.services.route_generator import RouteGenerator
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


class RouteGenerateRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    # 上限が無いと1リクエストで外部API無料枠（openrouteservice: 日次2000）を枯渇させたり、
    # road_graphエンジンでbboxが際限なく広がりタイル問い合わせが長時間ハングしうる。
    # 既存の実機検証は30kmまでのため、余裕を見つつも無制限は避ける値として100kmとする。
    distance_km: float = Field(gt=0, le=100)
    distance_tolerance_km: float = Field(gt=0, le=50, default=5.0)
    route_type: Literal["loop"] = "loop"


class RouteGenerateResponse(BaseModel):
    routes: list[RouteCandidate]
    # どちらのルーティングエンジンが生成した候補かの識別子（"openrouteservice" | "road_graph"）。
    # wind_score等はエンジンによって算出の意味が異なる（openrouteservice_engine.py参照）ため、
    # 評価値の精査・比較時にどちらの定義の数値かを判別できるようにする。
    engine: str


@router.post("/api/routes/generate", response_model=RouteGenerateResponse)
async def generate_routes(
    request: RouteGenerateRequest,
    http_request: Request,
    route_generator: RouteGenerator = Depends(get_route_generator),
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
    async with _generate_semaphore:
        origin = Coordinates(latitude=request.latitude, longitude=request.longitude)
        candidates = await route_generator.generate_loops(
            origin=origin,
            distance_km=request.distance_km,
            distance_tolerance_km=request.distance_tolerance_km,
        )
    return RouteGenerateResponse(routes=candidates, engine=route_generator.engine_name)
