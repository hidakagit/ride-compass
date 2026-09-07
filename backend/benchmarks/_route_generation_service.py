"""実DB接続が必要なRouteGenerator実測ベンチマーク（bench_t531/bench_t536等）が共有する
サービス配線（改善計画T557、項目19）。各スクリプトが同じ手順（軸定義refresh→
GraphService/ElevationAttributeService/WeatherServiceの組み立て→RoadGraphEngine/
RouteGeneratorの生成、および対象bboxが未splitのまま書き込み経路（再構築）へ入らないかの
確認）を重複させないための共通ヘルパー。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from app.domain.evaluation import RoutePreference
from app.domain.route import Coordinates
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.infrastructure.database import get_route_generation_session_factory, get_session_factory
from app.infrastructure.elevation_client import ElevationClient
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.axis_registry_service import refresh_axis_definitions
from app.services.elevation_attribute_service import ElevationAttributeService
from app.services.graph_service import GraphService
from app.services.road_graph_engine import BBOX_MARGIN_MIN_KM, BBOX_MARGIN_RATIO, RoadGraphEngine, _bbox_around_point
from app.services.route_generator import RouteGenerator
from app.services.weather_service import WeatherService


async def refresh_axis_registry() -> None:
    """`RoutePreference()`を構築する前に必ず1回呼ぶ（軸レジストリのrefresh前に構築すると
    重みが空になる）。"""
    async with get_session_factory()() as axis_session:
        await refresh_axis_definitions(AxisDefinitionRepository(axis_session))


@asynccontextmanager
async def route_generator_session(preference: RoutePreference) -> AsyncIterator[RouteGenerator]:
    """軸定義refresh後の`preference`を受け取り、GraphService/ElevationAttributeService/
    WeatherServiceの組み立てからRoadGraphEngine/RouteGeneratorの生成までを行う。
    呼び出し側は`await refresh_axis_registry()`を先に済ませておくこと。
    """
    async with get_route_generation_session_factory()() as graph_session, \
            get_route_generation_session_factory()() as elevation_session:
        graph_service = GraphService(repository=RoadGraphRepository(graph_session))
        async with httpx.AsyncClient() as http_client:
            elevation_service = ElevationAttributeService(
                ElevationClient(), http_client, repository=RoadGraphRepository(elevation_session)
            )
            weather_service = WeatherService()
            engine = RoadGraphEngine(graph_service, elevation_service, weather_service, preference)
            yield RouteGenerator(engine)


async def assert_read_only_path(
    origin: Coordinates, radius_km: float, *, allow_unsplit: bool, allow_unsplit_env_hint: str,
) -> None:
    """`prepare`が使うbbox（起点`radius_km`＋マージン）がsplit済みで、読み取り経路
    （タイルキャッシュ／`get_graph_in_bbox`）だけを通ることを確認する（改善計画T531）。
    未split（`is_split_up_to_date`がFalse、＝`prepare`の再構築が本番DBへの書き込み経路に
    入る）なら、`allow_unsplit`がTrueでない限り`SystemExit`で中断する。
    """
    margin_km = max(BBOX_MARGIN_MIN_KM, radius_km * BBOX_MARGIN_RATIO)
    bbox = _bbox_around_point(origin, radius_km + margin_km)
    async with get_route_generation_session_factory()() as session:
        up_to_date = await RoadGraphRepository(session).is_split_up_to_date(bbox)
    print(f"bbox radius_km={radius_km + margin_km:.1f} is_split_up_to_date={up_to_date}")
    if not up_to_date and not allow_unsplit:
        raise SystemExit(
            "対象bboxが未split（再構築＝書き込み経路に入る）のため中断しました。"
            f"距離を小さくするか、{allow_unsplit_env_hint}=1（本番では使わない）を指定してください。"
        )
