"""APIのDI工場（FastAPIのDepends用ファクトリ）とルータ共通ヘルパー。

エンドポイント本体はapi/routers/配下に分かれている（改善計画T5でapi/routes.pyを分割）。
サービスの組み立て方（どのクライアント・タイムアウト・リポジトリを注入するか）は
すべてここに集約し、ルータはエンドポイントの入出力とレート制限だけを持つ。
"""

from dataclasses import dataclass
from typing import Awaitable, Callable

from fastapi import Depends, Request

from app.config import settings
from app.domain.errors import RoutingError
from app.domain.evaluation import DEFAULT_HARD_FILTERS, RoutePreference
from app.domain.recipe import MotorVehicleDensityRecipe, RoadSuitabilityRecipe
from app.domain.route import Coordinates, RouteSegment
from app.domain.traffic import CarStressRecipe
from app.infrastructure.accident_repository import AccidentTileQuery
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.infrastructure.basemap_client import BasemapClient
from app.infrastructure.database import get_route_generation_session_factory, get_session_factory
from app.infrastructure.elevation_client import ElevationClient
from app.infrastructure.http_client import get_http_client
from app.infrastructure.ors_client import ORSClient
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.infrastructure.weather_client import WeatherClient
from app.services.accident_service import AccidentService
from app.services.axis_registry_service import AxisRegistryAdminService
from app.services.elevation_attribute_service import ElevationAttributeService
from app.services.elevation_service import ElevationService
from app.services.evaluation_service import (
    EvaluationService,
    load_motor_vehicle_density_recipe,
    load_road_suitability_recipe,
    load_route_preference,
    load_car_stress_recipe,
)
from app.services.graph_service import GraphService
from app.services.openrouteservice_engine import OpenRouteServiceEngine
from app.services.region_service import RegionService
from app.services.road_graph_engine import RoadGraphEngine
from app.services.route_generator import RouteGenerator
from app.services.route_scorer import RouteScorer, load_scoring_weights
from app.services.routing_service import RoutingService
from app.services.flood_service import FloodService
from app.services.warning_service import WarningService
from app.services.wbgt_service import WbgtService
from app.services.weather_service import WeatherService
from app.services.wind_service import WindService


def client_id(request: Request) -> str:
    """per-IPレート制限のキーに使うクライアント識別子。

    Renderのようなリバースプロキシ配下では、uvicornの--proxy-headers＋
    --forwarded-allow-ips設定（backend/Dockerfile）が正しくないと全アクセスが
    プロキシの単一IPに潰れる点に注意（tests/test_client_ip_behind_proxy.py参照）。
    """
    return request.client.host if request.client else "unknown"


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


def get_warning_service():
    # 改善計画T205（警報・注意報バッジ）。GSI逆ジオコーダ・JMA地域マスタ・JMA警報APIは
    # いずれも軽量なJSON取得のため、他のサービスと同じ共有httpx.AsyncClientを使う。
    return WarningService(get_http_client(10.0))


def get_wbgt_service():
    # 改善計画T174（WBGT警告バッジ）。地点マスタCSV取得・予測値API取得ともに軽量なため
    # 他のサービスと同じ共有httpx.AsyncClientを使う。
    return WbgtService(get_http_client(10.0))


def get_flood_service():
    # 改善計画T212（河川氾濫予報バッジ）。地点解決はT205のjma_warning_client.pyを再利用する。
    return FloodService(get_http_client(10.0))


def get_wind_service(
    weather_service: WeatherService = Depends(get_weather_service),
) -> WindService:
    # openrouteserviceエンジン専用。Road GraphエンジンはEvaluationService/compute_wind_penaltyで
    # 風を扱う（出発時点の一様適用。エンジン間の意味の違いはopenrouteservice_engine.py参照）。
    return WindService(weather_service)


@dataclass
class RouteGenerationSetup:
    """1回のルート生成に使う組み立て済みの部品と、実際に適用された評価条件。

    scoring_weights / route_preference / car_stress_recipe はレスポンスの条件エコー
    （routers/routes.py: GenerationConditions）にそのまま使う。
    """

    generator: RouteGenerator
    scoring_weights: dict[str, float]
    route_preference: RoutePreference
    car_stress_recipe: CarStressRecipe
    road_suitability_recipe: RoadSuitabilityRecipe
    motor_vehicle_density_recipe: MotorVehicleDensityRecipe
    # 改善計画T218・T12 ADR原則1: コスト式の割増率の強さ（P）。road_graphエンジンのみに効く。
    penalty_strength: float
    # 改善計画T218a・T12 ADR原則5: 0次ハードフィルタの勾配しきい値（%、Noneは無効）。
    # road_graphエンジンのみに効く。
    max_average_grade_percent: float | None
    # 改善計画T266: 0次ハードフィルタ名（no_bicycle/motorway/trunk）の個別ON/OFF上書き。
    # road_graphエンジンのみに効く。常に解決済み（Noneではなく実際に適用された集合）。
    hard_filters: frozenset[str]


