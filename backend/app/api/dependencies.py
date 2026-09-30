"""APIのDI工場（FastAPIのDepends用ファクトリ）。

サービスの組み立て方（どのクライアント・タイムアウト・リポジトリを注入するか）はここに集約する。
公開関数は注入の口だけで、ルーターは`Depends`で受け取る（部品を束ねる判断は`services/`が持つ）。
定期ジョブも同じ部品ならここの口を呼ぶ。HTTPの経路に無い部品（起動時の軸定義・較正値の読み込み、
MSMの同期）だけは`main.py`が組み立てる。
"""

from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from typing import AsyncIterator, Callable

from cachetools import LRUCache
from fastapi import Depends

from app.config import settings
from app.domain.region import BoundingBox
from app.domain.route_preference import RoutePreference
from app.domain.wind import ASSUMED_SPEED_KMH
from app.infrastructure.accident_repository import AccidentTileQuery
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.infrastructure.basemap_client import BasemapClient
from app.infrastructure.database import get_route_generation_session_factory, get_session_factory
from app.infrastructure.db_status import DbStatusQuery
from app.infrastructure.derived_data_freshness import DerivedDataFreshnessQuery
from app.infrastructure.gsi_tile_client import NOT_FOUND_MAX_ENTRIES, GsiTileClient
from app.infrastructure.http_client import get_http_client
from app.infrastructure.jma_tile_client import JmaTileClient
from app.infrastructure.material_coverage import MaterialCoverageQuery
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.accident_service import AccidentService
from app.services.axis_registry_service import AxisRegistryAdminService
from app.services.db_status_service import DbStatusService
from app.services.dedicated_way_values import DirectionalMaterialService, dedicated_way_value_factory
from app.services.derived_data_freshness_service import DerivedDataFreshnessService
from app.services.flood_service import FloodService
from app.services.graph_service import GraphService
from app.services.jma_amedas_service import JmaAmedasService
from app.services.material_coverage_service import MaterialCoverageService
from app.services.region_service import RegionService
from app.services.route_generation_setup import (
    RouteGenerationSetup,
    RoutePreviewService,
    assemble_route_generation_setup,
)
from app.services.warning_service import WarningService
from app.services.wbgt_service import WbgtService
from app.services.weather_service import WeatherService


# 以下のJMA/GSI系サービスはいずれも軽量なJSON・CSVしか取りに行かないため、共有の
# httpx.AsyncClient（同じタイムアウト）を使い回す。
def get_weather_service():
    return WeatherService()


def get_warning_service():
    return WarningService(get_http_client(10.0))


def get_amedas_service():
    return JmaAmedasService(get_http_client(10.0))


def get_wbgt_service():
    return WbgtService(get_http_client(10.0))


def get_flood_service():
    return FloodService(get_http_client(10.0))


async def get_graph_service():
    async with get_route_generation_session_factory()() as session:
        yield GraphService(repository=RoadGraphRepository(session))


@asynccontextmanager
async def _open_route_generation_setup(
    *,
    preference_override: RoutePreference | None = None,
    penalty_strength: float | None = None,
    max_average_grade_percent: float | None = None,
    hard_filters_override: frozenset[str] | None = None,
    assumed_speed_kmh: float = ASSUMED_SPEED_KMH,
    lens_axis_id: str | None = None,
) -> AsyncIterator[RouteGenerationSetup]:
    """ルート生成ジョブが使う`RouteGenerationSetup`を組み立てる非同期コンテキストマネージャ。

    セッション開閉を複製しないよう、DI用ジェネレータ関数をそのまま
    `asynccontextmanager()`で包んで`AsyncExitStack`へ載せる。
    """
    async with AsyncExitStack() as stack:
        weather_service = get_weather_service()
        graph_service = await stack.enter_async_context(asynccontextmanager(get_graph_service)())
        yield assemble_route_generation_setup(
            graph_service,
            weather_service,
            preference_override=preference_override,
            penalty_strength=penalty_strength,
            max_average_grade_percent=max_average_grade_percent,
            hard_filters_override=hard_filters_override,
            assumed_speed_kmh=assumed_speed_kmh,
            lens_axis_id=lens_axis_id,
        )


