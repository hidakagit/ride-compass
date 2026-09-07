"""改善計画T537のサニティチェック用ベンチマーク: 実DB（dev機）に対して`RoadGraphEngine.
prepare`を直接複数回呼び、タイル集合キーのプロセス内LRU（`infrastructure/
search_graph_cache.py`）が効いた2回目以降で`_build_search_graph`のgraph_ms・
`prepare`のindex_msが大きく縮むことを実測する。

`bench_t536_route_generation.py`と同様、実DB接続が必須（`DATABASE_URL`、backend/.env）。
`generate_loops`（trace込み）ではなく`prepare`単体を計測することで、T537の対象
（LazyRoadGraph・NodeSpatialIndexの構築）だけを他のステージから切り離して確認する。

使い方: `python -m benchmarks.bench_t537_prepare_cache`
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
from app.services.axis_registry_service import refresh_axis_definitions
from app.services.elevation_attribute_service import ElevationAttributeService
from app.services.graph_service import GraphService
from app.services.road_graph_engine import RoadGraphEngine
from app.services.weather_service import WeatherService

# T536ベンチマークと同じ起点（東京駅相当）・distance_km。
ORIGIN = Coordinates(latitude=35.6812, longitude=139.7671)
DISTANCE_KM = 10.0
NOW = datetime(2024, 6, 21, 3, 0, tzinfo=timezone.utc)  # 昼間固定（night分岐を横に置く）

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("ridecompass.graph")
logger.setLevel(logging.INFO)


async def _run_once(label: str) -> None:
    async with get_route_generation_session_factory()() as graph_session, \
            get_route_generation_session_factory()() as elevation_session:
        graph_service = GraphService(repository=RoadGraphRepository(graph_session))
        async with httpx.AsyncClient() as http_client:
            elevation_service = ElevationAttributeService(
                ElevationClient(), http_client, repository=RoadGraphRepository(elevation_session)
            )
            weather_service = WeatherService()
            engine = RoadGraphEngine(
                graph_service, elevation_service, weather_service, RoutePreference(),
            )

            started = time.monotonic()
            context = await engine.prepare(ORIGIN, DISTANCE_KM, now=NOW)
            elapsed_ms = round((time.monotonic() - started) * 1000)
            ok = context is not None
            print(f"=== {label}: prepare_wall_ms={elapsed_ms} ok={ok} ===")


async def main() -> None:
    print(f"origin={ORIGIN} distance_km={DISTANCE_KM} (T537サニティチェック: search_graph_cache)")
    async with get_session_factory()() as axis_session:
        await refresh_axis_definitions(AxisDefinitionRepository(axis_session))

    await _run_once("1回目(冷パス、search_graph_cache空)")
    await _run_once("2回目(温パス、同一タイル集合でsearch_graph_cacheヒット想定)")
    await _run_once("3回目(温パス)")


if __name__ == "__main__":
    asyncio.run(main())
