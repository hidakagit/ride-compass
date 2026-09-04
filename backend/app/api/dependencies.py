"""APIのDI工場（FastAPIのDepends用ファクトリ）とルータ共通ヘルパー。

エンドポイント本体はapi/routers/配下に分かれている（改善計画T5でapi/routes.pyを分割）。
サービスの組み立て方（どのクライアント・タイムアウト・リポジトリを注入するか）は
すべてここに集約し、ルータはエンドポイントの入出力とレート制限だけを持つ。
"""

import logging
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable

from fastapi import Depends, HTTPException, Request

from app.config import settings
from app.domain.dynamic_way_values import dynamic_way_value_materials
from app.domain.errors import RoutingError
from app.domain.evaluation import DEFAULT_HARD_FILTERS, RoutePreference
from app.domain.route import Coordinates, RouteSegment
from app.infrastructure.accident_repository import AccidentTileQuery
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.infrastructure.basemap_client import BasemapClient
from app.infrastructure.gsi_relief_tile_client import GsiReliefTileClient
from app.infrastructure.database import get_route_generation_session_factory, get_session_factory
from app.infrastructure.debug_log import record_rate_limit_rejection
from app.infrastructure.elevation_client import ElevationClient
from app.infrastructure.http_client import get_http_client
from app.infrastructure.jma_tile_client import JmaTileClient
from app.infrastructure.material_coverage import MaterialCoverageQuery
from app.infrastructure.rate_limiter import check_rate_limit
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.infrastructure.weather_client import WeatherClient
from app.services.accident_service import AccidentService
from app.services.axis_registry_service import AxisRegistryAdminService
from app.services.elevation_attribute_service import ElevationAttributeService
from app.services.evaluation_service import load_route_preference
from app.services.graph_service import GraphService
from app.services.region_service import RegionService
from app.services.road_graph_engine import RoadGraphEngine
from app.services.route_generator import RouteGenerator
from app.services.flood_service import FloodService
from app.services.gradient_way_service import GradientWayService
from app.services.jma_amedas_service import JmaAmedasService
from app.services.material_coverage_service import MaterialCoverageService
from app.services.warning_service import WarningService
from app.services.wbgt_service import WbgtService
from app.services.weather_service import WeatherService
from app.services.wind_way_service import WindWayService

logger = logging.getLogger("ridecompass.dependencies")


def client_id(request: Request) -> str:
    """per-IPレート制限のキーに使うクライアント識別子。

    Renderのようなリバースプロキシ配下では、uvicornの--proxy-headers＋
    --forwarded-allow-ips設定（backend/Dockerfile）が正しくないと全アクセスが
    プロキシの単一IPに潰れる点に注意（tests/test_client_ip_behind_proxy.py参照）。

    改善計画T467: request.clientがNone（ASGI呼び出し元がclient情報を渡さない場合、
    または想定外のプロキシ構成）のときは全リクエストが固定文字列"unknown"の1つの
    レート制限バケットへ相乗りし、無関係な複数クライアントの通信量が合算されてしまう
    （本来より早く429になる、または逆に個々のクライアントに対する制限が実質緩くなる）。
    根本原因（プロキシ構成等）の調査に使えるようWARNINGで記録する
    （docs/logging.md: エラー・429拒否は常時WARNING以上で出す方針に準拠）。
    """
    if request.client is None:
        logger.warning("request.client is None; rate-limit key falls back to shared 'unknown' bucket")
        return "unknown"
    return request.client.host


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


@dataclass
class RouteGenerationSetup:
    """1回のルート生成に使う組み立て済みの部品と、実際に適用された評価条件。

    route_preference はレスポンスの条件エコー
    （routers/routes.py: GenerationConditions）にそのまま使う。
    """

    generator: RouteGenerator
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


def _assemble_route_generation_setup(
    graph_service: GraphService,
    elevation_attribute_service: ElevationAttributeService,
    weather_service: WeatherService,
    preference_override: RoutePreference | None = None,
    penalty_strength: float = 1.0,
    max_average_grade_percent: float | None = None,
    hard_filters_override: frozenset[str] | None = None,
) -> RouteGenerationSetup:
    """組み立て済みのサービスと評価条件から`RouteGenerationSetup`を作る（改善計画T265）。

    唯一の呼び出し元`open_route_generation_setup`から「どのサービスをエンジンへ
    どう組み立てるか」を切り離すための純粋関数（テストからも直接呼べる、
    tests/test_routes_generate.py参照）。
    """
    preference = preference_override or load_route_preference()
    hard_filters = hard_filters_override if hard_filters_override is not None else DEFAULT_HARD_FILTERS
    engine = RoadGraphEngine(
        graph_service,
        elevation_attribute_service,
        weather_service,
        preference,
        penalty_strength,
        max_average_grade_percent,
        hard_filters,
    )
    return RouteGenerationSetup(
        generator=RouteGenerator(engine),
        route_preference=preference,
        penalty_strength=penalty_strength,
        max_average_grade_percent=max_average_grade_percent,
        hard_filters=hard_filters,
    )


