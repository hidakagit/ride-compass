"""テストが本番と同じ経路でEdgeのコストを求めるための入口。

本番の探索は「材料の配列→静的スコア行列→（動的軸の上書き）→重み付き合成→0次フィルタ」
という順に進む（`services/road_graph_engine.py`）。テストは区間1本や数本を見たいだけだが、
**別の合成をテスト用に書くと、それが検証しているのは本番ではなくその写しになる**。
ここは本番の関数を順に呼ぶだけで、計算を持たない。
"""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from app.domain.attributes import EdgeMaterialArrays
from app.domain.dynamic_materials import DynamicAxisRequestContext, evaluate_dynamic_axis_arrays
from app.domain.evaluation import build_static_edge_score_matrix, compose_costs_from_axis_matrix
from app.domain.graph import RoadGraphLike
from app.domain.hard_filters import compute_hard_filter_excluded
from app.domain.route_preference import RoutePreference
from app.domain.weather import WeatherConditions


@dataclass(frozen=True, slots=True)
class EdgeCost:
    """区間1本ぶんの評価結果。0次フィルタで除外された区間はcost/difficultyがNone。"""

    edge_id: str
    cost: float | None
    difficulty: float | None
    allowed: bool


def edge_costs(
    graph: RoadGraphLike,
    materials: EdgeMaterialArrays,
    preference: RoutePreference,
    *,
    weights: dict[str, float] | None = None,
    penalty_strength: float = 1.0,
    hard_filters: frozenset[str] | None = None,
    max_average_grade_percent: float | None = None,
    weather: WeatherConditions | None = None,
    travel_speed_ms: float | None = None,
    accident_years_covered: int = 0,
) -> dict[str, EdgeCost]:
    """区間id→評価結果。`weather`を渡すと動的軸（風）もリクエスト時の値で埋める。"""
    matrix = build_static_edge_score_matrix(graph, materials, accident_years_covered)
    if not matrix.edge_ids:
        return {}
    axis_arrays: Mapping[str, np.ndarray] = {
        axis_id: matrix.axis_scores[:, column] for column, axis_id in enumerate(matrix.axis_ids)
    }
    if weather is not None:
        if travel_speed_ms is None:
            raise ValueError("weatherを渡すときはtravel_speed_msが要る")
        resolved = evaluate_dynamic_axis_arrays(
            axis_arrays,
            DynamicAxisRequestContext(
                bearing_deg=matrix.bearing_deg, weather=weather, travel_speed_ms=travel_speed_ms
            ),
        )
        axis_arrays = {axis_id: resolved[axis_id] for axis_id in matrix.axis_ids}

    excluded = compute_hard_filter_excluded(
        matrix.hard_filter_flags, matrix.gradient_percent, hard_filters, max_average_grade_percent
    )
    composed = compose_costs_from_axis_matrix(
        matrix.distance_m,
        axis_arrays,
        weights if weights is not None else preference.weights,
        penalty_strength,
        with_contributions=False,
    )
    return {
        edge_id: (
            EdgeCost(edge_id=edge_id, cost=None, difficulty=None, allowed=False)
            if excluded[row]
            else EdgeCost(
                edge_id=edge_id,
                cost=float(composed.cost[row]),
                difficulty=(
                    None
                    if np.isnan(composed.difficulty[row])
                    else float(composed.difficulty[row])
                ),
                allowed=True,
            )
        )
        for row, edge_id in enumerate(matrix.edge_ids)
    }


def axis_scores(
    graph: RoadGraphLike,
    materials: EdgeMaterialArrays,
    edge_id: str,
    *,
    accident_years_covered: int = 0,
    weather: WeatherConditions | None = None,
    travel_speed_ms: float | None = None,
) -> dict[str, float]:
    """区間1本ぶんの軸別スコア（算出できなかった軸はキーごと落とす）。"""
    matrix = build_static_edge_score_matrix(graph, materials, accident_years_covered)
    row = matrix.edge_ids.index(edge_id)
    arrays: Mapping[str, np.ndarray] = {
        axis_id: matrix.axis_scores[:, column] for column, axis_id in enumerate(matrix.axis_ids)
    }
    if weather is not None:
        if travel_speed_ms is None:
            raise ValueError("weatherを渡すときはtravel_speed_msが要る")
        arrays = evaluate_dynamic_axis_arrays(
            arrays,
            DynamicAxisRequestContext(
                bearing_deg=matrix.bearing_deg, weather=weather, travel_speed_ms=travel_speed_ms
            ),
        )
    return {
        axis_id: float(arrays[axis_id][row])
        for axis_id in matrix.axis_ids
        if not np.isnan(arrays[axis_id][row])
    }


__all__ = ["EdgeCost", "axis_scores", "edge_costs"]
