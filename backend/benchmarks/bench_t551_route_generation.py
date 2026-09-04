"""改善計画T551（目的地ルートのvia-node方式N件化）の本番同等環境での実測スクリプト。

実DB（`DATABASE_URL`）に対して`RouteGenerator.generate_via_waypoints`（経由地無し、
destination指定）を呼び、ステージ別の所要時間（`prepare_ms`/`select_ms`/`evaluate_ms`/
`total_ms`）はRouteGenerator自体のINFOログ（route_generator.py: _generate_destination_routes
末尾）から出力される。本スクリプトは壁時計合計と候補の内訳を追加で出力する。

本番VMでは、稼働中のbackendコンテナとは別にbackendイメージの使い捨てコンテナ
（`--network=host --env-file /home/ubuntu/ridecompass-backend.env`）から実行する。
**必ず読み取り経路のみを通す**: 対象bboxの道路データが未split（`is_split_up_to_date`が
False）だと`prepare`が再構築＝本番DBへの書き込み経路に入るため、既定では実行前に
判定して未splitなら中断する（`T551_BENCH_ALLOW_UNSPLIT=1`で無効化できるが本番では使わない）。
bbox半径は`RouteGenerator._generate_destination_routes`と同じ
`distance_km * TURNAROUND_RADIUS_RATIO`（起点⇔目的地間の距離ベース、周回のD/2ベースより
小さい）。

環境変数:
- `T551_BENCH_ORIGIN`: `lat,lon`（既定はT522/T531と同じ東京駅相当 `35.6817502,139.7634149`）
- `T551_BENCH_DESTINATION`: `lat,lon`（既定は東京駅から東へ約24km、船橋駅相当
  `35.7015,139.9825`）
- `T551_BENCH_MAX_ROUTES`: 候補件数（既定8）
- `T551_BENCH_RUNS`: 既定重みでの実行回数（既定3。1回目は冷パス、2回目以降が温パス）
- `T551_BENCH_INFRA_RUN`: `1`で自転車インフラ100%の重みでも1回実行する（既定1）

使い方: `python -m benchmarks.bench_t551_route_generation`
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from app.domain.evaluation import RoutePreference
from app.domain.geo import haversine_distance_km
from app.domain.route import Coordinates
from app.services.route_generator import TURNAROUND_RADIUS_RATIO
from benchmarks._route_generation_service import assert_read_only_path, refresh_axis_registry, route_generator_session

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s")
logging.getLogger("ridecompass.generate").setLevel(logging.INFO)
logging.getLogger("ridecompass.graph").setLevel(logging.INFO)


def _point(env_name: str, default: str) -> Coordinates:
    raw = os.environ.get(env_name, default)
    lat, lon = (float(v) for v in raw.split(","))
    return Coordinates(latitude=lat, longitude=lon)


ORIGIN = _point("T551_BENCH_ORIGIN", "35.6817502,139.7634149")
DESTINATION = _point("T551_BENCH_DESTINATION", "35.7015,139.9825")
MAX_ROUTES = int(os.environ.get("T551_BENCH_MAX_ROUTES", "8"))
RUNS = int(os.environ.get("T551_BENCH_RUNS", "3"))
INFRA_RUN = os.environ.get("T551_BENCH_INFRA_RUN", "1") == "1"
ALLOW_UNSPLIT = os.environ.get("T551_BENCH_ALLOW_UNSPLIT", "0") == "1"
# frontend/src/app/page.tsx: handleGenerateのeffectiveDistanceKmと同じ算出（実距離+1kmの
# 余裕）。本スクリプトは起点→目的地の1点のみのため経由地は考慮しない。
DISTANCE_KM = haversine_distance_km(ORIGIN, DESTINATION) + 1


async def _run_once(label: str, preference_factory, max_routes: int) -> None:
    await refresh_axis_registry()
    preference = preference_factory()  # 軸レジストリのrefresh後に構築する（先に作ると重みが空になる）

    async with route_generator_session(preference) as generator:
        started = time.monotonic()
        candidates = await generator.generate_via_waypoints(
            ORIGIN, waypoints=[], distance_km=DISTANCE_KM, destination=DESTINATION, max_routes=max_routes,
        )
        elapsed_ms = round((time.monotonic() - started) * 1000)
        print(
            f"=== {label}: total_wall_ms={elapsed_ms} candidates={len(candidates)} "
            f"reason={generator.last_no_candidates_reason}"
        )
        for candidate in candidates:
            infra = (candidate.axis_difficulties or {}).get("bicycle_infra_quality")
            print(
                f"  {candidate.id} {candidate.distance_km:5.1f}km "
                f"overall={candidate.overall_difficulty} infra={infra}"
            )


def _infra_only_preference() -> RoutePreference:
    weights = {axis_id: 0.0 for axis_id in RoutePreference().weights}
    weights["bicycle_infra_quality"] = 1.0
    return RoutePreference(weights=weights)


async def main() -> None:
    print(
        f"origin={ORIGIN} destination={DESTINATION} distance_km={DISTANCE_KM:.1f} max_routes={MAX_ROUTES}"
    )
    await assert_read_only_path(
        ORIGIN, DISTANCE_KM * TURNAROUND_RADIUS_RATIO,
        allow_unsplit=ALLOW_UNSPLIT, allow_unsplit_env_hint="T551_BENCH_ALLOW_UNSPLIT",
    )
    for i in range(RUNS):
        await _run_once(f"既定重み {i + 1}回目", RoutePreference, MAX_ROUTES)
    if INFRA_RUN:
        await _run_once("自転車インフラ100%", _infra_only_preference, MAX_ROUTES)


if __name__ == "__main__":
    asyncio.run(main())
