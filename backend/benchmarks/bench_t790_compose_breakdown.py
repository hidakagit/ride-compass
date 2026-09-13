"""改善計画T790段階D: レグ合成（`_LegCostComposer._compose_at`）の内訳を測る。

時刻ビンを張ると合成がビンの本数ぶん走るため、生成時間の支配項になった。どの部品が
支配的かを部品単位で出す（推測で最適化しないため）。

本番VMでは稼働中のbackendコンテナとは別に、backendイメージの使い捨てコンテナから実行する
（`--network=host --env-file /home/ubuntu/ridecompass-backend.env`、MSMの実データを読むため
`-v /home/ubuntu/ridecompass-cache-data:/app/data`も要る）。

使い方: `python -m benchmarks.bench_t790_compose_breakdown`
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

import numpy as np

from app.domain.route import Coordinates
from app.domain.route_preference import RoutePreference
from app.services import road_graph_engine as engine_module
from benchmarks._route_generation_service import refresh_axis_registry, route_generator_session

logging.basicConfig(level=logging.WARNING, format="%(message)s")

ORIGIN = Coordinates(
    latitude=float(os.environ.get("T790_LAT", "35.6817502")),
    longitude=float(os.environ.get("T790_LON", "139.7634149")),
)
RADIUS_KM = float(os.environ.get("T790_RADIUS_KM", "13"))
REPEATS = int(os.environ.get("T790_REPEATS", "3"))


def _stopwatch() -> dict[str, float]:
    """`_compose_at`の各段を計測するよう差し替え、段名→累積msの辞書を返す。"""
    totals: dict[str, float] = {}
    original = engine_module._LegCostComposer._compose_at

    def timed(self, passage, **kwargs):  # noqa: ANN001, ANN003, ANN202
        marks: list[tuple[str, float]] = [("start", time.perf_counter())]

        real_travel = self._travel_time_seconds

        def travel(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            started = time.perf_counter()
            result = real_travel(*args, **kwargs)
            totals["travel_time_seconds"] = totals.get("travel_time_seconds", 0.0) + (
                time.perf_counter() - started
            ) * 1000
            return result

        self._travel_time_seconds = travel  # type: ignore[method-assign]
        try:
            leg = original(self, passage, **kwargs)
        finally:
            del self._travel_time_seconds
        marks.append(("total", time.perf_counter()))
        totals["compose_at_total"] = totals.get("compose_at_total", 0.0) + (
            marks[-1][1] - marks[0][1]
        ) * 1000
        return leg

    engine_module._LegCostComposer._compose_at = timed  # type: ignore[method-assign]
    return totals


async def main() -> None:
    restore = engine_module._LegCostComposer._compose_at
    totals = _stopwatch()
    try:
        await refresh_axis_registry()
        async with route_generator_session(RoutePreference()) as generator:
            engine = generator._engine
            for run in range(1, REPEATS + 1):
                totals.clear()
                started = time.perf_counter()
                context = await engine.prepare(ORIGIN, radius_km=RADIUS_KM)
                prepare_ms = (time.perf_counter() - started) * 1000
                if context is None:
                    print("context=None（対象タイル未取込）")
                    return
                edges = len(context.composer._score_matrix.distance_m)
                calls = max(1, int(totals.get("compose_at_total", 0.0) // 1))
                print(
                    f"[{run}回目] edges={edges} prepare_ms={prepare_ms:.0f} "
                    f"compose_at_total_ms={totals.get('compose_at_total', 0.0):.0f} "
                    f"うち走行モデル+停止_ms={totals.get('travel_time_seconds', 0.0):.0f}"
                )
                _ = calls

            # 合成1本ぶんを繰り返して、走行モデルと軸合成の取り分を見る。
            composer = context.composer
            passage = np.zeros(len(composer._score_matrix.distance_m))
            totals.clear()
            started = time.perf_counter()
            for _ in range(REPEATS):
                composer._compose_at(passage)
            per_call_ms = (time.perf_counter() - started) * 1000 / REPEATS
            print(
                f"[合成のみ・表示用] 1本あたり={per_call_ms:.0f}ms "
                f"うち走行モデル+停止={totals.get('travel_time_seconds', 0.0) / REPEATS:.0f}ms"
            )
            totals.clear()
            started = time.perf_counter()
            for _ in range(REPEATS):
                composer._compose_at(passage, for_display=False)
            search_ms = (time.perf_counter() - started) * 1000 / REPEATS
            print(
                f"[合成のみ・探索用] 1本あたり={search_ms:.0f}ms "
                f"うち走行モデル+停止={totals.get('travel_time_seconds', 0.0) / REPEATS:.0f}ms"
            )
    finally:
        engine_module._LegCostComposer._compose_at = restore  # type: ignore[method-assign]


if __name__ == "__main__":
    asyncio.run(main())