@asynccontextmanager
async def open_route_generation_setup(
    preference_override: RoutePreference | None = None,
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

    DB接続を要する2つの依存（`get_graph_service`/`get_elevation_attribute_service`）は、
    既存のDI用ジェネレータ関数をそのまま`asynccontextmanager()`でラップして
    `AsyncExitStack`で開く（セッション開閉ロジックを複製しない）。
    """
    async with AsyncExitStack() as stack:
        weather_service = get_weather_service()
        graph_service = await stack.enter_async_context(asynccontextmanager(get_graph_service)())
        elevation_attribute_service = await stack.enter_async_context(
            asynccontextmanager(get_elevation_attribute_service)()
        )
        yield _assemble_route_generation_setup(
            graph_service, elevation_attribute_service, weather_service,
            preference_override, penalty_strength,
            max_average_grade_percent, hard_filters_override,
        )


PreviewBuilder = Callable[[Coordinates, Coordinates], Awaitable[RouteSegment]]


def get_preview_builder(
    graph_service: GraphService = Depends(get_graph_service),
    elevation_attribute_service: ElevationAttributeService = Depends(get_elevation_attribute_service),
    weather_service: WeatherService = Depends(get_weather_service),
) -> PreviewBuilder:
    """`/api/routes/preview`（単一区間確認）向けのビルダー（改善計画T237）。

    `RoadGraphEngine.preview_segment`へ委譲する。previewはリクエストボディでの評価重み
    上書きに対応しない（generateと違い研究インターフェース向けの調整UIが無い）ため、
    既定値のみを使う。
    """

    async def preview(origin: Coordinates, destination: Coordinates) -> RouteSegment:
        preference = load_route_preference()
        engine = RoadGraphEngine(
            graph_service,
            elevation_attribute_service,
            weather_service,
            preference,
        )
        segment = await engine.preview_segment(origin, destination)
        if segment is None:
            raise RoutingError("road_graph: no path found between origin and destination")
        return segment

    return preview


async def get_region_service():
    # PostGISのみを参照する（PBF取込済みの範囲外・DB障害時は空タイルを返す。
    # Overpassフォールバックは改善計画T22で撤去済み。docs/osm-pbf-import.md Phase 2、
    # docs/decisions/pre-static-attributes-gate.md 決定2改定）。road_graph_use_repository
    # 無効時（DBなし構成）はrepository自体を注入しないため、路面レイヤーは常に空タイルになる。
    #
    # `get_graph_service`（GraphService）はこの設定に関わらずDB接続を必須とする
    # （改善計画T222、main.py起動時WARNING参照）ため、本番でDB接続済みの環境でこの設定だけ
    # Falseのままにすると「ルート生成はDBを使うのに地図タイルは常に空」という一貫性の
    # 無い構成になる（運用上は非推奨だが、コード上はエラーにならず空タイルを返し続ける
    # だけで安全側）。
    if settings.road_graph_use_repository:
        async with get_session_factory()() as session:
            yield RegionService(repository=RoadGraphRepository(session))
    else:
        yield RegionService()


# 改善計画T460: material_id→サービスファクトリの登録テーブル。以前はget_dynamic_way_value_
# service内の_buildがif material_id == "wind"というハードコード分岐でサービスを組み立てて
# おり、domain/dynamic_way_values.pyのモジュールdocstringが謳う「新しい動的＋向きあり材料は
# ここへ1エントリ足すだけで反映される」という1本道の主張に反していた（設計原則8違反）。
# WindWayService/GradientWayServiceはコンストラクタ依存が異なる（前者だけweather_service を
# 追加で要求）ため、ファクトリはrepository・weather_serviceの両方を受け取り、必要な方だけ
# 使う統一シグネチャにする。3つ目の動的材料を追加する際は、このdictへ1エントリ足すだけでよい
# （T458: dynamic_way_value_materials()自体の拡張[軸スタジオでの宣言のみで完結]とは
# 別軸・別タイミングで進められる。こちらはPython実装本体の登録のため常にコード変更を伴う）。
# 注意: このdictのキー集合はdynamic_way_value_materials()（domain/dynamic_way_values.py、
# 改善計画T458でAXIS_DEFINITIONS由来の動的導出へ変更）のキー集合の部分集合である必要が
# ある（後者に無いmaterial_idは下の`if material_id not in dynamic_way_value_materials()`で
# 先に弾かれる）。新しい材料を追加する際は、軸スタジオでの登録（dedicated_way_value_layer・
# needs_time/needs_bearing）に加えてこのdictへも1エントリ登録すること——片方だけ更新すると
# `_build`がKeyErrorで即座に失敗する（fail-fast、無音の分岐漏れより検知しやすい設計。
# こちらはPythonの実装本体[コンストラクタ]の登録なので宣言だけでは代替できない）。
_DYNAMIC_WAY_VALUE_SERVICE_FACTORIES: dict[
    str, Callable[[RoadGraphRepository | None, WeatherService], WindWayService | GradientWayService]
] = {
    "wind": lambda repository, weather_service: WindWayService(repository=repository, weather_service=weather_service),
    "gradient": lambda repository, weather_service: GradientWayService(repository=repository),
}


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
    if material_id not in dynamic_way_value_materials():
        yield None
        return

    def _build(repository: RoadGraphRepository | None):
        return _DYNAMIC_WAY_VALUE_SERVICE_FACTORIES[material_id](repository, weather_service)

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


def get_gsi_relief_tile_client():
    return GsiReliefTileClient(get_http_client(15.0))


async def get_axis_registry_admin_service():
    # 軸定義CRUD管理API（改善計画T221 Stage D）専用。タイル配信と同じ
    # get_session_factory()（command_timeout=20）で十分（書き込みは軽量なUPSERT/DELETE）。
    async with get_session_factory()() as session:
        yield AxisRegistryAdminService(AxisDefinitionRepository(session))


async def get_material_coverage_service():
    # 材料の欠損割合集計（管理API専用）。osm_raw_ways/road_edgesの全表走査を伴うため、
    # タイル配信用の短いcommand_timeout（20秒）ではなくルート生成用の長い
    # command_timeout（180秒）を持つセッションを使う。
    async with get_route_generation_session_factory()() as session:
        yield MaterialCoverageService(MaterialCoverageQuery(session))