RouteGenerationSetupOpener = Callable[..., AbstractAsyncContextManager[RouteGenerationSetup]]


def get_route_generation_setup_opener() -> RouteGenerationSetupOpener:
    """ルート生成ジョブがエンジンを組むときの開き方。

    セッションそのものではなく開き方を注入する——ジョブは応答の送出後も走り続け、リクエストの
    DBセッションはハンドラ関数が返った時点で閉じられるため、ジョブが自分でセッションを開いて閉じる。
    """
    return _open_route_generation_setup


def get_route_preview_service(
    graph_service: GraphService = Depends(get_graph_service),
    weather_service: WeatherService = Depends(get_weather_service),
) -> RoutePreviewService:
    return RoutePreviewService(graph_service, weather_service)


async def get_road_graph_repository():
    """`RoadGraphRepository`を直接使いたい読み取り専用の管理API向け。

    利用者はいずれも全表走査寄りのため、タイル配信保護用の短いcommand_timeoutで
    キャンセルされないようルート生成用のセッション工場を使う。
    """
    async with get_route_generation_session_factory()() as session:
        yield RoadGraphRepository(session)


async def get_region_service():
    async with get_session_factory()() as session:
        yield RegionService(repository=RoadGraphRepository(session))


async def get_ingested_area() -> BoundingBox | None:
    """サービスの対象範囲（`RegionService.get_ingested_area`）。読めなければNone。"""
    async with get_session_factory()() as session:
        return await RegionService(repository=RoadGraphRepository(session)).get_ingested_area()


async def get_dedicated_way_value_service(
    axis_id: str,
    weather_service: WeatherService = Depends(get_weather_service),
):
    """way_id→動的値配信層の、軸id駆動な単一の注入点。

    `axis_id`はパスパラメータで、ルーター側と同名でなければFastAPIが解決できない。
    router側で軸ごとのサービスをそれぞれ`Depends`するとリクエストごとにDBセッションが
    重複して開くため、この関数自体が分岐して1セッションで済ませる。配信できない`axis_id`には
    Noneを返し、呼び出し元が404を返す。
    """
    factory = dedicated_way_value_factory(axis_id)
    if factory is None:
        yield None
        return

    async with get_session_factory()() as session:
        yield factory(RoadGraphRepository(session), weather_service)


async def get_directional_material_service(weather_service: WeatherService = Depends(get_weather_service)):
    """区間インスペクタが足す専用配信の材料。値は地図のレンズと同じ経路で引く。"""
    async with get_session_factory()() as session:
        yield DirectionalMaterialService(RoadGraphRepository(session), weather_service)


async def get_accident_service():
    async with get_session_factory()() as session:
        yield AccidentService(repository=AccidentTileQuery(session))


def get_basemap_client():
    return BasemapClient(get_http_client(15.0), settings.basemap_public_base_url)


def get_jma_tile_client():
    return JmaTileClient(get_http_client(15.0))


#: 整備区域外の記憶。クライアントはリクエストごとに作られるため、プロセスの側で持つ。
_gsi_not_found_paths: LRUCache = LRUCache(maxsize=NOT_FOUND_MAX_ENTRIES)


def get_gsi_tile_client():
    return GsiTileClient(get_http_client(15.0), _gsi_not_found_paths)


# 以下の管理API向けのうち、書き込み・1テーブル読みで足りるものはタイル配信と同じ
# セッション工場を使い、全表走査を伴う集計はルート生成用の長いcommand_timeoutを使う
# （短い方だと集計が最後まで走らずキャンセルされる）。
async def get_axis_registry_admin_service():
    async with get_session_factory()() as session:
        yield AxisRegistryAdminService(AxisDefinitionRepository(session))


async def get_tuning_session():
    async with get_session_factory()() as session:
        yield session


async def get_material_coverage_service():
    async with get_route_generation_session_factory()() as session:
        yield MaterialCoverageService(MaterialCoverageQuery(session))


async def get_db_status_service():
    async with get_route_generation_session_factory()() as session:
        yield DbStatusService(DbStatusQuery(session))


async def get_derived_data_freshness_service():
    async with get_route_generation_session_factory()() as session:
        yield DerivedDataFreshnessService(DerivedDataFreshnessQuery(session))
