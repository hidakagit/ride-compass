"""改善計画T802: 2点間探索の増分が、時刻ビンの持ち回り由来かを切り分ける。

[T790](../../docs/tasks/T790.md)段階Dで探索は`(時刻ビン, 状態)`の2次元コスト配列から
その時刻の行を引くようになり、本番計測で`trace`が179→704msになった。増分の出どころとして
次の2つが混ざっている:

1. **状態空間が変わった**: 状態＝交差点ノードから状態＝有向区間（ターン展開）へ。
   状態数はノード数より多く、1回の探索で触る量そのものが増える。
2. **時刻ラベルを持ち回るようになった**: 取り出した状態ごとに経過時間からビンを求め、
   遷移ごとに2次元の添字で引き、到達時刻を書く。

この2つは対策が正反対（1は訪問状態を減らす＝[T792](../../docs/tasks/T792.md)、
2は1状態あたりの手間を減らす＝本タスク）なので、**どちらがどれだけかを先に測る**。

測るもの:
- ノード数と状態数の比（1がどれだけ効いているか）
- 同じ入力・同じ状態空間で、ビン1本とビン複数の壁時計（2の上側の見積もり）
- 訪問状態の割合（A*が効いているか。T792と同じ量）

本番VMでは稼働中のbackendコンテナとは別に、backendイメージの使い捨てコンテナから実行する
（`--network=host --env-file /home/ubuntu/ridecompass-backend.env`、風の実データを読むため
`-v /home/ubuntu/ridecompass-cache-data:/app/data`も要る）。

使い方: `python -m benchmarks.bench_t802_time_bins`
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


ORIGIN = _coordinate("T802_ORIGIN", Coordinates(latitude=35.6812, longitude=139.7671))
DESTINATION = _coordinate("T802_DESTINATION", Coordinates(latitude=35.7528, longitude=139.7386))
REPEATS = int(os.environ.get("T802_REPEATS", "5"))
#: ビンを増やしたときの手間を見るための本数。実データのレグは目標30kmの周回で1本に収まる。
BIN_COUNTS = [int(part) for part in os.environ.get("T802_BINS", "1,2,4,8,16").split(",")]


def _tile_to_bins(rows: np.ndarray, bin_count: int) -> np.ndarray:
    """1本ぶんのコスト配列を`bin_count`本へ複製する。

    **値は変えない**——ビンの本数だけを変えて、添字の次元が増えることの手間を見る。
    値まで変えると経路が変わり、壁時計の比較にならない。
    """
    return np.ascontiguousarray(np.repeat(rows[:1], bin_count, axis=0))


async def main() -> None:
    await refresh_axis_registry()
    async with route_generator_session(RoutePreference()) as generator:
        engine = generator._engine
        context = await engine.prepare(ORIGIN, radius_km=30.0, waypoints=[DESTINATION])
        if context is None:
            print("context=None（対象タイル未取込）")
            return

        await engine.select_via_nodes(context, DESTINATION, max_routes=3)
        destination = context.destination_correction or DESTINATION
        destination_node = find_nearest_node_indexed(context.node_index, destination)
        if destination_node is None:
            print("目的地をスナップできない")
            return

        leg = context.legs[0]
        origin_states = _origin_states(
            context.statics, context.lazy_graph.node_id_to_index[context.origin_node]
        )
        goal_index = context.lazy_graph.node_id_to_index[destination_node]
        straight_m = np.asarray(
            _estimate_distances_m(context.graph, context.node_lat, context.node_lon, destination_node)
        )
        heuristic = straight_m / (45.0 / 3.6)

        node_count = len(context.graph.nodes)
        state_count = context.turn_structure.state_count
        print(
            f"ノード {node_count:,} / 状態（有向区間） {state_count:,}"
            f"（{state_count / max(node_count, 1):.1f}倍）"
        )
        print(f"実データのビン本数: {leg.cost_bins_lazy.shape[0]}（bin_seconds={leg.bin_seconds}）")
        print()

        baseline_path: list[int] | None = None
        for bin_count in BIN_COUNTS:
            cost = _tile_to_bins(leg.cost_bins_lazy, bin_count)
            seconds = _tile_to_bins(leg.travel_bins_lazy, bin_count)
            # ビンが1本のときは境界を跨がないよう幅を無限に、複数のときは実際に跨ぐよう
            # 経路の所要時間より短い幅にする（添字が0のまま動かないと手間を測れない）。
            bin_seconds = np.inf if bin_count == 1 else 60.0
            best_ms = float("inf")
            path: list[int] | None = None
            for _ in range(REPEATS):
                started = time.perf_counter()
                path = turn_expanded_shortest_path(
                    context.turn_structure, cost, heuristic, origin_states, goal_index,
                    seconds, bin_seconds,
                )
                best_ms = min(best_ms, (time.perf_counter() - started) * 1000)
            if baseline_path is None:
                baseline_path = path
            same = "経路一致" if path == baseline_path else "**経路が変わる**"
            print(f"ビン{bin_count:>3}本: elapsed_ms={best_ms:7.1f} 区間数={0 if path is None else len(path)} {same}")


if __name__ == "__main__":
    asyncio.run(main())
