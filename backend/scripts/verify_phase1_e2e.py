"""Phase 1 E2E検証: PBF取込済みのPostGISだけを使い、road_graphエンジンでの
ルート生成が完走することを確認する。

前提: app/batch/import_pbf.pyで対象範囲（東京駅周辺を含むbbox）を取込済みであること。

実行方法（backendディレクトリから）:
    $env:DATABASE_URL = "postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/ridecompass"
    .venv\\Scripts\\python.exe scripts\\verify_phase1_e2e.py

GraphServiceは改善計画T222でPostGIS（repository）必須構成へ一本化済みのため、本スクリプトも
PostGISのみで完結する（Overpassへ問い合わせる経路自体がコードから撤去済み）。天候
（Open-Meteo）と標高（GSI）は実APIを呼ぶ。
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.domain.route import Coordinates  # noqa: E402
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository  # noqa: E402
from app.infrastructure.database import get_engine, get_session_factory  # noqa: E402
from app.infrastructure.elevation_client import ElevationClient  # noqa: E402
from app.infrastructure.road_graph_repository import RoadGraphRepository  # noqa: E402
from app.infrastructure.weather_client import WeatherClient  # noqa: E402
from app.services.axis_registry_service import refresh_axis_definitions  # noqa: E402
from app.services.elevation_attribute_service import ElevationAttributeService  # noqa: E402
from app.services.evaluation_service import EvaluationService, load_route_preference  # noqa: E402
from app.services.graph_service import GraphService  # noqa: E402
from app.services.road_graph_engine import RoadGraphEngine  # noqa: E402
from app.services.route_generator import RouteGenerator  # noqa: E402
from app.services.route_scorer import RouteScorer, load_scoring_weights  # noqa: E402
from app.services.weather_service import WeatherService  # noqa: E402

# 東京駅。取込bbox（35.60,139.65,35.75,139.85）の中央付近で、4km周回の探索bbox
# （半径1.33km＋マージン2km）が余裕を持って取込範囲に収まる。
ORIGIN = Coordinates(latitude=35.681, longitude=139.767)
DISTANCE_KM = 4.0
DISTANCE_TOLERANCE_KM = 5.0


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    engine = get_engine()
    session_factory = get_session_factory()

    # 改善計画T350: AXIS_DEFINITIONSはDBからのpush型更新でのみ埋まる（Python literal撤去済み）。
    # 本スクリプトはapp.mainのlifespanを経由しない単体ツールのため、ここで明示的に読み込まないと
    # load_route_preference()がweights={}の空の軸重みを返し、ルート生成が軸を一切考慮しないまま
    # 完走してしまい「検証」が実質何も検証しなくなる（DB接続不可時はrefresh_axis_definitions
    # 自身がfail-fastする）。
    async with session_factory() as axis_session:
        await refresh_axis_definitions(AxisDefinitionRepository(axis_session))

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            async with session_factory() as graph_session, session_factory() as elevation_session:
                graph_service = GraphService(repository=RoadGraphRepository(graph_session))
                elevation_attribute_service = ElevationAttributeService(
                    ElevationClient(), http_client, repository=RoadGraphRepository(elevation_session)
                )
                route_preference = load_route_preference()
                road_graph_engine = RoadGraphEngine(
                    graph_service,
                    elevation_attribute_service,
                    EvaluationService(route_preference),
                    WeatherService(WeatherClient(), http_client),
                    route_preference,
                )
                generator = RouteGenerator(road_graph_engine, RouteScorer(load_scoring_weights()))
                candidates = await generator.generate_loops(
                    origin=ORIGIN, distance_km=DISTANCE_KM, distance_tolerance_km=DISTANCE_TOLERANCE_KM
                )
    finally:
        await engine.dispose()
    elapsed = time.perf_counter() - started

    print()
    print(f"候補数: {len(candidates)}  所要時間: {elapsed:.1f}s")
    for c in candidates:
        print(
            f"  {c.direction_label:>3}: distance={c.distance_km}km gain={c.elevation_gain_m}m "
            f"road={c.road_score} wind={c.wind_score} total={c.total_score} segments={len(c.segments or [])}"
        )

    ok = bool(candidates)
    if not ok:
        print("FAIL: 候補が0件（取込データでのルート生成に失敗）")
    else:
        print("PASS: PostGISのみでルート生成が完走した")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
