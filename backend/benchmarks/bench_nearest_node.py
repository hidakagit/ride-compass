"""`domain/routing.py: find_nearest_node_indexed`の計測。

`RoadGraphEngine`は1リクエストあたり`prepare`で1回・`trace_loop`で方位ごとに2回
（8方位なら16回）＝計17回、最も近いNodeを探す呼び出しを行う。索引
（`build_node_spatial_index`のグリッドバケット）は1リクエストにつき1回だけ構築して
使い回すため、ここでは索引構築を計測対象の外に置き、探索そのものがノード数に対して
どうスケールするかを確認する。
"""

from __future__ import annotations

from benchmarks._harness import BenchmarkResult, measure, print_report
from benchmarks._synthetic import grid_point, make_grid_graph

CALLS_PER_ROUTE_GENERATION_REQUEST = 17  # prepare 1回 + trace_loop(2回 x 8方位)


def run() -> list[BenchmarkResult]:
    from app.domain.routing import build_node_spatial_index, find_nearest_node_indexed

    results: list[BenchmarkResult] = []
    for rows, cols in [(23, 23), (45, 45), (90, 90), (142, 142)]:
        graph = make_grid_graph(rows, cols)
        node_count = len(graph.nodes)
        target = grid_point(rows, cols, 0.5, 0.5)
        index = build_node_spatial_index(graph)

        result = measure(
            f"find_nearest_node_indexed (nodes={node_count})",
            lambda idx=index, t=target: find_nearest_node_indexed(idx, t),
            repeat=30,
        )
        # 1リクエスト分（17回呼び出し）の推定コストをnoteへ埋め込む（medianベース、索引構築は含まない）。
        result.note = f"~{result.median_s * CALLS_PER_ROUTE_GENERATION_REQUEST * 1000:.1f} ms / route-generation request (x{CALLS_PER_ROUTE_GENERATION_REQUEST} calls)"
        results.append(result)

    return results


if __name__ == "__main__":
    print_report("find_nearest_node_indexed: grid bucket index scaling", run())
