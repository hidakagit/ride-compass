import asyncio
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.config import settings
from app.domain.errors import RoutingError
from app.domain.evaluation import RoutePreference
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
from app.version import STARTED_AT
from app.services.elevation_attribute_service import ElevationAttributeService
from app.services.elevation_service import ElevationService
from app.services.evaluation_service import EvaluationService, load_route_preference
from app.services.graph_service import GraphService
from app.services.openrouteservice_engine import OpenRouteServiceEngine
from app.services.region_service import RegionService
from app.services.road_graph_engine import RoadGraphEngine
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

# ルート生成は最も高コストなエンドポイント（openrouteserviceエンジン: 8方位分のORS呼び出し＋
# 標高・天候の外部API、無料枠は日次2000リクエスト / road_graphエンジン: Overpass・GSIへの
# 大量問い合わせでコールド時40〜70秒）のため、per-IPのレート制限に加えてプロセス全体の
# 同時実行数も制限する。上限を超えた分は待たせず429で即座に返し、ブラウザのリトライや連打で
# 外部サービスへの負荷が積み上がることを防ぐ。
GENERATE_RATE_LIMIT_PER_MINUTE = 10
GENERATE_MAX_CONCURRENT = 2
_generate_semaphore = asyncio.Semaphore(GENERATE_MAX_CONCURRENT)


def _client_id(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/health")
def health() -> dict[str, str | None]:
    # commit（Renderが自動注入するRENDER_GIT_COMMIT）とstarted_at（プロセス起動時刻、
    # デプロイのたびに再起動されるため実質デプロイ時刻の目安）で、Render上に実際に
    # デプロイされているコミットが最新かどうかを外部から確認できるようにする
    # （ローカル開発ではcommitはnullのまま。詳細はdocs/architecture.md参照）。
    return {
        "status": "ok",
        "commit": settings.render_git_commit,
        "started_at": STARTED_AT.isoformat(),
    }


async def get_routing_service():
    # /api/routes/preview（Step3の疎通確認用エンドポイント）専用に加え、
    # settings.routing_engine=="openrouteservice"のときは/api/routes/generateからも使われる。
    # 8方位の周回生成でTLSハンドシェイクを繰り返さないよう、リクエスト単位で
    # コネクションを共有する（ors_client.pyのdocstring参照）。
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        yield RoutingService(ORSClient(settings.openrouteservice_api_key, http_client))


async def get_elevation_service():
    # openrouteserviceエンジン専用（1ルートあたり十数地点を問い合わせるため、
    # リクエスト単位でコネクションを使い回す）。Road Graphエンジンは代わりに
    # get_elevation_attribute_serviceを使う。
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        yield ElevationService(ElevationClient(), http_client)


async def get_weather_service():
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        yield WeatherService(WeatherClient(), http_client)


def get_wind_service(
    weather_service: WeatherService = Depends(get_weather_service),
) -> WindService:
    # openrouteserviceエンジン専用。Road GraphエンジンはEvaluationService/compute_wind_penaltyで
    # 風を扱う（出発時点の一様適用。エンジン間の意味の違いはopenrouteservice_engine.py参照）。
    return WindService(weather_service)


def get_route_scorer() -> RouteScorer:
    return RouteScorer(load_scoring_weights())


def get_route_preference() -> RoutePreference:
    return load_route_preference()


def get_evaluation_service(
    route_preference: RoutePreference = Depends(get_route_preference),
) -> EvaluationService:
    return EvaluationService(route_preference)


async def get_graph_service():
    # ルート生成は周回全体を覆うbboxを1回のOverpass問い合わせで取得するため、
    # 地域路面レイヤー（タイル単位、15秒）より長めのタイムアウトにする。
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        yield GraphService(OverpassClient(), http_client)


async def get_elevation_attribute_service():
    # Road GraphのEdge形状点ごとに問い合わせるため、リクエスト単位でコネクションを使い回す
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        yield ElevationAttributeService(ElevationClient(), http_client)


def get_route_generator(
    routing_service: RoutingService = Depends(get_routing_service),
    elevation_service: ElevationService = Depends(get_elevation_service),
    wind_service: WindService = Depends(get_wind_service),
    graph_service: GraphService = Depends(get_graph_service),
    elevation_attribute_service: ElevationAttributeService = Depends(get_elevation_attribute_service),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    weather_service: WeatherService = Depends(get_weather_service),
    route_scorer: RouteScorer = Depends(get_route_scorer),
    route_preference: RoutePreference = Depends(get_route_preference),
) -> RouteGenerator:
    # 周回生成戦略（8方位・距離フィルタ・スコアリング）はRouteGeneratorが単一で持ち、
    # settings.routing_engineに応じて経路計算・評価のエンジンだけを差し替える（config.py参照）。
    # 両エンジン分の依存関係をまとめてDepends宣言しているため、使わない側の依存
    # （httpx.AsyncClient等、いずれも実際のI/Oはこの時点で発生しない軽量なもの）も毎回
    # 構築されるが、FastAPIのDIで条件分岐に応じて一部のDependsだけを解決する簡単な方法が
    # 無いため、単純さを優先してこの形にしている。
    if settings.routing_engine == "road_graph":
        engine = RoadGraphEngine(
            graph_service,
            elevation_attribute_service,
            evaluation_service,
            weather_service,
            route_preference,
        )
    else:
        engine = OpenRouteServiceEngine(routing_service, elevation_service, wind_service, route_preference)
    return RouteGenerator(engine, route_scorer)


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
    if not check_rate_limit(f"generate:{_client_id(http_request)}", GENERATE_RATE_LIMIT_PER_MINUTE):
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    # 同時実行数の上限に達している場合は待たせず即座に429を返す（外部サービスへの負荷が
    # 積み上がるのを防ぐ。locked()確認とacquireの間に隙間はあるが、多少の超過は許容する簡易実装）。
    if _generate_semaphore.locked():
        raise HTTPException(status_code=429, detail="ルート生成が混み合っています。しばらく待ってから再試行してください。")
    async with _generate_semaphore:
        origin = Coordinates(latitude=request.latitude, longitude=request.longitude)
        candidates = await route_generator.generate_loops(
            origin=origin,
            distance_km=request.distance_km,
            distance_tolerance_km=request.distance_tolerance_km,
        )
    return RouteGenerateResponse(routes=candidates, engine=route_generator.engine_name)


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
    if not check_rate_limit(f"road-tile:{_client_id(request)}", ROAD_TILE_RATE_LIMIT_PER_MINUTE):
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
    if not check_rate_limit(f"basemap:{_client_id(request)}", BASEMAP_RATE_LIMIT_PER_MINUTE):
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
