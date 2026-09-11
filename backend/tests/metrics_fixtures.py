"""`MaterialExtractionContext.metrics`（群名→edge_id→{キー: 値}）をテストから組み立てる糖衣。

スカラー経路（`compute_edge_cost`/`compute_edge_axis_scores`）とベクトル経路
（`compute_edge_costs_bulk`）は同じ形の`metrics`を受け取るため、パリティテストは
**同じ1つの辞書**を両方へ渡せる（件数をスカラー引数と`metrics`の2通りで作ると、
片方だけ更新して食い違ったまま「一致した」と誤判定しうる）。
"""

from app.domain.attributes import (
    METRIC_GROUP_COUNTS,
    METRIC_GROUP_GEOMETRY,
    METRIC_GROUP_LANDCOVER,
    METRIC_GROUP_POI,
    METRIC_KEY_ACCIDENT,
    METRIC_KEY_BUILT_PERCENT,
    METRIC_KEY_CURVATURE,
    METRIC_KEY_INTERSECTION,
    METRIC_KEY_TREES_PERCENT,
)

Metrics = dict[str, dict[str, dict[str, float]]]


def counts_row(
    accident: float | None = None,
    intersection: float | None = None,
) -> dict[str, float]:
    """件数群の1行。Noneのキーは載せない（「そのキーだけ不明」を表す）。"""
    row = {METRIC_KEY_ACCIDENT: accident, METRIC_KEY_INTERSECTION: intersection}
    return {key: float(value) for key, value in row.items() if value is not None}


def landcover_row(trees: float | None = None, built: float | None = None) -> dict[str, float]:
    row = {METRIC_KEY_TREES_PERCENT: trees, METRIC_KEY_BUILT_PERCENT: built}
    return {key: float(value) for key, value in row.items() if value is not None}


def edge_metrics(
    edge_id: str,
    *,
    accident: float | None = None,
    intersection: float | None = None,
    poi: dict[str, float] | None = None,
    trees: float | None = None,
    built: float | None = None,
    curvature: float | None = None,
) -> Metrics:
    """Edge1本ぶんの`metrics`。値を1つも指定しない群は行自体を持たない
    （「未集計」＝その群由来の材料はすべて欠損、という既存の意味論）。"""
    metrics: Metrics = {}
    counts = counts_row(accident, intersection)
    if counts:
        metrics[METRIC_GROUP_COUNTS] = {edge_id: counts}
    if poi is not None:
        metrics[METRIC_GROUP_POI] = {edge_id: {k: float(v) for k, v in poi.items()}}
    landcover = landcover_row(trees, built)
    if landcover:
        metrics[METRIC_GROUP_LANDCOVER] = {edge_id: landcover}
    if curvature is not None:
        metrics[METRIC_GROUP_GEOMETRY] = {edge_id: {METRIC_KEY_CURVATURE: float(curvature)}}
    return metrics


def merge_metrics(*metrics: Metrics) -> Metrics:
    """複数Edgeぶんの`metrics`を1つへまとめる（群ごとにedge_idを合流させる）。"""
    merged: Metrics = {}
    for one in metrics:
        for group, rows in one.items():
            merged.setdefault(group, {}).update(rows)
    return merged
