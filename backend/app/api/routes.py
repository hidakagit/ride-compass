import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.config import settings
from app.domain.errors import RoutingError
from app.domain.evaluation import RoutePreference
from app.domain.region import ROAD_TILE_MAX_ZOOM, ROAD_TILE_MIN_ZOOM
from app.domain.route import Coordinates, RouteCandidate, RouteSegment
from app.domain.weather import WeatherConditions
from app.infrastructure import tile_cache
from app.infrastructure.basemap_client import BasemapClient
from app.infrastructure.database import get_session_factory
from app.infrastructure.debug_log import get_stats, record_rate_limit_rejection
from app.infrastructure.elevation_client import ElevationClient
from app.infrastructure.http_client import get_http_client
from app.infrastructure.road_graph_repository import RoadGraphRepository
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
# 密集した都市部のタイルはPostGISから1万件超のwayが返ることがあり、Supabaseが遠隔
# リージョンにあるとその転送・パース・MVTエンコードだけで1タイルあたり数秒かかる
# （実測: 東京駅付近z13タイルで約7.6秒）。地図の短時間パン/ズームでブラウザが並列に
# 大量のタイルを要求すると、この重い処理が同時に積み上がりCPUを奪い合い、Renderの
# ヘルスチェックすら応答できず「Instance failed」でプロセスごと再起動される事故が実機で
# 発生した。ルート生成（GENERATE_MAX_CONCURRENT）と同じ考え方で同時実行数を制限し、
# 上限超過分は待たせず429にすることでプロセス全体が巻き込まれないようにする。
ROAD_TILE_MAX_CONCURRENT = 3
_road_tile_semaphore = asyncio.Semaphore(ROAD_TILE_MAX_CONCURRENT)
BASEMAP_RATE_LIMIT_PER_MINUTE = 300
# refreshはbasemap/road-tile両方のディスクキャッシュを一括削除する破壊的操作のため、
# 通常のbasemapプロキシより厳しい上限にする（連打されるとキャッシュが常に温まらず、
# Overpass/OpenFreeMapへの実問い合わせが毎回発生し続けてしまう）。
BASEMAP_REFRESH_RATE_LIMIT_PER_MINUTE = 6
# /preview・/weatherは/generateほど高コストではないが、いずれも外部APIの無料枠を
# 消費する（openrouteservice: 日次2000リクエストをgenerateと共有 / Open-Meteo）ため、
# 他の認証なしエンドポイントと同様に歯止めを設ける。
PREVIEW_RATE_LIMIT_PER_MINUTE = 20
WEATHER_RATE_LIMIT_PER_MINUTE = 60

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


@router.get("/api/debug/stats")
def debug_stats() -> dict:
    # 外部API呼び出し・キャッシュの集計(カテゴリ別の呼び出し数/エラー数/ヒット率/所要時間)と
    # 429拒否数のプロセス内スナップショット(infrastructure/debug_log.py)。ログを目視で数えずに
    # キャッシュヒット率等を確認するための運用エンドポイント。集計値のみで秘匿情報や個別の
    # 座標を含まないため、debug_modeに関わらず/healthと同様に常時公開する。
    # プロセス再起動でリセットされる点に注意(started_atで起点を判別できる)。
    return {
        "commit": settings.render_git_commit,
        "started_at": STARTED_AT.isoformat(),
        "engine": settings.routing_engine,
        "debug_mode": settings.debug_mode,
        **get_stats(),
    }


def get_routing_service():
    # /api/routes/preview（Step3の疎通確認用エンドポイント）専用に加え、
    # settings.routing_engine=="openrouteservice"のときは/api/routes/generateからも使われる。
    # httpx.AsyncClientはプロセス全体で使い回す（infrastructure/http_client.py参照）。
    return RoutingService(ORSClient(settings.openrouteservice_api_key, get_http_client(10.0)))


def get_elevation_service():
    # openrouteserviceエンジン専用（1ルートあたり十数地点を問い合わせる）。
    # Road Graphエンジンは代わりにget_elevation_attribute_serviceを使う。
    return ElevationService(ElevationClient(), get_http_client(10.0))


def get_weather_service():
    return WeatherService(WeatherClient(), get_http_client(10.0))


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
    # road_graph_use_repository有効時はPostGISをread-throughキャッシュとして注入し、
    # PBF取込済み（タイルマーク済み）の範囲ではOverpassへ問い合わせない（config.py参照）。
    http_client = get_http_client(30.0)
    if settings.road_graph_use_repository:
        async with get_session_factory()() as session:
            yield GraphService(
                OverpassClient(),
                http_client,
                repository=RoadGraphRepository(session),
                overpass_fallback_enabled=settings.overpass_fallback_enabled,
            )
    else:
        yield GraphService(OverpassClient(), http_client)


