"""`domain/routing.py: find_nearest_node`の計測。

このリンター探索は明示的に「総当たりの線形探索」（docstring参照、PostGIS空間インデックス
未使用構成向け）として実装されている。`RoadGraphEngine`は1リクエストあたり
`prepare`で1回・`trace_loop`で方位ごとに2回（8方位なら16回）＝計17回呼び出すため、
ノード数に対して線形の可視化と、ノード数が増えたときに1リクエストあたりの累積コストが
どう伸びるかを確認する。
"""

from __future__ import annotations

from benchmarks._harness import BenchmarkResult, measure, print_report
from benchmarks._synthetic import grid_point, make_grid_graph

CALLS_PER_ROUTE_GENERATION_REQUEST = 17  # prepare 1回 + trace_loop(2回 x 8方位)


def run() -> list[BenchmarkResult]:
    from app.domain.routing import find_nearest_node

    results: list[BenchmarkResult] = []
    for rows, cols in [(23, 23), (45, 45), (90, 90), (142, 142)]:
        graph = make_grid_graph(rows, cols)
        node_count = len(graph.nodes)
        target = grid_point(rows, cols, 0.5, 0.5)

        result = measure(
            f"find_nearest_node (nodes={node_count})",
            lambda g=graph, t=target: find_nearest_node(g, t),
            repeat=30,
        )
        # 1リクエスト分（17回呼び出し）の推定コストをnoteへ埋め込む（medianベース）。
        result.note = f"~{result.median_s * CALLS_PER_ROUTE_GENERATION_REQUEST * 1000:.1f} ms / route-generation request (x{CALLS_PER_ROUTE_GENERATION_REQUEST} calls)"
        results.append(result)

    return results


if __name__ == "__main__":
    print_report("find_nearest_node: linear scan scaling", run())
