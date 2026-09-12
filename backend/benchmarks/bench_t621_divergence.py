"""[T621](../../docs/tasks/T621.md)段取り1の実測: 実データで目的地候補の分岐点がいくつ出るか。

`RouteGenerator._generate_destination_routes`と同じ手順（`prepare`→`select_via_nodes`
→最短経路の追加）で実候補を作り、各候補を「表示中」と見立てたときの分岐点
（＝地図に置くマーカー）の個数・位置・乗り換え先の数を出す。T621の論点4は
「候補8本ぶんの分岐点を全部出すと地図が埋まるか」が決め手で、モックでは埋まらなかったが
実データでは未確認のため、ここを測る。

併せて次の2つを確認する:
- 合成した経路がグラフ上で連結しているか（前のEdgeのto_node＝次のEdgeのfrom_node）。
  T621の論点5「同じノードでつなぐ限り経路として成立する」を実データで確かめる。
- 温パスの`prepare`所要時間（`T621_BENCH_RUNS`が2以上のとき、2回目以降が温）。

`bench_t551_route_generation.py`と同じく**読み取り経路のみを通す**（未splitのbboxは
`prepare`が再構築＝書き込み経路に入るため、既定では中断する）。

環境変数:
- `T621_BENCH_ORIGIN` / `T621_BENCH_DESTINATION`: `lat,lon`（既定はbench_t551と同じ
  東京駅相当 → 船橋駅相当）
- `T621_BENCH_MAX_ROUTES`: 候補件数（既定8）
- `T621_BENCH_RUNS`: prepare→select の実行回数（既定2。1回目は冷パス、2回目が温パス）
- `T621_BENCH_ALLOW_UNSPLIT`: `1`で未split中断を無効化（本番では使わない）

使い方: `python -m benchmarks.bench_t621_divergence`
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime

from app.domain.route_preference import RoutePreference
from app.domain.geo import haversine_distance_km
from app.domain.route import Coordinates
from app.domain.time_zone import JST
from app.services.route_generator import TURNAROUND_RADIUS_RATIO
from benchmarks._divergence import divergence_points, spliced_path
from benchmarks._route_generation_service import (
    assert_read_only_path,
    refresh_axis_registry,
    route_generator_session,
)

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s")
logging.getLogger("ridecompass.generate").setLevel(logging.INFO)
logging.getLogger("ridecompass.graph").setLevel(logging.INFO)


def _coordinates(env_name: str, default: str) -> Coordinates:
    latitude, longitude = (float(part) for part in os.getenv(env_name, default).split(","))
    return Coordinates(latitude=latitude, longitude=longitude)


ORIGIN = _coordinates("T621_BENCH_ORIGIN", "35.6817502,139.7634149")
DESTINATION = _coordinates("T621_BENCH_DESTINATION", "35.7015,139.9825")
MAX_ROUTES = int(os.getenv("T621_BENCH_MAX_ROUTES", "8"))
RUNS = int(os.getenv("T621_BENCH_RUNS", "2"))
ALLOW_UNSPLIT = os.getenv("T621_BENCH_ALLOW_UNSPLIT") == "1"
DISTANCE_KM = haversine_distance_km(ORIGIN, DESTINATION)


def _is_connected(graph, path: list[str]) -> bool:
    """`path`のEdge列がグラフ上で連結しているか（前のto_node＝次のfrom_node）。"""
    edges = [graph.edges[edge_id] for edge_id in path]
    return all(current.to_node_id == following.from_node_id for current, following in zip(edges, edges[1:]))


def _cumulative_km(graph, path: list[str], index: int) -> float:
    return sum(graph.edges[edge_id].distance_m for edge_id in path[:index]) / 1000.0


def _report(graph, paths: dict[str, list[str]]) -> None:
    spliced_total = 0
    spliced_connected = 0
    marker_counts: list[int] = []

    for label, displayed in paths.items():
        others = {other: path for other, path in paths.items() if other != label}
        points = divergence_points(displayed, others)
        marker_counts.append(len(points))
        print(f"\n--- 表示中={label} edges={len(displayed)} マーカー={len(points)}個")
        for point in points:
            km = _cumulative_km(graph, displayed, point.index)
            print(f"    {km:6.2f}km地点 乗り換え先={len(point.targets)}件 {sorted(point.targets)}")
            for target in point.targets:
                path = spliced_path(displayed, paths[target], point)
                spliced_total += 1
                spliced_connected += _is_connected(graph, path)

    print(
        f"\n=== マーカー個数: 最小{min(marker_counts)} 最大{max(marker_counts)} "
        f"平均{sum(marker_counts) / len(marker_counts):.1f}（候補{len(paths)}本）"
    )
    print(f"=== 合成経路の連結: {spliced_connected}/{spliced_total} 件が連結")


async def main() -> None:
    print(f"origin={ORIGIN} destination={DESTINATION} distance_km={DISTANCE_KM:.1f} max_routes={MAX_ROUTES}")
    radius_km = DISTANCE_KM * TURNAROUND_RADIUS_RATIO
    await assert_read_only_path(
        ORIGIN, radius_km,
        allow_unsplit=ALLOW_UNSPLIT, allow_unsplit_env_hint="T621_BENCH_ALLOW_UNSPLIT",
    )
    await refresh_axis_registry()

    async with route_generator_session(RoutePreference()) as generator:
        # 分岐点はEdge id列（`TracedLoop.data`）から求めるため、RouteCandidateを組み立てる
        # RouteGeneratorではなくengineを直接呼ぶ（候補へのedge_ids露出は段取り2）。
        engine = generator._engine
        context = None
        traced = []
        for run in range(RUNS):
            start_time = datetime.now(JST)
            started = time.monotonic()
            context = await engine.prepare(ORIGIN, radius_km, waypoints=[DESTINATION], now=start_time)
            prepare_ms = round((time.monotonic() - started) * 1000)
            if context is None:
                raise SystemExit("道路データが無く候補を生成できません")
            select_started = time.monotonic()
            traced = await engine.select_via_nodes(context, DESTINATION, MAX_ROUTES)
            select_ms = round((time.monotonic() - select_started) * 1000)
            print(f"{run + 1}回目: prepare_ms={prepare_ms} select_ms={select_ms} traced={len(traced)}")

        shortest = await engine.select_shortest_distance_route(context, DESTINATION)
        if shortest is not None and all(t.data != shortest.data for t in traced):
            traced.append(shortest)

    if not traced:
        raise SystemExit("候補が0件でした")
    paths = {f"route-{index:02d}": list(loop.data) for index, loop in enumerate(traced)}
    _report(context.graph, paths)


if __name__ == "__main__":
    asyncio.run(main())
