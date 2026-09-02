"""`RoadGraphEngine`の経路探索フェーズ（`prepare`のグラフ構築後〜復路探索）をまとめて
模擬計測する。

改善計画T531以降の実際のリクエストは、`select_loop_turnarounds`で起点からの一対全最短
経路木（`build_shortest_path_tree`、scipy）を1回求め、折返し点候補ごとに復路のA*
（`shortest_path_node_ids_lazy`、rustworkx）を1回呼ぶ。加えて`prepare`で起点のスナップ
（`find_nearest_node_indexed`）に1回。合成の格子グラフ上で同じ構成の呼び出しを行い、
「一対全木」「復路A*×候補数」のどちらが1リクエストの支配的なコストになっているかを
内訳として示す。
"""

from __future__ import annotations

import random

import numpy as np

from benchmarks._harness import BenchmarkResult, measure, print_report
from benchmarks._synthetic import GRID_SPACING_DEG, TOKYO_LAT, TOKYO_LON, make_grid_graph

POOL_SIZE = 24  # RouteGenerator.turnaround_pool_size(8)と同じ想定


def _random_grid_point(rows: int, cols: int, rng: random.Random):
    from app.domain.route import Coordinates

    return Coordinates(
        latitude=TOKYO_LAT + rng.uniform(0.05, 0.95) * rows * GRID_SPACING_DEG,
        longitude=TOKYO_LON + rng.uniform(0.05, 0.95) * cols * GRID_SPACING_DEG,
    )


def run() -> list[BenchmarkResult]:
    from app.domain.routing import (
        build_lazy_road_graph,
        build_node_spatial_index,
        build_search_graph_statics,
        build_shortest_path_tree,
        find_nearest_node_indexed,
        shortest_path_node_ids_lazy,
    )

    results: list[BenchmarkResult] = []

    for rows, cols in [(23, 23), (45, 45), (90, 90)]:
        graph = make_grid_graph(rows, cols)
        node_count, edge_count = len(graph.nodes), len(graph.edges)
        lazy_graph = build_lazy_road_graph(graph)
        statics = build_search_graph_statics(lazy_graph, graph)
        rng = random.Random(42)
        # コストは距離×(1〜2倍)の乱数（cost >= distanceの不変条件を満たす）。
        cost_array = statics.edge_length_m * np.array([rng.uniform(1.0, 2.0) for _ in range(edge_count)])
        cost_list = cost_array.tolist()
        spatial_index = build_node_spatial_index(graph)
        zero_estimate = [0.0] * node_count

        origin = _random_grid_point(rows, cols, rng)
        origin_node = find_nearest_node_indexed(spatial_index, origin)
        origin_index = lazy_graph.node_id_to_index[origin_node]
        turnaround_nodes = [find_nearest_node_indexed(spatial_index, _random_grid_point(rows, cols, rng)) for _ in range(POOL_SIZE)]

        def tree_only(statics=statics, cost_array=cost_array, origin_index=origin_index):
            build_shortest_path_tree(statics.csr, cost_array, statics.edge_length_m, origin_index)

        def return_legs_only(lazy_graph=lazy_graph, cost_list=cost_list, origin_node=origin_node, nodes=turnaround_nodes):
            for node in nodes:
                shortest_path_node_ids_lazy(lazy_graph, node, origin_node, cost_list.__getitem__, zero_estimate.__getitem__)

        results.append(
            measure(
                f"one-to-all tree (nodes={node_count}, edges={edge_count})", tree_only, repeat=5, warmup=1,
            )
        )
        results.append(
            measure(
                f"  - return-leg A* x{POOL_SIZE} (nodes={node_count})", return_legs_only, repeat=5, warmup=1,
            )
        )

    return results


if __name__ == "__main__":
    print_report("RoadGraphEngine trace phase: one-to-all tree + return-leg A* x pool", run())
