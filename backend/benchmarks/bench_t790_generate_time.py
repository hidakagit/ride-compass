"""改善計画T790: ルート生成の所要時間を改修前後で同条件に比べる。

`generate_via_waypoints`（目的地ルート）を同じ起点・目的地で繰り返し呼び、冷パス（1回目）と
温パス（2回目以降）の壁時計を出すだけのベンチ。**改修前のイメージでもそのまま動くよう、
ターンの費用など改修後にしか無い引数は使わない**。

使い方: `python -m benchmarks.bench_t790_generate_time`
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from app.domain.route import Coordinates
from app.domain.route_preference import RoutePreference
from benchmarks._route_generation_service import refresh_axis_registry, route_generator_session
from benchmarks._revision import announce_revision


def _coordinate_from_env(name: str, default: Coordinates) -> Coordinates:
    raw = os.environ.get(name)
    if not raw:
        return default
    latitude, longitude = (float(part) for part in raw.split(","))
    return Coordinates(latitude=latitude, longitude=longitude)


ORIGIN = _coordinate_from_env("T790_ORIGIN", Coordinates(latitude=35.8617, longitude=139.9707))
DESTINATION = _coordinate_from_env("T790_DESTINATION", Coordinates(latitude=35.7528, longitude=139.7386))
DISTANCE_KM = float(os.environ.get("T790_DISTANCE_KM", "30"))
MAX_ROUTES = int(os.environ.get("T790_MAX_ROUTES", "3"))
RUNS = int(os.environ.get("T790_RUNS", "3"))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("ridecompass.graph").setLevel(logging.INFO)


async def main() -> None:
    print(f"origin={ORIGIN} destination={DESTINATION} runs={RUNS}")
    await refresh_axis_registry()
    async with route_generator_session(RoutePreference()) as generator:
        for run in range(1, RUNS + 1):
            started = time.monotonic()
            candidates = await generator.generate_via_waypoints(
                ORIGIN, [], DISTANCE_KM, destination=DESTINATION, max_routes=MAX_ROUTES
            )
            elapsed_ms = round((time.monotonic() - started) * 1000)
            label = "冷" if run == 1 else "温"
            distances = "/".join(f"{c.distance_km:.1f}" for c in candidates)
            print(f"[{label}{run}回目] total_wall_ms={elapsed_ms} 候補={len(candidates)}件 距離={distances}km")


if __name__ == "__main__":
    announce_revision()
    asyncio.run(main())
