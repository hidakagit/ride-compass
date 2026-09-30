"""実DB接続が必要な`RouteGenerator`の実測ベンチマークが共有する前準備。

エンジンの組み立ては本番と同じ`api/dependencies.py: get_route_generation_setup_opener`を使う。
HTTPの経路に無い起動時の読み込み（軸定義）だけをここが持つ。
"""

from __future__ import annotations

from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.infrastructure.database import get_session_factory
from app.services.axis_registry_service import refresh_axis_definitions


async def refresh_axis_registry() -> None:
    """ルート生成を組み立てる前に必ず1回呼ぶ（軸レジストリのrefresh前に組み立てると
    既定の重みが空になる）。"""
    async with get_session_factory()() as axis_session:
        await refresh_axis_definitions(AxisDefinitionRepository(axis_session))
