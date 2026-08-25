"""`EvaluationService.evaluate_graph`の計測（改善計画T238）。

T220の完了メモが「evaluate_graph自体（car_stress判定が支配的、cProfileで確認済み）は
今回手を付けていない」と残した高速化候補への対応として、`car_stress_level`の
pydanticモデル構築コストを避けるT238の変更前後を比較する（`git stash`で本コミットの
差分を退避・復元しながら同一ベンチマークを2回走らせる運用を想定）。

T219/T220が基準にした約69,216エッジ規模と、T224が基準にした約122,710エッジ相当の
2規模で計測する。
"""

from __future__ import annotations

from benchmarks._harness import BenchmarkResult, measure, print_report
from benchmarks._synthetic import make_grid_graph


def run() -> list[BenchmarkResult]:
    from app.services.evaluation_service import EvaluationService, load_route_preference

    preference = load_route_preference()
    service = EvaluationService(preference)

    results: list[BenchmarkResult] = []
    # (131, 131) ≈ 68,120エッジ（T219/T220基準）、(175, 175) ≈ 122,032エッジ（T224基準相当）。
    for rows, cols in [(131, 131), (175, 175)]:
        graph = make_grid_graph(rows, cols)
        edge_count = len(graph.edges)
        way_tags = {edge_id: {"highway": "residential"} for edge_id in graph.edges}

        result = measure(
            f"evaluate_graph (edges={edge_count})",
            lambda g=graph, wt=way_tags: service.evaluate_graph(
                g, elevation_attributes={}, surface_attributes={}, preference=preference, way_tags=wt
            ),
            repeat=10,
        )
        results.append(result)

    return results


if __name__ == "__main__":
    print_report("EvaluationService.evaluate_graph", run())
