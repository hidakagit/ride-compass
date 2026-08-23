"""`domain/graph.py: build_road_graph`の計測（Road Graph構築、交差点分割）。

`GraphService.get_or_build_graph_with_attributes`は、生データが前回のsplit以降
変わっていた場合（または未取込）に、PostGIS上の生Way/Nodeデータに対してこの関数を
呼び出す（省略パスが効かない低頻度・重い経路）。Way数・Node数の増加に対する構築コストの
スケールを確認する。
"""

from __future__ import annotations

from benchmarks._harness import BenchmarkResult, measure, print_report
from benchmarks._synthetic import make_grid_way_specs


def run() -> list[BenchmarkResult]:
    from app.domain.graph import build_road_graph

    results: list[BenchmarkResult] = []
    for rows, cols in [(23, 23), (45, 45), (90, 90), (142, 142)]:
        ways, node_coords = make_grid_way_specs(rows, cols)

        result = measure(
            f"build_road_graph (ways={len(ways)}, nodes={len(node_coords)})",
            lambda w=ways, n=node_coords: build_road_graph(w, n),
            repeat=10,
        )
        results.append(result)

    return results


if __name__ == "__main__":
    print_report("build_road_graph: construction scaling", run())
