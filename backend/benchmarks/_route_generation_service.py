"""実DB接続が必要な`RouteGenerator`の実測ベンチマークが共有するサービス配線。

各スクリプトが同じ手順（軸定義のrefresh→GraphService/WeatherServiceの組み立て→
RoadGraphEngine/RouteGeneratorの生成）を重複させないための共通ヘルパー。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.domain.evaluation import resolve_penalty_strength
from app.domain.route_preference import RoutePreference
from app.domain.routing import TurnCostSpec
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.infrastructure.database import get_route_generation_session_factory, get_session_factory
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.axis_registry_service import refresh_axis_definitions
from app.services.graph_service import GraphService
from app.services.road_graph_engine import RoadGraphEngine
from app.services.route_generator import RouteGenerator
from app.services.weather_service import WeatherService


async def refresh_axis_registry() -> None:
    """`RoutePreference()`を構築する前に必ず1回呼ぶ（軸レジストリのrefresh前に構築すると
    重みが空になる）。"""
    async with get_session_factory()() as axis_session:
        await refresh_axis_definitions(AxisDefinitionRepository(axis_session))


@asynccontextmanager
async def route_generator_session(
    preference: RoutePreference,
    *,
    turn_cost: TurnCostSpec | None = None,
) -> AsyncIterator[RouteGenerator]:
    """軸定義refresh後の`preference`を受け取り、`RouteGenerator`まで組み立てる。
    呼び出し側は`await refresh_axis_registry()`を先に済ませておくこと。
    換算レート（P）はルート生成が省略時に使うのと同じ`resolve_penalty_strength`から読む
    （このモジュールは`tuning_overrides`を読み込まないため、値は較正値の宣言の既定）。
    """
    async with get_route_generation_session_factory()() as graph_session:
        graph_service = GraphService(repository=RoadGraphRepository(graph_session))
        engine = RoadGraphEngine(
            graph_service, WeatherService(), preference,
            penalty_strength=resolve_penalty_strength(None), turn_cost=turn_cost,
        )
        yield RouteGenerator(engine)
