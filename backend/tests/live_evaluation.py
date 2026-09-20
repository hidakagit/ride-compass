"""テストが本番と同じ経路で区間ごとのコストを求めるための入口。

本番の探索は「材料の配列→静的スコア行列→重み付き合成→0次フィルタ」の順に進む
（`services/road_graph_engine.py`）。ここは本番の関数を順に呼ぶだけで、計算を持たない。
区間ごとの結果へ畳むのはテストの都合で、本番は配列のまま探索へ渡す。
"""

from dataclasses import dataclass

import numpy as np

from app.domain.attributes import EdgeMaterialArrays
from app.domain.evaluation import build_static_edge_score_matrix, compose_costs_from_axis_matrix
from app.domain.graph import LeanRoadGraph
from app.domain.hard_filters import compute_hard_filter_excluded
from app.domain.route_preference import RoutePreference


@dataclass(frozen=True, slots=True)
class EdgeCost:
    """区間1本ぶんの評価結果。0次フィルタで除外された区間はcost/difficultyがNone。"""

    edge_id: str
    cost: float | None
    difficulty: float | None
    allowed: bool


def edge_costs(
    graph: LeanRoadGraph,
    materials: EdgeMaterialArrays,
    preference: RoutePreference,
    *,
    hard_filters: frozenset[str] | None = None,
    max_average_grade_percent: float | None = None,
) -> dict[str, EdgeCost]:
    """区間id→評価結果。"""
    matrix = build_static_edge_score_matrix(graph, materials)
    if not matrix.edge_ids:
        return {}
    excluded = compute_hard_filter_excluded(
        matrix.hard_filter_flags, matrix.gradient_percent, hard_filters, max_average_grade_percent
    )
    composed = compose_costs_from_axis_matrix(
        matrix.distance_m, matrix.axis_arrays(), preference.weights, with_contributions=False
    )
    return {
        edge_id: (
            EdgeCost(edge_id=edge_id, cost=None, difficulty=None, allowed=False)
            if excluded[row]
            else EdgeCost(
                edge_id=edge_id,
                cost=float(composed.cost[row]),
                difficulty=(
                    None if np.isnan(composed.difficulty[row]) else float(composed.difficulty[row])
                ),
                allowed=True,
            )
        )
        for row, edge_id in enumerate(matrix.edge_ids)
    }


__all__ = ["EdgeCost", "edge_costs"]
