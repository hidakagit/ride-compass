from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.config import settings
from app.domain.errors import RoutingError
from app.domain.region import ROAD_TILE_MAX_ZOOM, ROAD_TILE_MIN_ZOOM
from app.domain.route import Coordinates, RouteCandidate, RouteSegment
from app.domain.weather import WeatherConditions
from app.infrastructure import tile_cache
from app.infrastructure.basemap_client import BasemapClient
from app.infrastructure.elevation_client import ElevationClient
from app.infrastructure.ors_client import ORSClient
from app.infrastructure.overpass_client import OverpassClient
from app.infrastructure.rate_limiter import check_rate_limit
from app.infrastructure.weather_client import WeatherClient
from app.services.elevation_service import ElevationService
from app.services.region_service import RegionService
from app.services.route_generator import RouteGenerator
from app.services.route_scorer import RouteScorer, load_scoring_weights
from app.services.routing_service import RoutingService
from app.services.weather_service import WeatherService
from app.services.wind_service import WindService

router = APIRouter()

# 認証なしで叩ける路面タイル/basemapプロキシへの簡易な歯止め（1クライアントIPあたり1分間の上限）。
# 路面タイルはOverpassへの実問い合わせ・ディスクキャッシュ書き込みを、basemapはOpenFreeMapへの
# 中継を伴うため、無制限に叩かれると外部サービス負荷やディスク消費に繋がる（詳細はrate_limiter.py）。
ROAD_TILE_RATE_LIMIT_PER_MINUTE = 120
BASEMAP_RATE_LIMIT_PER_MINUTE = 300


def _client_id(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def get_routing_service() -> RoutingService:
    return RoutingService(ORSClient(settings.openrouteservice_api_key))


async def get_elevation_service():
    # 1ルートあたり十数地点を問い合わせるため、リクエスト単位でコネクションを使い回す
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        yield ElevationService(ElevationClient(), http_client)


async def get_weather_service():
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        yield WeatherService(WeatherClient(), http_client)


def get_wind_service(
    weather_service: WeatherService = Depends(get_weather_service),
) -> WindService:
    return WindService(weather_service)


def get_route_scorer() -> RouteScorer:
    return RouteScorer(load_scoring_weights())


def get_route_generator(
    routing_service: RoutingService = Depends(get_routing_service),
    elevation_service: ElevationService = Depends(get_elevation_service),
    wind_service: WindService = Depends(get_wind_service),
    route_scorer: RouteScorer = Depends(get_route_scorer),
) -> RouteGenerator:
    return RouteGenerator(routing_service, elevation_service, wind_service, route_scorer)


class RoutePreviewRequest(BaseModel):
    origin: Coordinates
    destination: Coordinates


@router.post("/api/routes/preview", response_model=RouteSegment)
async def preview_route(
    request: RoutePreviewRequest,
    routing_service: RoutingService = Depends(get_routing_service),
) -> RouteSegment:
    try:
        return await routing_service.get_route([request.origin, request.destination])
    except RoutingError as exc:
        raise HTTPException(status_code=502, detail=f"ルート取得に失敗しました: {exc}") from exc


class RouteGenerateRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    distance_km: float = Field(gt=0)
    distance_tolerance_km: float = Field(gt=0, default=5.0)
    route_type: Literal["loop"] = "loop"


class RouteGenerateResponse(BaseModel):
    routes: list[RouteCandidate]


@router.post("/api/routes/generate", response_model=RouteGenerateResponse)
async def generate_routes(
    request: RouteGenerateRequest,
    route_generator: RouteGenerator = Depends(get_route_generator),
) -> RouteGenerateResponse:
    origin = Coordinates(latitude=request.latitude, longitude=request.longitude)
    candidates = await route_generator.generate_loops(
        origin=origin,
        distance_km=request.distance_km,
        distance_tolerance_km=request.distance_tolerance_km,
    )
    return RouteGenerateResponse(routes=candidates)


@router.get("/api/weather", response_model=WeatherConditions)
async def get_weather(
    latitude: float,
    longitude: float,
    weather_service: WeatherService = Depends(get_weather_service),
) -> WeatherConditions:
    conditions = await weather_service.get_conditions(Coordinates(latitude=latitude, longitude=longitude))
    if conditions is None:
        raise HTTPException(status_code=502, detail="天候情報の取得に失敗しました")
    return conditions


async def get_region_service():
    async with httpx.AsyncClient(timeout=15.0) as http_client:
        yield RegionService(OverpassClient(), http_client)


@router.get("/api/region/road-surface-tiles/{z}/{x}/{y}.pbf")
async def region_road_surface_tile(
    z: int,
    x: int,
    y: int,
    request: Request,
    region_service: RegionService = Depends(get_region_service),
) -> Response:
    if not check_rate_limit(_client_id(request), ROAD_TILE_RATE_LIMIT_PER_MINUTE):
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    # MapLibre側もvector sourceのminzoom/maxzoomでこの範囲外は要求しないが、
    # 直接APIを叩かれた場合の安全弁として範囲外は拒否する。
    if z < ROAD_TILE_MIN_ZOOM or z > ROAD_TILE_MAX_ZOOM:
        raise HTTPException(status_code=400, detail="対応していないズームレベルです。")
    # x/yがそのズームレベルで存在しうる範囲（0 <= x,y < 2**z）を外れると、
    # domain/region.pyのtile_bounds_lonlatがmath.sinhでOverflowErrorを送出しうるため、
    # ここで先に弾く（例: 直接APIを叩かれてy=10**18のような極端な値が渡された場合）。
    tile_index_max = 2**z
    if not (0 <= x < tile_index_max) or not (0 <= y < tile_index_max):
        raise HTTPException(status_code=400, detail="タイル座標が範囲外です。")
    tile_bytes = await region_service.get_road_surface_tile(z, x, y)
    return Response(content=tile_bytes, media_type="application/vnd.mapbox-vector-tile")


async def get_basemap_client():
    async with httpx.AsyncClient(timeout=15.0) as http_client:
        yield BasemapClient(http_client, settings.basemap_public_base_url)


@router.get("/api/basemap/{path:path}")
async def basemap_proxy(
    path: str, request: Request, basemap_client: BasemapClient = Depends(get_basemap_client)
) -> Response:
    if not check_rate_limit(_client_id(request), BASEMAP_RATE_LIMIT_PER_MINUTE):
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    result = await basemap_client.get(path)
    if result is None:
        raise HTTPException(status_code=502, detail="地図タイルの取得に失敗しました")
    content, content_type = result
    return Response(content=content, media_type=content_type)


@router.post("/api/basemap/refresh")
def basemap_refresh() -> dict[str, str]:
    # 基礎地図タイルと路面ベクタタイル（Step10）は同じファイルキャッシュを共有しているため、
    # この一括クリアで両方とも消える。
    tile_cache.clear_all()
    return {"status": "ok"}