RouteGenerationBuilder = Callable[
    [
        RoutePreference | None,
        dict[str, float] | None,
        CarStressRecipe | None,
        RoadSuitabilityRecipe | None,
        MotorVehicleDensityRecipe | None,
        float,
        float | None,
        frozenset[str] | None,
    ],
    RouteGenerationSetup,
]


async def get_graph_service():
    # PostGISのみを参照し、取込範囲外はOverpassへ問い合わせずデータ未整備として扱う
    # （改善計画T22でOverpassフォールバックを撤去済み。改善計画T222でDBなし構成
    # 自体も撤去したため、road_graph_use_repository設定に関わらず常にrepository付きで
    # 構築する。config.py参照）。
    # get_session_factory()（タイル配信と共有、command_timeout=20）ではなく
    # get_route_generation_session_factory()（改善計画T242、command_timeout=180）を使う。
    # 未splitエリアの初回タッチ時に発生しうる重い再構築（graph_service.pyのdocstring参照）が
    # タイル配信保護用の短いタイムアウトでキャンセルされる実測不具合への対応
    # （database.py: get_route_generation_engineのコメント参照）。
    async with get_route_generation_session_factory()() as session:
        yield GraphService(repository=RoadGraphRepository(session))


async def get_elevation_attribute_service():
    # Road GraphのEdge形状点ごとに問い合わせるため、リクエスト単位でコネクションを使い回す。
    # road_graph_use_repository有効時はEdge単位の標高キャッシュ（PostGIS）を注入する
    # （GraphService側とは別セッション。各操作が独立にcommitするため同居させる必要は無い）。
    # get_graph_serviceと同じ理由でget_route_generation_session_factory()を使う
    # （改善計画T242）。
    http_client = get_http_client(10.0)
    if settings.road_graph_use_repository:
        async with get_route_generation_session_factory()() as session:
            yield ElevationAttributeService(ElevationClient(), http_client, repository=RoadGraphRepository(session))
    else:
        yield ElevationAttributeService(ElevationClient(), http_client)


async def get_surface_match_repository():
    # OpenRouteServiceEngineの路面評価（サンプル点→自前DBのEdge空間マッチ、改善計画T21）用。
    # 他の各所（get_elevation_attribute_service等）と同じ「road_graph_use_repository無効時は
    # Noneを注入し、該当評価をスキップさせる」パターン。専用セッションを使う理由も同様
    # （GraphService/ElevationAttributeServiceと同居させる必要が無い読み取り専用アクセスのため）。
    if settings.road_graph_use_repository:
        async with get_session_factory()() as session:
            yield RoadGraphRepository(session)
    else:
        yield None


def get_route_generation_builder(
    routing_service: RoutingService = Depends(get_routing_service),
    elevation_service: ElevationService = Depends(get_elevation_service),
    wind_service: WindService = Depends(get_wind_service),
    graph_service: GraphService = Depends(get_graph_service),
    elevation_attribute_service: ElevationAttributeService = Depends(get_elevation_attribute_service),
    weather_service: WeatherService = Depends(get_weather_service),
    surface_match_repository: RoadGraphRepository | None = Depends(get_surface_match_repository),
) -> RouteGenerationBuilder:
    # 周回生成戦略（8方位・距離フィルタ・スコアリング）はRouteGeneratorが単一で持ち、
    # settings.routing_engineに応じて経路計算・評価のエンジンだけを差し替える（config.py参照）。
    # 両エンジン分の依存関係をまとめてDepends宣言しているため、使わない側の依存
    # （httpx.AsyncClient等、いずれも実際のI/Oはこの時点で発生しない軽量なもの）も毎回
    # 構築されるが、FastAPIのDIで条件分岐に応じて一部のDependsだけを解決する簡単な方法が
    # 無いため、単純さを優先してこの形にしている。
    #
    # RouteGenerator本体ではなくビルダー（呼び出し可能）を返すのは、評価の重みを
    # リクエストボディで上書きできるため（研究インターフェース改善 §10-1）。DI解決の時点では
    # ボディが未検証のため、エンドポイントが検証済みの上書き値（無ければNone）を渡して
    # 組み立てを完了する。上書きが無い場合はYAML既定値を読む（従来挙動と同一。
    # YAMLはリクエスト毎に再読込されるため、編集はサーバー再起動なしで反映される）。
    def build(
        preference_override: RoutePreference | None = None,
        scoring_weights_override: dict[str, float] | None = None,
        car_stress_recipe_override: CarStressRecipe | None = None,
        road_suitability_recipe_override: RoadSuitabilityRecipe | None = None,
        motor_vehicle_density_recipe_override: MotorVehicleDensityRecipe | None = None,
        penalty_strength: float = 1.0,
        max_average_grade_percent: float | None = None,
        hard_filters_override: frozenset[str] | None = None,
    ) -> RouteGenerationSetup:
        preference = preference_override or load_route_preference()
        scoring_weights = scoring_weights_override or load_scoring_weights()
        car_stress_recipe = car_stress_recipe_override or load_car_stress_recipe()
        road_suitability_recipe = road_suitability_recipe_override or load_road_suitability_recipe()
        motor_vehicle_density_recipe = motor_vehicle_density_recipe_override or load_motor_vehicle_density_recipe()
        hard_filters = hard_filters_override if hard_filters_override is not None else DEFAULT_HARD_FILTERS
        if settings.routing_engine == "road_graph":
            engine = RoadGraphEngine(
                graph_service,
                elevation_attribute_service,
                EvaluationService(
                    preference, car_stress_recipe, road_suitability_recipe, motor_vehicle_density_recipe
                ),
                weather_service,
                preference,
                car_stress_recipe,
                road_suitability_recipe,
                motor_vehicle_density_recipe,
                penalty_strength,
                max_average_grade_percent,
                hard_filters,
            )
        else:
            engine = OpenRouteServiceEngine(
                routing_service, elevation_service, wind_service, preference,
                repository=surface_match_repository,
                car_stress_recipe=car_stress_recipe,
                road_suitability_recipe=road_suitability_recipe,
                motor_vehicle_density_recipe=motor_vehicle_density_recipe,
            )
        return RouteGenerationSetup(
            generator=RouteGenerator(engine, RouteScorer(scoring_weights)),
            scoring_weights=scoring_weights,
            route_preference=preference,
            car_stress_recipe=car_stress_recipe,
            road_suitability_recipe=road_suitability_recipe,
            motor_vehicle_density_recipe=motor_vehicle_density_recipe,
            penalty_strength=penalty_strength,
            max_average_grade_percent=max_average_grade_percent,
            hard_filters=hard_filters,
        )

    return build


