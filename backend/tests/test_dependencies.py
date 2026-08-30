"""app/api/dependencies.pyのDB分岐DIファクトリ（road_graph_use_repository設定で
repositoryあり/なしを切り替えるファクトリ関数群）の単体テスト（改善計画T331）。

これらは`async def ...(): async with get_session_factory()() as session: yield ...`という
形のFastAPI依存関数（async generator）。create_async_engine/AsyncSessionはいずれも遅延接続
（database.pyのコメント参照）で、ここではクエリを実行しないため、実DB接続なしで直接呼び出せる。
"""

from app.api.dependencies import (
    get_accident_service,
    get_dynamic_way_value_service,
    get_elevation_attribute_service,
    get_graph_service,
    get_region_service,
    get_weather_service,
)
from app.config import settings
from app.infrastructure.accident_repository import AccidentTileQuery
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.accident_service import AccidentService
from app.services.elevation_attribute_service import ElevationAttributeService
from app.services.gradient_way_service import GradientWayService
from app.services.graph_service import GraphService
from app.services.region_service import RegionService
from app.services.wind_way_service import WindWayService


class TestGetGraphService:
    # 改善計画T222でDBなし構成を撤去済みのため、road_graph_use_repositoryの値に関わらず
    # 常にrepository付きで構築される（dependencies.pyのコメント参照）。

    async def test_yields_repository_backed_service_when_repository_enabled(self, monkeypatch):
        monkeypatch.setattr(settings, "road_graph_use_repository", True)

        agen = get_graph_service()
        try:
            service = await agen.__anext__()
            assert isinstance(service, GraphService)
            assert isinstance(service._repository, RoadGraphRepository)
        finally:
            await agen.aclose()

    async def test_yields_repository_backed_service_even_when_repository_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "road_graph_use_repository", False)

        agen = get_graph_service()
        try:
            service = await agen.__anext__()
            assert isinstance(service, GraphService)
            assert isinstance(service._repository, RoadGraphRepository)
        finally:
            await agen.aclose()


class TestGetElevationAttributeService:
    async def test_injects_repository_when_enabled(self, monkeypatch):
        monkeypatch.setattr(settings, "road_graph_use_repository", True)

        agen = get_elevation_attribute_service()
        try:
            service = await agen.__anext__()
            assert isinstance(service, ElevationAttributeService)
            assert isinstance(service._repository, RoadGraphRepository)
        finally:
            await agen.aclose()

    async def test_omits_repository_when_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "road_graph_use_repository", False)

        agen = get_elevation_attribute_service()
        try:
            service = await agen.__anext__()
            assert isinstance(service, ElevationAttributeService)
            assert service._repository is None
        finally:
            await agen.aclose()


class TestGetRegionService:
    async def test_injects_repository_when_enabled(self, monkeypatch):
        monkeypatch.setattr(settings, "road_graph_use_repository", True)

        agen = get_region_service()
        try:
            service = await agen.__anext__()
            assert isinstance(service, RegionService)
            assert isinstance(service._repository, RoadGraphRepository)
        finally:
            await agen.aclose()

    async def test_omits_repository_when_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "road_graph_use_repository", False)

        agen = get_region_service()
        try:
            service = await agen.__anext__()
            assert isinstance(service, RegionService)
            assert service._repository is None
        finally:
            await agen.aclose()


class TestGetAccidentService:
    async def test_injects_repository_when_enabled(self, monkeypatch):
        monkeypatch.setattr(settings, "road_graph_use_repository", True)

        agen = get_accident_service()
        try:
            service = await agen.__anext__()
            assert isinstance(service, AccidentService)
            assert isinstance(service._repository, AccidentTileQuery)
        finally:
            await agen.aclose()

    async def test_omits_repository_when_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "road_graph_use_repository", False)

        agen = get_accident_service()
        try:
            service = await agen.__anext__()
            assert isinstance(service, AccidentService)
            assert service._repository is None
        finally:
            await agen.aclose()


class TestGetDynamicWayValueService:
    """改善計画T460: material_id→サービスファクトリの登録テーブル
    （_DYNAMIC_WAY_VALUE_SERVICE_FACTORIES）が、以前のif material_id == "wind"ハードコード
    分岐と同じ結果を返すことの回帰テスト。road_graph_use_repository無効化でDB接続を避け、
    このファイルの他テストと同じ「実DB接続なしで直接呼び出す」方針を踏襲する。"""

    async def test_wind_material_id_yields_wind_way_service_with_weather_service(self, monkeypatch):
        monkeypatch.setattr(settings, "road_graph_use_repository", False)
        weather_service = get_weather_service()

        agen = get_dynamic_way_value_service("wind", weather_service=weather_service)
        try:
            service = await agen.__anext__()
            assert isinstance(service, WindWayService)
            assert service._weather_service is weather_service
        finally:
            await agen.aclose()

    async def test_gradient_material_id_yields_gradient_way_service(self, monkeypatch):
        monkeypatch.setattr(settings, "road_graph_use_repository", False)

        agen = get_dynamic_way_value_service("gradient", weather_service=get_weather_service())
        try:
            service = await agen.__anext__()
            assert isinstance(service, GradientWayService)
        finally:
            await agen.aclose()

    async def test_unknown_material_id_yields_none(self, monkeypatch):
        monkeypatch.setattr(settings, "road_graph_use_repository", False)

        agen = get_dynamic_way_value_service("rain", weather_service=get_weather_service())
        try:
            service = await agen.__anext__()
            assert service is None
        finally:
            await agen.aclose()
