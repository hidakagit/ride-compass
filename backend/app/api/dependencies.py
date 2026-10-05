"""APIのDI工場（FastAPIのDepends用ファクトリ）。

サービスの組み立て方（どのクライアント・タイムアウト・リポジトリを注入するか）はここに集約する。
公開関数は注入の口だけで、ルーターは`Depends`で受け取る（部品を束ねる判断は`services/`が持つ）。
定期ジョブも同じ部品ならここの口を呼ぶ。HTTPの経路に無い部品（起動時の軸定義・較正値の読み込み、
MSMの同期）だけは`main.py`が組み立てる。
"""

from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import AsyncIterator, Callable

from cachetools import LRUCache
from fastapi import Depends

from app.config import settings
from app.domain.region import BoundingBox
from app.domain.route_preference import RoutePreference
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.infrastructure.basemap_client import BasemapClient
from app.infrastructure.database import get_route_generation_session_factory, get_session_factory
from app.infrastructure.db_status import DbStatusQuery
from app.infrastructure.derived_data_freshness import DerivedDataFreshnessQuery
from app.infrastructure.flood_client import new_flood_cache
from app.infrastructure.gsi_tile_client import NOT_FOUND_MAX_ENTRIES, GsiTileClient
from app.infrastructure.http_client import get_http_client
from app.infrastructure.jma_amedas_client import new_latest_time_cache, new_station_table_cache
from app.infrastructure.jma_tile_client import JmaTileClient, JmaTileSharedState
from app.infrastructure.jma_warning_client import new_area_data_cache, new_warning_cache
from app.infrastructure.material_coverage import MaterialCoverageQuery
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.infrastructure.wbgt_client import new_forecast_cache, new_point_master_cache
from app.services.axis_registry_service import AxisRegistryAdminService
from app.services.db_status_service import DbStatusService
from app.services.dedicated_way_values import (
    DirectionalMaterialService,
    dedicated_way_value_factory,
    material_service_builder,
)
from app.services.derived_data_freshness_service import DerivedDataFreshnessService
from app.services.flood_service import FloodService
from app.services.graph_service import GraphService
from app.services.jma_amedas_service import JmaAmedasService
from app.services.material_coverage_service import MaterialCoverageService
from app.services.region_service import AxisInspectorService, RegionService
from app.services.route_generation_setup import (
    RouteGenerationSetup,
    assemble_route_generation_setup,
)
from app.services.warning_service import WarningService
from app.services.wbgt_service import WbgtService
from app.services.weather_service import WeatherService


#: 気象の取得のプロセス内キャッシュ。サービス・クライアントはリクエストごとに作られるため、プロセスの側で持つ。
#: 地域マスタは警報と洪水予報で共有する。
_area_data_cache = new_area_data_cache()
_warning_cache = new_warning_cache()
_flood_cache = new_flood_cache()
_station_table_cache = new_station_table_cache()
_latest_time_cache = new_latest_time_cache()
_point_master_cache = new_point_master_cache()
_forecast_cache = new_forecast_cache()
_jma_tile_shared = JmaTileSharedState()
#: 雨の材料を実体の中に持つため、プロセスに1つ。
_weather_service = WeatherService()


def get_weather_service():
    return _weather_service


# 以下のJMA/GSI系サービスはいずれも軽量なJSON・CSVしか取りに行かないため、共有の
# httpx.AsyncClient（同じタイムアウト）を使い回す。
def get_warning_service():
    return WarningService(get_http_client(10.0), area_data_cache=_area_data_cache, warning_cache=_warning_cache)


def get_amedas_service():
    return JmaAmedasService(
        get_http_client(10.0),
        get_jma_tile_client(),
        station_table_cache=_station_table_cache,
        latest_time_cache=_latest_time_cache,
    )


def get_wbgt_service():
    return WbgtService(get_http_client(10.0), point_master_cache=_point_master_cache, forecast_cache=_forecast_cache)


def get_flood_service():
    return FloodService(get_http_client(10.0), area_data_cache=_area_data_cache, flood_cache=_flood_cache)


@asynccontextmanager
async def _open_graph_service() -> AsyncIterator[GraphService]:
    async with get_route_generation_session_factory()() as session:
        yield GraphService(repository=RoadGraphRepository(session))


@asynccontextmanager
async def _open_route_generation_setup(
    *,
    preference_override: RoutePreference | None,
    penalty_strength: float | None,
    max_average_grade_percent: float | None,
    hard_filters: frozenset[str],
    assumed_speed_kmh: float,
    lens_axis_id: str | None,
) -> AsyncIterator[RouteGenerationSetup]:
    """ルート生成ジョブが使う`RouteGenerationSetup`を組み立てる非同期コンテキストマネージャ。"""
    async with _open_graph_service() as graph_service:
        yield assemble_route_generation_setup(
            graph_service,
            get_weather_service(),
            preference_override=preference_override,
            penalty_strength=penalty_strength,
            max_average_grade_percent=max_average_grade_percent,
            hard_filters=hard_filters,
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
    """フィーチャー→動的値配信層の、軸id駆動な単一の注入点。

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


async def get_axis_inspector_service(weather_service: WeatherService = Depends(get_weather_service)):
    """区間インスペクタ。専用配信の材料（値は地図のレンズと同じ経路で引く）と道の内訳を、同じセッションで順に引く
    ——別々に開くと、先に引いた材料のセッションが要求の終わりまで接続を持ったまま、内訳がもう1本を取る。"""
    async with get_session_factory()() as session:
        repository = RoadGraphRepository(session)
        yield AxisInspectorService(
            RegionService(repository=repository),
            DirectionalMaterialService(material_service_builder(repository, weather_service)),
        )


def get_basemap_client():
    return BasemapClient(get_http_client(15.0), settings.basemap_public_base_url)


def get_jma_tile_client():
    return JmaTileClient(get_http_client(15.0), _jma_tile_shared)


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