PreviewBuilder = Callable[[Coordinates, Coordinates], Awaitable[RouteSegment]]


def get_preview_builder(
    routing_service: RoutingService = Depends(get_routing_service),
    graph_service: GraphService = Depends(get_graph_service),
    elevation_attribute_service: ElevationAttributeService = Depends(get_elevation_attribute_service),
    weather_service: WeatherService = Depends(get_weather_service),
) -> PreviewBuilder:
    """`/api/routes/preview`（単一区間確認）向けのビルダー（改善計画T237）。

    `get_route_generation_builder`と対になる構成で、`settings.routing_engine`に応じて
    ORS（`RoutingService.get_route`）またはroad_graph（`RoadGraphEngine.preview_segment`）へ
    委譲する。previewはリクエストボディでの評価重み上書きに対応しない（generateと違い
    研究インターフェース向けの調整UIが無い）ため、既定値のみを使う。
    """

    async def preview(origin: Coordinates, destination: Coordinates) -> RouteSegment:
        if settings.routing_engine == "road_graph":
            preference = load_route_preference()
            engine = RoadGraphEngine(
                graph_service,
                elevation_attribute_service,
                EvaluationService(preference),
                weather_service,
                preference,
            )
            segment = await engine.preview_segment(origin, destination)
            if segment is None:
                raise RoutingError("road_graph: no path found between origin and destination")
            return segment
        return await routing_service.get_route([origin, destination])

    return preview


async def get_region_service():
    # PostGISのみを参照する（PBF取込済みの範囲外・DB障害時は空タイルを返す。
    # Overpassフォールバックは改善計画T22で撤去済み。docs/osm-pbf-import.md Phase 2、
    # docs/decisions/pre-static-attributes-gate.md 決定2改定）。road_graph_use_repository
    # 無効時（DBなし構成）はrepository自体を注入しないため、路面レイヤーは常に空タイルになる。
    if settings.road_graph_use_repository:
        async with get_session_factory()() as session:
            yield RegionService(repository=RoadGraphRepository(session))
    else:
        yield RegionService()


async def get_accident_service():
    # PostGISのみを参照する（get_region_serviceと同じ「road_graph_use_repository無効時は
    # repository自体を注入しない」パターン）。事故データはroad_graph_tilesのカバレッジとは
    # 無関係な独立データのため、DBなし構成では常に空タイルになる。
    if settings.road_graph_use_repository:
        async with get_session_factory()() as session:
            yield AccidentService(repository=AccidentTileQuery(session))
    else:
        yield AccidentService()


def get_basemap_client():
    return BasemapClient(get_http_client(15.0), settings.basemap_public_base_url)


async def get_axis_registry_admin_service():
    # 軸定義CRUD管理API（改善計画T221 Stage D）専用。タイル配信と同じ
    # get_session_factory()（command_timeout=20）で十分（書き込みは軽量なUPSERT/DELETE）。
    async with get_session_factory()() as session:
        yield AxisRegistryAdminService(AxisDefinitionRepository(session))
