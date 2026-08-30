"""app/api/dependencies.pyのDB分岐DIファクトリ（road_graph_use_repository設定で
repositoryあり/なしを切り替えるファクトリ関数群）の単体テスト（改善計画T331）。

これらは`async def ...(): async with get_session_factory()() as session: yield ...`という
形のFastAPI依存関数（async generator）。create_async_engine/AsyncSessionはいずれも遅延接続
（database.pyのコメント参照）で、ここではクエリを実行しないため、実DB接続なしで直接呼び出せる。
"""

from app.api.dependencies import (
    get_accident_service,
    get_elevation_attribute_service,
    get_graph_service,
    get_region_service,
)
from app.config import settings
from app.infrastructure.accident_repository import AccidentTileQuery
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.accident_service import AccidentService
from app.services.elevation_attribute_service import ElevationAttributeService
from app.services.graph_service import GraphService
from app.services.region_service import RegionService


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
