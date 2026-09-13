"""改善計画T790段階D: レグ合成（`_LegCostComposer`）の内訳を測る。

コスト配列の合成がルート生成の支配項になったため、どの部品が支配的かを部品単位で出す
（推測で最適化しないため）。`_compose_at`が呼ぶ関数を計測用に包んで段ごとに積む。

本番VMでは稼働中のbackendコンテナとは別に、backendイメージの使い捨てコンテナから実行する
（`--network=host --env-file /home/ubuntu/ridecompass-backend.env`、風の実データを読むため
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
RADIUS_KM = float(os.environ.get("T790_RADIUS_KM", "12"))
REPEATS = int(os.environ.get("T790_REPEATS", "3"))

TOTALS: dict[str, float] = {}


def _timed(owner, name: str, attribute: str):
    """`owner.attribute`を、呼び出し時間を`TOTALS[name]`へ積む関数で包む。"""
    original = getattr(owner, attribute)

    def wrapper(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        started = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            TOTALS[name] = TOTALS.get(name, 0.0) + (time.perf_counter() - started) * 1000

    setattr(owner, attribute, wrapper)
    return lambda: setattr(owner, attribute, original)


async def main() -> None:
    restores = [
        _timed(engine_module._LegCostComposer, "1_走行モデル+停止", "_travel_time_seconds"),
        _timed(engine_module, "2_軸の合成", "compose_costs_from_axis_matrix"),
        _timed(engine_module, "3_動的軸の評価", "evaluate_dynamic_axis_arrays"),
        _timed(engine_module, "4_風の成分", "wind_components"),
    ]
    try:
        await refresh_axis_registry()
        async with route_generator_session(RoutePreference()) as generator:
            engine = generator._engine
            context = await engine.prepare(ORIGIN, radius_km=RADIUS_KM)
            if context is None:
                print("context=None（対象タイル未取込）")
                return
            composer = context.composer
            edges = len(composer._score_matrix.distance_m)

            # 合成器の組み立て（時刻に依らない軸の重み付き和の先取りを含む）。
            started = time.perf_counter()
            for _ in range(REPEATS):
                engine_module._LegCostComposer(
                    composer._score_matrix, composer._weights, composer._penalty_strength,
                    composer._hard_filter_excluded, composer._weather, composer._wind_series,
                    composer.start, composer.speed_kmh, composer._lazy_row_index,
                )
            build_ms = (time.perf_counter() - started) * 1000 / REPEATS
            print(f"edges={edges} 合成器の組み立て={build_ms:.0f}ms")

            passage = np.zeros(edges)
            for label, kwargs in (("表示用", {}), ("探索用", {"for_display": False})):
                TOTALS.clear()
                started = time.perf_counter()
                for _ in range(REPEATS):
                    composer._compose_at(passage, **kwargs)
                total_ms = (time.perf_counter() - started) * 1000 / REPEATS
                parts = " ".join(
                    f"{name[2:]}={value / REPEATS:.0f}ms" for name, value in sorted(TOTALS.items())
                )
                accounted = sum(TOTALS.values()) / REPEATS
                print(f"[{label}] 合計={total_ms:.0f}ms {parts} その他={total_ms - accounted:.0f}ms")
    finally:
        for restore in restores:
            restore()


if __name__ == "__main__":
    asyncio.run(main())
