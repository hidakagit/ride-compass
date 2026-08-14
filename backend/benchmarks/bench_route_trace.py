"""`RoadGraphEngine`の経路探索フェーズ（`prepare`のグラフ構築後〜`trace_loop`）を
まとめて模擬計測する。

実際のリクエストは8方位（`RouteGenerator`のデフォルト）それぞれについて`trace_loop`を
呼び、内部で`find_nearest_node`を2回（経由地点A・Bのスナップ）・`shortest_path_node_ids`
（NetworkX Dijkstra）を3回（起点→A、A→B、B→起点）呼ぶ。加えて`prepare`で起点のスナップに
1回。合計で`find_nearest_node`は17回（1 + 2x8）、Dijkstraは24回（3x8）呼ばれる
（`bench_nearest_node.py`の`CALLS_PER_ROUTE_GENERATION_REQUEST`と同じ前提）。

合成の格子グラフ上で同じ回数の呼び出しを行い、「Node最近傍探索（線形探索）」と
「Dijkstra探索」のどちらが1リクエストの支配的なコストになっているかを内訳として示す。
"""

from __future__ import annotations

import random

from benchmarks._harness import BenchmarkResult, measure, print_report
from benchmarks._synthetic import GRID_SPACING_DEG, TOKYO_LAT, TOKYO_LON, make_grid_graph

BEARING_COUNT = 8  # RouteGenerator.DIRECTIONSと同じ想定
NEAREST_NODE_CALLS = 1 + 2 * BEARING_COUNT  # prepare 1回 + trace_loop 2回 x 8方位 = 17
DIJKSTRA_CALLS = 3 * BEARING_COUNT  # trace_loop 3回 x 8方位 = 24


def _random_grid_point(rows: int, cols: int, rng: random.Random):
    from app.domain.route import Coordinates

    return Coordinates(
        latitude=TOKYO_LAT + rng.uniform(0.05, 0.95) * rows * GRID_SPACING_DEG,
        longitude=TOKYO_LON + rng.uniform(0.05, 0.95) * cols * GRID_SPACING_DEG,
    )


def run() -> list[BenchmarkResult]:
    from app.domain.evaluation import compute_edge_cost
    from app.domain.routing import build_networkx_graph, concat_node_paths, find_nearest_node, path_to_edge_ids, shortest_path_node_ids
    from app.services.evaluation_service import load_route_preference

    preference = load_route_preference()
    results: list[BenchmarkResult] = []

    for rows, cols in [(23, 23), (45, 45), (90, 90)]:
        graph = make_grid_graph(rows, cols)
        node_count, edge_count = len(graph.nodes), len(graph.edges)

        edge_costs = {
            edge_id: compute_edge_cost(edge, None, None, preference, wind=None) for edge_id, edge in graph.edges.items()
        }
        nx_graph = build_networkx_graph(graph, edge_costs)

        rng = random.Random(42)
        origin = _random_grid_point(rows, cols, rng)
        # 8方位 x (経由地A, 経由地B) = 16点。実際のRouteGeneratorの周回経路と同じ構造。
        bearing_waypoints = [
            (_random_grid_point(rows, cols, rng), _random_grid_point(rows, cols, rng)) for _ in range(BEARING_COUNT)
        ]

        def trace_all_bearings(graph=graph, nx_graph=nx_graph, origin=origin, bearing_waypoints=bearing_waypoints):
            origin_node = find_nearest_node(graph, origin)
            for point_a, point_b in bearing_waypoints:
                node_a = find_nearest_node(graph, point_a)
                node_b = find_nearest_node(graph, point_b)
                path_1 = shortest_path_node_ids(nx_graph, origin_node, node_a)
                path_2 = shortest_path_node_ids(nx_graph, node_a, node_b)
                path_3 = shortest_path_node_ids(nx_graph, node_b, origin_node)
                if path_1 and path_2 and path_3:
                    full_path = concat_node_paths([path_1, path_2, path_3])
                    path_to_edge_ids(nx_graph, full_path)

        results.append(
            measure(
                f"8-bearing trace_loop simulation (nodes={node_count}, edges={edge_count})",
                trace_all_bearings,
                repeat=5,
                warmup=1,
            )
        )

        # 内訳: 同じ規模のグラフで「Node最近傍探索(線形探索)だけ」「Dijkstra探索だけ」を
        # それぞれ実リクエスト相当の回数(17回/24回)行い、どちらが支配的か切り分ける。
        all_points = [origin] + [p for pair in bearing_waypoints for p in pair]
        assert len(all_points) == NEAREST_NODE_CALLS

        def nearest_node_only(graph=graph, points=all_points):
            for point in points:
                find_nearest_node(graph, point)

        node_ids = [find_nearest_node(graph, p) for p in all_points]
        origin_node_id = node_ids[0]
        pairs = []
        for i in range(BEARING_COUNT):
            node_a, node_b = node_ids[1 + 2 * i], node_ids[2 + 2 * i]
            pairs.extend([(origin_node_id, node_a), (node_a, node_b), (node_b, origin_node_id)])
        assert len(pairs) == DIJKSTRA_CALLS

        def dijkstra_only(nx_graph=nx_graph, pairs=pairs):
            for a, b in pairs:
                shortest_path_node_ids(nx_graph, a, b)

        results.append(
            measure(f"  - find_nearest_node only x{len(all_points)} (nodes={node_count})", nearest_node_only, repeat=5, warmup=1)
        )
        results.append(
            measure(f"  - dijkstra_path only x{len(pairs)} (nodes={node_count})", dijkstra_only, repeat=5, warmup=1)
        )

    return results


if __name__ == "__main__":
    print_report("RoadGraphEngine trace phase: nearest-node + Dijkstra x 8 bearings", run())
