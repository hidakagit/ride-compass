"""改善計画T792: 2点間探索のA*ヒューリスティックをどこまで強められるかを測る。

コストの単位が秒になったため、下界は「直線距離 ÷ 出せる最大速度」で作っている
（`road_graph_engine.py: _heuristic_seconds`）。この`出せる最大速度`が下り坂の上限
（`MAX_DESCENT_SPEED_KMH`）という**どの経路でも到達しない値**のため、下界が実際のコストから
大きく離れ、A*が実質ダイクストラとして動いている疑いがある。

同じ起点・目的地・同じコスト配列に対して、下界の作り方だけを変えて壁時計と得られた経路を
比べる。**admissible（真のコスト以下）でなければ経路が変わる**ため、経路の一致も併せて見る。

比べる下界:
- `descent`: 現行（直線距離 ÷ MAX_DESCENT_SPEED_KMH）
- `observed`: bbox内の区間から実測した最速の秒/m（`min(所要時間 / 距離)`）を使う。
  どの経路も「その区間の速さ」より速くは進めないため下界であり続ける
- `zero`: 下界0（＝ダイクストラ）。A*が効いているかの基準線

本番VMでは稼働中のbackendコンテナとは別に、backendイメージの使い捨てコンテナから実行する
（`--network=host --env-file /home/ubuntu/ridecompass-backend.env`、風の実データを読むため
`-v /home/ubuntu/ridecompass-cache-data:/app/data`も要る）。

使い方: `python -m benchmarks.bench_t792_heuristic`
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

import numpy as np

from app.domain.route import Coordinates
from app.domain.route_preference import RoutePreference
from app.domain.routing import find_nearest_node_indexed, turn_expanded_shortest_path
from app.services.road_graph_engine import _estimate_distances_m, _origin_states
from benchmarks._route_generation_service import refresh_axis_registry, route_generator_session

logging.basicConfig(level=logging.WARNING, format="%(message)s")


def _coordinate(name: str, default: Coordinates) -> Coordinates:
    raw = os.environ.get(name)
    if not raw:
        return default
    latitude, longitude = (float(part) for part in raw.split(","))
    return Coordinates(latitude=latitude, longitude=longitude)


ORIGIN = _coordinate("T792_ORIGIN", Coordinates(latitude=35.8617, longitude=139.9707))
DESTINATION = _coordinate("T792_DESTINATION", Coordinates(latitude=35.7528, longitude=139.7386))
REPEATS = int(os.environ.get("T792_REPEATS", "3"))


async def main() -> None:
    await refresh_axis_registry()
    async with route_generator_session(RoutePreference()) as generator:
        engine = generator._engine
        context = await engine.prepare(ORIGIN, radius_km=30.0, waypoints=[DESTINATION])
        if context is None:
            print("context=None（対象タイル未取込）")
            return

        # 目的地の再スナップ（メインの道路網から孤立したNodeへ寄ったときの補正）は
        # `select_via_nodes`が行い、`select_fastest_route`はその結果を引き継ぐ。実経路と
        # 同じ順に呼んでから測る。
        await engine.select_via_nodes(context, DESTINATION, max_routes=3)
        destination = context.destination_correction or DESTINATION
        origin_node = context.origin_node
        destination_node = find_nearest_node_indexed(context.node_index, destination)
        if destination_node is None:
            print("目的地をスナップできない")
            return
        leg = context.legs[0]
        straight_m = np.asarray(
            _estimate_distances_m(context.graph, context.node_lat, context.node_lon, destination_node)
        )
        origin_states = _origin_states(context.statics, context.lazy_graph.node_id_to_index[origin_node])
        goal_index = context.lazy_graph.node_id_to_index[destination_node]
        print(
            f"origin={origin_node} destination={destination_node} "
            f"origin_states={len(origin_states)} goal_index={goal_index} "
            f"finite_cost={int(np.isfinite(context.legs[0].cost_bins_lazy[0]).sum())}"
        )

        probe = await engine.select_fastest_route(context, destination)
        print(f"select_fastest_route -> {'None' if probe is None else str(len(probe.data)) + '区間'}")

        seconds = leg.travel_seconds_lazy
        length_m = context.statics.edge_length_m
        usable = np.isfinite(seconds) & (length_m > 0)
        observed_sec_per_m = float(np.min(seconds[usable] / length_m[usable]))
        descent_sec_per_m = 1.0 / (45.0 / 3.6)
        print(
            f"edges={len(seconds)} states={context.turn_structure.state_count} "
            f"最速の秒/m: 現行の下界={descent_sec_per_m:.4f} 実測={observed_sec_per_m:.4f} "
            f"（実測の方が{observed_sec_per_m / descent_sec_per_m:.2f}倍きつい下界）"
        )

        cruise_sec_per_m = 1.0 / (context.composer.speed_kmh / 3.6)
        variants = {
            "zero（ダイクストラ）": np.zeros(len(straight_m)),
            "descent（現行・下り上限）": straight_m * descent_sec_per_m,
            "observed（実測の最速）": straight_m * observed_sec_per_m,
            "x1.5（admissibleでない）": straight_m * descent_sec_per_m * 1.5,
            "巡航速度（admissibleでない）": straight_m * cruise_sec_per_m,
            "巡航x1.5（admissibleでない）": straight_m * cruise_sec_per_m * 1.5,
        }
        baseline: list[int] | None = None
        for label, heuristic in variants.items():
            best_ms = float("inf")
            path: list[int] | None = None
            for _ in range(REPEATS):
                started = time.perf_counter()
                path = turn_expanded_shortest_path(
                    context.turn_structure, leg.cost_bins_lazy, heuristic, origin_states, goal_index,
                    leg.travel_bins_lazy, leg.bin_seconds,
                )
                best_ms = min(best_ms, (time.perf_counter() - started) * 1000)
            if baseline is None:
                baseline = path
            edges = 0 if path is None else len(path)
            if path == baseline:
                same = "経路一致"
            else:
                shared = len(set(path or []) & set(baseline or []))
                same = f"**経路が変わる**（共有区間 {shared}/{len(baseline or [])}）"
            print(f"[{label}] elapsed_ms={best_ms:.0f} 区間数={edges} {same}")


if __name__ == "__main__":
    asyncio.run(main())
