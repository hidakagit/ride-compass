"""改善計画T536のサニティチェック用ベンチマーク: 実DB（dev機）に対して実際に
`RouteGenerator.generate_loops`（8方位周回、既定重み）を呼び、`prepare_ms`/`trace_ms`の
実測でタイル単位の静的スコア行列＋ベクトル化コスト方式（本タスク）が旧方式
（Edge単位のPythonコールバック）より速いことを確認する。

`benchmarks/`配下の他スクリプト（合成グラフのみを使う）と異なり、本スクリプトは実DBへの
接続が必須（`DATABASE_URL`、backend/.env）。dev機のPostgreSQLが起動していない場合は
接続エラーで終了する。

使い方: `python -m benchmarks.bench_t536_route_generation`
（プロセス内タイルキャッシュ[graph_material_cache/tile_score_matrix_cache]は空の状態から
始まるため、1回目=冷パス・2回目以降=温パスとして両方を計測する。同一プロセス内で
複数回generate_loopsを呼ぶことで、タイル単位キャッシュの効果[T536の主張の一部]も
あわせて確認できる）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

from app.domain.evaluation import RoutePreference
from app.domain.route import Coordinates
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.infrastructure.database import get_route_generation_session_factory, get_session_factory
from app.infrastructure.elevation_client import ElevationClient
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.infrastructure.weather_client import WeatherClient
from app.services.axis_registry_service import refresh_axis_definitions
from app.services.elevation_attribute_service import ElevationAttributeService
from app.services.graph_service import GraphService
from app.services.road_graph_engine import RoadGraphEngine
from app.services.route_generator import RouteGenerator
from app.services.route_scorer import RouteScorer
from app.services.weather_service import WeatherService

# T522.mdと同じ起点（東京駅相当）。distance_kmはdev機で現実的な時間に収めるため
# 本番調査（30km）より小さくする——本スクリプトの目的は倍率の方向性確認であり、
# 本番同等の絶対値確認ではない（それは本番pushとサンプリングでユーザーが別途行う）。
ORIGIN = Coordinates(latitude=35.6812, longitude=139.7671)
DISTANCE_KM = 10.0
TOLERANCE_KM = 5.0

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("ridecompass.graph")
logger.setLevel(logging.INFO)


async def _run_once(label: str) -> None:
    async with get_session_factory()() as axis_session:
        await refresh_axis_definitions(AxisDefinitionRepository(axis_session))

    async with get_route_generation_session_factory()() as graph_session, \
            get_route_generation_session_factory()() as elevation_session:
        graph_service = GraphService(repository=RoadGraphRepository(graph_session))
        async with httpx.AsyncClient() as http_client:
            elevation_service = ElevationAttributeService(
                ElevationClient(), http_client, repository=RoadGraphRepository(elevation_session)
            )
            weather_service = WeatherService(WeatherClient(), http_client)
            engine = RoadGraphEngine(
                graph_service, elevation_service, weather_service, RoutePreference(),
            )
            generator = RouteGenerator(engine, RouteScorer({"distance_weight": 0.3, "difficulty_weight": 0.7}))

            started = time.monotonic()
            candidates = await generator.generate_loops(ORIGIN, DISTANCE_KM, TOLERANCE_KM)
            elapsed_ms = round((time.monotonic() - started) * 1000)
            print(f"=== {label}: total_wall_ms={elapsed_ms} candidates={len(candidates)} ===")


async def main() -> None:
    print(f"origin={ORIGIN} distance_km={DISTANCE_KM} (T536サニティチェック)")
    await _run_once("1回目(冷パス想定、プロセス内タイルキャッシュ空)")
    await _run_once("2回目(温パス、タイルキャッシュヒット)")
    await _run_once("3回目(温パス)")


if __name__ == "__main__":
    asyncio.run(main())
