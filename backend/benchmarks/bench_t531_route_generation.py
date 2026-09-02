"""改善計画T531（フロンティア方式の周回生成）の本番同等環境での実測スクリプト。

実DB（`DATABASE_URL`）に対して`RouteGenerator.generate_loops`を呼び、ステージ別の
所要時間（`prepare_ms`/`select_ms`/`trace_ms`/`evaluate_ms`/`total_ms`）と候補の内訳
（折返し候補数・距離フィルタ棄却数・各候補の方位/距離/overall_difficulty）を出力する。

本番VMでは、稼働中のbackendコンテナとは別にbackendイメージの使い捨てコンテナ
（`--network=host --env-file /home/ubuntu/ridecompass-backend.env`）から実行する。
**必ず読み取り経路のみを通す**: 対象bboxの道路データが未split（`is_split_up_to_date`が
False）だと`prepare`が再構築＝本番DBへの書き込み経路に入るため、既定では実行前に
判定して未splitなら中断する（`T531_BENCH_ALLOW_UNSPLIT=1`で無効化できるが本番では使わない）。

環境変数:
- `T531_BENCH_ORIGIN`: `lat,lon`（既定はT522と同じ東京駅相当 `35.6817502,139.7634149`）
- `T531_BENCH_DISTANCE_KM`: 目標距離（既定30）
- `T531_BENCH_TOLERANCE_KM`: 距離許容（既定5）
- `T531_BENCH_MAX_ROUTES`: 候補件数（既定8）
- `T531_BENCH_RUNS`: 既定重みでの実行回数（既定3。1回目は冷パス、2回目以降が温パス）
- `T531_BENCH_INFRA_RUN`: `1`で自転車インフラ100%の重みでも1回実行する（既定1）

使い方: `python -m benchmarks.bench_t531_route_generation`
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

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
from app.services.road_graph_engine import BBOX_MARGIN_MIN_KM, BBOX_MARGIN_RATIO, RoadGraphEngine, _bbox_around_point
from app.services.route_generator import TURNAROUND_RADIUS_RATIO, RouteGenerator
from app.services.weather_service import WeatherService

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s")
logging.getLogger("ridecompass.generate").setLevel(logging.INFO)
logging.getLogger("ridecompass.graph").setLevel(logging.INFO)


def _origin() -> Coordinates:
    raw = os.environ.get("T531_BENCH_ORIGIN", "35.6817502,139.7634149")
    lat, lon = (float(v) for v in raw.split(","))
    return Coordinates(latitude=lat, longitude=lon)


DISTANCE_KM = float(os.environ.get("T531_BENCH_DISTANCE_KM", "30"))
TOLERANCE_KM = float(os.environ.get("T531_BENCH_TOLERANCE_KM", "5"))
MAX_ROUTES = int(os.environ.get("T531_BENCH_MAX_ROUTES", "8"))
RUNS = int(os.environ.get("T531_BENCH_RUNS", "3"))
INFRA_RUN = os.environ.get("T531_BENCH_INFRA_RUN", "1") == "1"
ALLOW_UNSPLIT = os.environ.get("T531_BENCH_ALLOW_UNSPLIT", "0") == "1"


async def _assert_read_only_path(origin: Coordinates) -> None:
    """`prepare`が使うbbox（`_bbox_around_point(origin, radius + margin)`）がsplit済みで、
    読み取り経路（タイルキャッシュ／`get_graph_in_bbox`）だけを通ることを確認する。"""
    radius_km = DISTANCE_KM * TURNAROUND_RADIUS_RATIO
    margin_km = max(BBOX_MARGIN_MIN_KM, radius_km * BBOX_MARGIN_RATIO)
    bbox = _bbox_around_point(origin, radius_km + margin_km)
    async with get_route_generation_session_factory()() as session:
        up_to_date = await RoadGraphRepository(session).is_split_up_to_date(bbox)
    print(f"bbox radius_km={radius_km + margin_km:.1f} is_split_up_to_date={up_to_date}")
    if not up_to_date and not ALLOW_UNSPLIT:
        raise SystemExit(
            "対象bboxが未split（再構築＝本番DBへの書き込み経路に入る）のため中断しました。"
            "距離を小さくするか、T531_BENCH_ALLOW_UNSPLIT=1（本番では使わない）を指定してください。"
        )


async def _run_once(label: str, preference_factory, max_routes: int) -> None:
    async with get_session_factory()() as axis_session:
        await refresh_axis_definitions(AxisDefinitionRepository(axis_session))
    preference = preference_factory()  # 軸レジストリのrefresh後に構築する（先に作ると重みが空になる）

    async with get_route_generation_session_factory()() as graph_session, \
            get_route_generation_session_factory()() as elevation_session:
        graph_service = GraphService(repository=RoadGraphRepository(graph_session))
        async with httpx.AsyncClient() as http_client:
            elevation_service = ElevationAttributeService(
                ElevationClient(), http_client, repository=RoadGraphRepository(elevation_session)
            )
            weather_service = WeatherService(WeatherClient(), http_client)
            generator = RouteGenerator(RoadGraphEngine(graph_service, elevation_service, weather_service, preference))

            started = time.monotonic()
            candidates = await generator.generate_loops(_origin(), DISTANCE_KM, TOLERANCE_KM, max_routes=max_routes)
            elapsed_ms = round((time.monotonic() - started) * 1000)
            print(
                f"=== {label}: total_wall_ms={elapsed_ms} candidates={len(candidates)} "
                f"reason={generator.last_no_candidates_reason}"
            )
            for candidate in candidates:
                infra = (candidate.axis_difficulties or {}).get("bicycle_infra_quality")
                print(
                    f"  {candidate.id} {candidate.direction_label:>3} {candidate.distance_km:5.1f}km "
                    f"overall={candidate.overall_difficulty} infra={infra}"
                )


def _infra_only_preference() -> RoutePreference:
    weights = {axis_id: 0.0 for axis_id in RoutePreference().weights}
    weights["bicycle_infra_quality"] = 1.0
    return RoutePreference(weights=weights)


async def main() -> None:
    origin = _origin()
    print(f"origin={origin} distance_km={DISTANCE_KM} tolerance_km={TOLERANCE_KM} max_routes={MAX_ROUTES}")
    await _assert_read_only_path(origin)
    for i in range(RUNS):
        await _run_once(f"既定重み {i + 1}回目", RoutePreference, MAX_ROUTES)
    if INFRA_RUN:
        await _run_once("自転車インフラ100%", _infra_only_preference, MAX_ROUTES)


if __name__ == "__main__":
    asyncio.run(main())
