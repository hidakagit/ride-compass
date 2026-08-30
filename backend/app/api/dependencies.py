"""APIのDI工場（FastAPIのDepends用ファクトリ）とルータ共通ヘルパー。

エンドポイント本体はapi/routers/配下に分かれている（改善計画T5でapi/routes.pyを分割）。
サービスの組み立て方（どのクライアント・タイムアウト・リポジトリを注入するか）は
すべてここに集約し、ルータはエンドポイントの入出力とレート制限だけを持つ。
"""

from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable

from fastapi import Depends, HTTPException, Request

from app.config import settings
from app.domain.dynamic_way_values import DYNAMIC_WAY_VALUE_MATERIALS
from app.domain.errors import RoutingError
from app.domain.evaluation import DEFAULT_HARD_FILTERS, RoutePreference
from app.domain.route import Coordinates, RouteSegment
from app.infrastructure.accident_repository import AccidentTileQuery
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.infrastructure.basemap_client import BasemapClient
from app.infrastructure.database import get_route_generation_session_factory, get_session_factory
from app.infrastructure.debug_log import record_rate_limit_rejection
from app.infrastructure.elevation_client import ElevationClient
from app.infrastructure.http_client import get_http_client
from app.infrastructure.jma_tile_client import JmaTileClient
from app.infrastructure.ors_client import ORSClient
from app.infrastructure.rate_limiter import check_rate_limit
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.infrastructure.weather_client import WeatherClient
from app.services.accident_service import AccidentService
from app.services.axis_registry_service import AxisRegistryAdminService
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
from app.services.flood_service import FloodService
from app.services.gradient_way_service import GradientWayService
from app.services.jma_amedas_service import JmaAmedasService
from app.services.warning_service import WarningService
from app.services.wbgt_service import WbgtService
from app.services.weather_service import WeatherService
from app.services.wind_service import WindService
from app.services.wind_way_service import WindWayService


def client_id(request: Request) -> str:
    """per-IPレート制限のキーに使うクライアント識別子。

    Renderのようなリバースプロキシ配下では、uvicornの--proxy-headers＋
    --forwarded-allow-ips設定（backend/Dockerfile）が正しくないと全アクセスが
    プロキシの単一IPに潰れる点に注意（tests/test_client_ip_behind_proxy.py参照）。
    """
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(request: Request, prefix: str, limit_per_minute: int) -> None:
    """per-IPレート制限を確認し、超過していれば記録した上で429を送出する（改善計画T425）。

    check_rate_limit→超過時のrecord_rate_limit_rejection→HTTPException(429)という
    3行のブロックが各routerへ個別に複製されていた（weather.py 7箇所・basemap.py 2箇所・
    jma_tile.py 1箇所・routes.py 2箇所、いずれも文言・組み立て方が完全に同一）ため、
    ここへ集約する。`prefix`はレート制限のキー・rejection集計カテゴリの両方を兼ねる
    （`f"{prefix}:{client_id(request)}"`)。地域タイル系エンドポイント専用だった
    旧`_tile_validation.check_tile_rate_limit`と同じ実装で、対象を全routerへ広げたもの。
    """
    if not check_rate_limit(f"{prefix}:{client_id(request)}", limit_per_minute):
        record_rate_limit_rejection(prefix, client_id(request), f"{limit_per_minute}/min")
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")


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


