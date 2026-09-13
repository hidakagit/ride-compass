"""改善計画T799: 物理を写した軸の既定重みを0にすると、返る候補がどう変わるかを見る。

風・勾配・停止密度・舗装は走行モデル（所要時間）へ入っているため、軸の重みが0でない限り
同じ現象に二重で払う。既定重みをDBで変える前に、**同じ本番データで候補がどう変わるか**を
並べて出す（値を変える前に影響を測る）。

`--network=host --env-file /home/ubuntu/ridecompass-backend.env`、風の実データを読むため
`-v /home/ubuntu/ridecompass-cache-data:/app/data`も要る。DBは読むだけで書き換えない。

使い方: `python -m benchmarks.bench_t799_default_weights`
"""

from __future__ import annotations

import asyncio
import logging
import os

from app.domain.axis_definitions import AXIS_DEFINITIONS
from app.domain.route import Coordinates
from app.domain.route_preference import RoutePreference
from benchmarks._route_generation_service import refresh_axis_registry, route_generator_session

logging.basicConfig(level=logging.WARNING, format="%(message)s")

# 走行モデルへ入っている現象を写した軸（＝重みが0でないと二重に効く）。
PHYSICS_AXIS_IDS = ("wind", "gradient", "surface_q", "axis_abdaded0be20")

ORIGIN = Coordinates(latitude=35.8617, longitude=139.9707)
DESTINATION = Coordinates(latitude=35.7528, longitude=139.7386)
LOOP_DISTANCE_KM = float(os.environ.get("T799_LOOP_KM", "30"))


def _describe(candidates) -> str:
    return " / ".join(
        f"{c.distance_km:.1f}km"
        f" {'—' if c.estimated_duration_seconds is None else f'{c.estimated_duration_seconds / 60:.0f}分'}"
        f" 難{'—' if c.overall_difficulty is None else f'{c.overall_difficulty:.0f}'}"
        for c in candidates
    )


async def _run(label: str, weights: dict[str, float], penalty_strength: float = 1.0) -> None:
    preference = RoutePreference(weights=weights)
    async with route_generator_session(preference, penalty_strength=penalty_strength) as generator:
        loops = await generator.generate_loops(ORIGIN, LOOP_DISTANCE_KM, 5.0, max_routes=3)
        print(f"[{label}] 周回: {_describe(loops)}")
        destination = await generator.generate_via_waypoints(
            ORIGIN, [], 30.0, destination=DESTINATION, max_routes=3
        )
        print(f"[{label}] 目的地: {_describe(destination)}")


async def main() -> None:
    await refresh_axis_registry()
    current = dict(RoutePreference().weights)
    print("現行の既定重み: " + ", ".join(f"{k}={v}" for k, v in sorted(current.items()) if v))

    zeroed = dict(current)
    for axis_id in PHYSICS_AXIS_IDS:
        if axis_id in zeroed:
            zeroed[axis_id] = 0.0
    remaining = {k: v for k, v in zeroed.items() if v}
    total = sum(remaining.values())
    print(
        "物理の軸を0にした後（合成は重みの合計で正規化するため、比だけが効く）: "
        + ", ".join(f"{k}={v / total:.2f}" for k, v in sorted(remaining.items()))
    )
    print(f"公開軸: {[a for a, d in AXIS_DEFINITIONS.items() if d.is_published]}")

    await _run("現行 P=1.0", current)
    for strength in (float(x) for x in os.environ.get("T799_STRENGTHS", "1.0,0.7,0.5").split(",")):
        await _run(f"物理の軸=0 P={strength}", zeroed, penalty_strength=strength)


if __name__ == "__main__":
    asyncio.run(main())
