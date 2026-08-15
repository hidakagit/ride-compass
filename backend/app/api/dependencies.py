"""APIのDI工場（FastAPIのDepends用ファクトリ）とルータ共通ヘルパー。

エンドポイント本体はapi/routers/配下に分かれている（改善計画T5でapi/routes.pyを分割）。
サービスの組み立て方（どのクライアント・タイムアウト・リポジトリを注入するか）は
すべてここに集約し、ルータはエンドポイントの入出力とレート制限だけを持つ。
"""

from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, Request

from app.config import settings
from app.domain.evaluation import RoutePreference
from app.infrastructure.basemap_client import BasemapClient
from app.infrastructure.database import get_session_factory
from app.infrastructure.elevation_client import ElevationClient
from app.infrastructure.http_client import get_http_client
from app.infrastructure.ors_client import ORSClient
from app.infrastructure.overpass_client import OverpassClient
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.infrastructure.weather_client import WeatherClient
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


def get_wind_service(
    weather_service: WeatherService = Depends(get_weather_service),
) -> WindService:
    # openrouteserviceエンジン専用。Road GraphエンジンはEvaluationService/compute_wind_penaltyで
    # 風を扱う（出発時点の一様適用。エンジン間の意味の違いはopenrouteservice_engine.py参照）。
    return WindService(weather_service)


@dataclass
class RouteGenerationSetup:
    """1回のルート生成に使う組み立て済みの部品と、実際に適用された評価条件。

    scoring_weights / route_preference はレスポンスの条件エコー
    （routers/routes.py: GenerationConditions）にそのまま使う。
    """

    generator: RouteGenerator
    scoring_weights: dict[str, float]
    route_preference: RoutePreference


RouteGenerationBuilder = Callable[[RoutePreference | None, dict[str, float] | None], RouteGenerationSetup]


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
    ) -> RouteGenerationSetup:
        preference = preference_override or load_route_preference()
        scoring_weights = scoring_weights_override or load_scoring_weights()
        if settings.routing_engine == "road_graph":
            engine = RoadGraphEngine(
                graph_service,
                elevation_attribute_service,
                EvaluationService(preference),
                weather_service,
                preference,
            )
        else:
            engine = OpenRouteServiceEngine(
                routing_service, elevation_service, wind_service, preference,
                repository=surface_match_repository,
            )
        return RouteGenerationSetup(
            generator=RouteGenerator(engine, RouteScorer(scoring_weights)),
            scoring_weights=scoring_weights,
            route_preference=preference,
        )

    return build


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
    # 揃える（get_graph_serviceと同じ30.0秒）。
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


def get_basemap_client():
    return BasemapClient(get_http_client(15.0), settings.basemap_public_base_url)