def get_amedas_service():
    # 改善計画T387（JMAアメダス観測値）。観測所マスタ・生観測値の取得は軽量なJSONのため
    # 他のJMA系サービスと同じ共有httpx.AsyncClientを使う。
    return JmaAmedasService(get_http_client(10.0))


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

    scoring_weights / route_preference はレスポンスの条件エコー
    （routers/routes.py: GenerationConditions）にそのまま使う。
    """

    generator: RouteGenerator
    scoring_weights: dict[str, float]
    route_preference: RoutePreference
    # 改善計画T218・T12 ADR原則1: コスト式の割増率の強さ（P）。road_graphエンジンのみに効く。
    penalty_strength: float
    # 改善計画T218a・T12 ADR原則5: 0次ハードフィルタの勾配しきい値（%、Noneは無効）。
    # road_graphエンジンのみに効く。
    max_average_grade_percent: float | None
    # 改善計画T266: 0次ハードフィルタ名（no_bicycle/motorway/trunk）の個別ON/OFF上書き。
    # road_graphエンジンのみに効く。常に解決済み（Noneではなく実際に適用された集合）。
    hard_filters: frozenset[str]


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
    #
    # get_graph_service（GraphService、routing_engine=road_graphのルート生成が使う）と違い
    # 本関数はrepository必須へは一本化していない。本関数の利用元OpenRouteServiceEngineは
    # routing_engine=openrouteserviceでのみ使われ、その構成はGraphService（DB接続必須、
    # 改善計画T222）を経由しないため、`else: yield None`（DBなし構成）は
    # routing_engine=openrouteservice + road_graph_use_repository=False（既定）という
    # 現在も有効な本番構成の組み合わせで到達する（road_graph_use_repository=falseのDBなし
    # 構成は、openrouteserviceエンジン専用の運用ではまだ現役。routing_engine=road_graphを
    # 選ぶ場合はDB接続が必須になる（main.py起動時WARNING参照）ため、その構成でこの設定を
    # Falseのままにするのは非推奨の組み合わせになる）。
    if settings.road_graph_use_repository:
        async with get_session_factory()() as session:
            yield RoadGraphRepository(session)
    else:
        yield None


def _assemble_route_generation_setup(
    routing_service: RoutingService,
    elevation_service: ElevationService,
    wind_service: WindService,
    graph_service: GraphService | None,
    elevation_attribute_service: ElevationAttributeService | None,
    weather_service: WeatherService,
    surface_match_repository: RoadGraphRepository | None,
    preference_override: RoutePreference | None = None,
    scoring_weights_override: dict[str, float] | None = None,
    penalty_strength: float = 1.0,
    max_average_grade_percent: float | None = None,
    hard_filters_override: frozenset[str] | None = None,
) -> RouteGenerationSetup:
    """組み立て済みの7サービスと評価条件から`RouteGenerationSetup`を作る（改善計画T265）。

    唯一の呼び出し元`open_route_generation_setup`から「どのサービスをどのエンジンへ
    どう組み立てるか」を切り離すための純粋関数（テストからも直接呼べる、
    tests/test_routes_generate.py参照）。`graph_service`/`elevation_attribute_service`は
    `settings.routing_engine=="road_graph"`のときのみ使う（そうでなければNoneのまま
    未使用）。呼び出し側（`open_route_generation_setup`）はこの利用パターンに合わせて
    使わない側のDBセッションを開かない（改善計画T386、T265コードレビュー指摘4件目）。
    """
    preference = preference_override or load_route_preference()
    scoring_weights = scoring_weights_override or load_scoring_weights()
    hard_filters = hard_filters_override if hard_filters_override is not None else DEFAULT_HARD_FILTERS
    if settings.routing_engine == "road_graph":
        engine = RoadGraphEngine(
            graph_service,
            elevation_attribute_service,
            EvaluationService(preference),
            weather_service,
            preference,
            penalty_strength,
            max_average_grade_percent,
            hard_filters,
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
        penalty_strength=penalty_strength,
        max_average_grade_percent=max_average_grade_percent,
        hard_filters=hard_filters,
    )


@asynccontextmanager
async def open_route_generation_setup(
    preference_override: RoutePreference | None = None,
    scoring_weights_override: dict[str, float] | None = None,
    penalty_strength: float = 1.0,
    max_average_grade_percent: float | None = None,
    hard_filters_override: frozenset[str] | None = None,
) -> AsyncIterator[RouteGenerationSetup]:
    """ルート生成ジョブが使う`RouteGenerationSetup`を組み立てる非同期コンテキストマネージャ
    （改善計画T265）。

    FastAPIのリクエストスコープ外（`BackgroundTasks`経由、レスポンス送出後に実行される）
    で使うため、`Depends`は使えない——リクエストのDBセッションはハンドラ関数が返った
    時点で閉じられ、その後もバックグラウンドタスクが同じセッションを使い続けようとすると
    失敗する（`graph_service.py: _warm_tile_cache_background`が同じ理由で新規セッションを
    開いているのと同じ制約）。

    DB接続を要する3つの依存（`get_graph_service`/`get_elevation_attribute_service`/
    `get_surface_match_repository`）は、既存のDI用ジェネレータ関数をそのまま
    `asynccontextmanager()`でラップして`AsyncExitStack`で開く（セッション開閉ロジックを
    複製しない）。残り4つ（httpx共有クライアント系）はセッション非依存のため直接呼ぶ。

    改善計画T386（T265コードレビュー指摘4件目、CONFIRMED）: `_assemble_route_generation_setup`は
    `settings.routing_engine`に応じてroad_graph/openrouteservice片方のサービスしか使わないため、
    使わない側のDBセッションは開かない。`get_surface_match_repository`が路面/事故タイル配信と
    共有する逼迫気味のプール（`config.py`参照）から接続を取得する点は特に、road_graphエンジン
    構成でジョブの全期間（冷パスで最大316秒[T248実測]）未使用の接続を無駄に保持し続けるのを
    避ける効果が大きい。
    """
    async with AsyncExitStack() as stack:
        routing_service = get_routing_service()
        elevation_service = get_elevation_service()
        weather_service = get_weather_service()
        wind_service = get_wind_service(weather_service)
        if settings.routing_engine == "road_graph":
            graph_service = await stack.enter_async_context(asynccontextmanager(get_graph_service)())
            elevation_attribute_service = await stack.enter_async_context(
                asynccontextmanager(get_elevation_attribute_service)()
            )
            surface_match_repository = None
        else:
            graph_service = None
            elevation_attribute_service = None
            surface_match_repository = await stack.enter_async_context(
                asynccontextmanager(get_surface_match_repository)()
            )
        yield _assemble_route_generation_setup(
            routing_service, elevation_service, wind_service, graph_service,
            elevation_attribute_service, weather_service, surface_match_repository,
            preference_override, scoring_weights_override, penalty_strength,
            max_average_grade_percent, hard_filters_override,
        )


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
    #
    # 本関数（地図タイル配信）は`routing_engine`設定と無関係に常に呼ばれるため、
    # get_graph_service（GraphService、routing_engine=road_graphのときのみDB接続必須へ
    # 一本化済み、改善計画T222）とは独立に`road_graph_use_repository`の値をそのまま見てよい。
    # `else: yield RegionService()`（DBなし構成）は、routing_engine（ルート生成）の設定に
    # 関わらず、単に「road_graph_use_repositoryを有効にしていない環境」（DBを持たない
    # 軽量構成、または各種テスト）で到達する。ただしrouting_engine=road_graphを選ぶ場合は
    # GraphServiceがこの設定に関わらずDB接続を必須とする（main.py起動時WARNING参照）ため、
    # 本番でrouting_engine=road_graphかつDB接続済みの環境でこの設定だけFalseのままにすると
    # 「ルート生成はDBを使うのに地図タイルは常に空」という一貫性の無い構成になる
    # （運用上は非推奨だが、コード上はエラーにならず空タイルを返し続けるだけで安全側）。
    if settings.road_graph_use_repository:
        async with get_session_factory()() as session:
            yield RegionService(repository=RoadGraphRepository(session))
    else:
        yield RegionService()


async def get_dynamic_way_value_service(
    material_id: str,
    weather_service: WeatherService = Depends(get_weather_service),
):
    """改善計画T423（T411の実施）: way_id→動的値配信層（風・勾配、「評価軸」グループ）の
    材料id駆動な単一の注入点。`material_id`（パスパラメータ）を見て、DBセッションを1つだけ
    開いた上でその材料に対応するサービスを組み立てる——router側でwind/gradient両方の
    サービスをDependsするとリクエストごとにDBセッションが2重に開いてしまうため、
    この関数自体が分岐して1セッションで済ませる。`material_id`が未知の場合はNoneを返し、
    呼び出し元（region.py）が404を返す。

    get_region_serviceと同じ「road_graph_use_repository無効時はrepository自体を注入しない」
    パターン（DBなし構成では常に空dictを返す。到達可能性の説明もget_region_service参照）。
    """
    if material_id not in DYNAMIC_WAY_VALUE_MATERIALS:
        yield None
        return

    def _build(repository: RoadGraphRepository | None):
        if material_id == "wind":
            return WindWayService(repository=repository, weather_service=weather_service)
        return GradientWayService(repository=repository)

    if settings.road_graph_use_repository:
        async with get_session_factory()() as session:
            yield _build(RoadGraphRepository(session))
    else:
        yield _build(None)


async def get_accident_service():
    # PostGISのみを参照する（get_region_serviceと同じ「road_graph_use_repository無効時は
    # repository自体を注入しない」パターン、到達可能性の説明もget_region_service参照）。
    # 事故データはroad_graph_tilesのカバレッジとは無関係な独立データのため、DBなし構成では
    # 常に空タイルになる。
    if settings.road_graph_use_repository:
        async with get_session_factory()() as session:
            yield AccidentService(repository=AccidentTileQuery(session))
    else:
        yield AccidentService()


def get_basemap_client():
    return BasemapClient(get_http_client(15.0), settings.basemap_public_base_url)


def get_jma_tile_client():
    return JmaTileClient(get_http_client(15.0))


async def get_axis_registry_admin_service():
    # 軸定義CRUD管理API（改善計画T221 Stage D）専用。タイル配信と同じ
    # get_session_factory()（command_timeout=20）で十分（書き込みは軽量なUPSERT/DELETE）。
    async with get_session_factory()() as session:
        yield AxisRegistryAdminService(AxisDefinitionRepository(session))