async def get_elevation_attribute_service():
    # Road GraphのEdge形状点ごとに問い合わせるため、リクエスト単位でコネクションを使い回す。
    # road_graph_use_repository有効時はEdge単位の標高キャッシュ（PostGIS）を注入する
    # （GraphService側とは別セッション。各操作が独立にcommitするため同居させる必要は無い）。
    http_client = get_http_client(10.0)
    if settings.road_graph_use_repository:
        async with get_session_factory()() as session:
            yield ElevationAttributeService(ElevationClient(), http_client, repository=RoadGraphRepository(session))
    else:
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
    http_request: Request,
    routing_service: RoutingService = Depends(get_routing_service),
) -> RouteSegment:
    if not check_rate_limit(f"preview:{_client_id(http_request)}", PREVIEW_RATE_LIMIT_PER_MINUTE):
        record_rate_limit_rejection("preview", _client_id(http_request), f"{PREVIEW_RATE_LIMIT_PER_MINUTE}/min")
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
    if not check_rate_limit(f"generate:{_client_id(http_request)}", GENERATE_RATE_LIMIT_PER_MINUTE):
        record_rate_limit_rejection("generate", _client_id(http_request), f"{GENERATE_RATE_LIMIT_PER_MINUTE}/min")
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    # 同時実行数の上限に達している場合は待たせず即座に429を返す（外部サービスへの負荷が
    # 積み上がるのを防ぐ。locked()確認とacquireの間に隙間はあるが、多少の超過は許容する簡易実装）。
    if _generate_semaphore.locked():
        record_rate_limit_rejection("generate-concurrency", _client_id(http_request), f"concurrent={GENERATE_MAX_CONCURRENT}")
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
    http_request: Request,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    weather_service: WeatherService = Depends(get_weather_service),
) -> WeatherConditions:
    # 以前はここでの範囲チェックをCoordinates（Pydanticモデル）任せにしており、
    # 範囲外の値（例: latitude=999）はFastAPIの422ではなくpydantic.ValidationErrorが
    # 関数内から送出され未処理の500になっていた。Queryのge/leでFastAPI層で弾く。
    if not check_rate_limit(f"weather:{_client_id(http_request)}", WEATHER_RATE_LIMIT_PER_MINUTE):
        record_rate_limit_rejection("weather", _client_id(http_request), f"{WEATHER_RATE_LIMIT_PER_MINUTE}/min")
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    conditions = await weather_service.get_conditions(Coordinates(latitude=latitude, longitude=longitude))
    if conditions is None:
        raise HTTPException(status_code=502, detail="天候情報の取得に失敗しました")
    return conditions


async def get_region_service():
    # road_graph_use_repository有効時はPostGISを第一系統として注入する（PBF取込済みの
    # 範囲ではOverpassへ問い合わせない。フォールバックの可否はoverpass_fallback_enabled。
    # docs/osm-pbf-import.md Phase 2）。
    #
    # OverpassClientのクエリは[timeout:25]（サーバー側が内部で使ってよい上限秒数）を
    # 指定しているのに、以前はhttpxクライアント側のタイムアウトが15.0秒とそれより短く
    # 設定されていた。密集した市街地のbboxは実測で10〜15秒以上かかることがあり、
    # サーバー側がまだ処理を続けている（＝最終的には成功する）リクエストをクライアント側が
    # 先に打ち切ってしまい、本来成功するはずの問い合わせがタイムアウトエラー扱いになる
    # 不具合が実機（Renderデプロイ）で確認された。クエリの内部タイムアウトに余裕を持って
    # 揃える（graph_service.pyのget_graph_serviceと同じ30.0秒）。
    http_client = get_http_client(30.0)
    if settings.road_graph_use_repository:
        async with get_session_factory()() as session:
            yield RegionService(
                OverpassClient(),
                http_client,
                repository=RoadGraphRepository(session),
                overpass_fallback_enabled=settings.overpass_fallback_enabled,
            )
    else:
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
        record_rate_limit_rejection("road-tile", _client_id(request), f"{ROAD_TILE_RATE_LIMIT_PER_MINUTE}/min")
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
    # 同時実行数の上限に達している場合は待たせず即座に429を返す（ROAD_TILE_MAX_CONCURRENTの
    # コメント参照。locked()確認とacquireの間に隙間はあるが、多少の超過は許容する簡易実装で
    # generate_routesと同じ）。キャッシュヒットは軽量（実測数ms）なのですぐ解放されるため、
    # 実質的に重い（PostGIS問い合わせを伴う）リクエストだけが詰まりの原因になる。
    if _road_tile_semaphore.locked():
        record_rate_limit_rejection("road-tile-concurrency", _client_id(request), f"concurrent={ROAD_TILE_MAX_CONCURRENT}")
        raise HTTPException(status_code=429, detail="路面タイルの取得が混み合っています。しばらく待ってから再試行してください。")
    async with _road_tile_semaphore:
        tile_bytes = await region_service.get_road_surface_tile(z, x, y)
    return Response(content=tile_bytes, media_type="application/vnd.mapbox-vector-tile")


def get_basemap_client():
    return BasemapClient(get_http_client(15.0), settings.basemap_public_base_url)


@router.get("/api/basemap/{path:path}")
async def basemap_proxy(
    path: str, request: Request, basemap_client: BasemapClient = Depends(get_basemap_client)
) -> Response:
    if not check_rate_limit(f"basemap:{_client_id(request)}", BASEMAP_RATE_LIMIT_PER_MINUTE):
        record_rate_limit_rejection("basemap", _client_id(request), f"{BASEMAP_RATE_LIMIT_PER_MINUTE}/min")
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    result = await basemap_client.get(path)
    if result is None:
        raise HTTPException(status_code=502, detail="地図タイルの取得に失敗しました")
    content, content_type = result
    return Response(content=content, media_type=content_type)


@router.post("/api/basemap/refresh")
def basemap_refresh(request: Request) -> dict[str, str]:
    # 基礎地図タイルと路面ベクタタイル（Step10）は同じファイルキャッシュを共有しているため、
    # この一括クリアで両方とも消える。認証が無いため、連打でキャッシュが常に温まらず
    # 外部サービス（Overpass/OpenFreeMap）への実問い合わせが発生し続けることを防ぐため
    # 他のエンドポイントよりも厳しいレート制限をかける。
    if not check_rate_limit(f"basemap-refresh:{_client_id(request)}", BASEMAP_REFRESH_RATE_LIMIT_PER_MINUTE):
        record_rate_limit_rejection(
            "basemap-refresh", _client_id(request), f"{BASEMAP_REFRESH_RATE_LIMIT_PER_MINUTE}/min"
        )
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    tile_cache.clear_all()
    return {"status": "ok"}
