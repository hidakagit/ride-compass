"""`MaterialExtractionContext.metrics`（群名→edge_id→{キー: 値}）をテストから組み立てる糖衣。

スカラー経路（`compute_edge_cost`/`compute_edge_axis_scores`）とベクトル経路
（`compute_edge_costs_bulk`）は同じ形の`metrics`を受け取るため、パリティテストは
**同じ1つの辞書**を両方へ渡せる（件数をスカラー引数と`metrics`の2通りで作ると、
片方だけ更新して食い違ったまま「一致した」と誤判定しうる）。
"""

from collections.abc import Mapping

from app.domain.attributes import (
    WIRED_LANDCOVER_KEYS,
    METRIC_GROUP_COUNTS,
    METRIC_GROUP_LANDCOVER,
    METRIC_GROUP_POI,
    METRIC_KEY_ACCIDENT,
    METRIC_KEY_INTERSECTION,
)

Metrics = dict[str, dict[str, dict[str, float]]]


def counts_row(
    accident: float | None = None,
    intersection: float | None = None,
) -> dict[str, float]:
    """件数群の1行。Noneのキーは載せない（「そのキーだけ不明」を表す）。"""
    row = {METRIC_KEY_ACCIDENT: accident, METRIC_KEY_INTERSECTION: intersection}
    return {key: float(value) for key, value in row.items() if value is not None}


def landcover_row(percents: Mapping[str, float] | None = None) -> dict[str, float]:
    """土地被覆の1行。クラス名は`WIRED_LANDCOVER_KEYS`。載せないキーは
    「そのクラスだけ不明」を表す。"""
    if not percents:
        return {}
    unknown = set(percents) - set(WIRED_LANDCOVER_KEYS)
    assert not unknown, f"配線されていない土地被覆のクラス: {sorted(unknown)}"
    return {key: float(value) for key, value in percents.items()}


def edge_metrics(
    edge_id: str,
    *,
    accident: float | None = None,
    intersection: float | None = None,
    poi: dict[str, float] | None = None,
    landcover: Mapping[str, float] | None = None,
) -> Metrics:
    """Edge1本ぶんの`metrics`。値を1つも指定しない群は行自体を持たない
    （「未集計」＝その群由来の材料はすべて欠損、という既存の意味論）。"""
    metrics: Metrics = {}
    counts = counts_row(accident, intersection)
    if counts:
        metrics[METRIC_GROUP_COUNTS] = {edge_id: counts}
    if poi is not None:
        metrics[METRIC_GROUP_POI] = {edge_id: {k: float(v) for k, v in poi.items()}}
    landcover_values = landcover_row(landcover)
    if landcover_values:
        metrics[METRIC_GROUP_LANDCOVER] = {edge_id: landcover_values}
    return metrics


def merge_metrics(*metrics: Metrics) -> Metrics:
    """複数Edgeぶんの`metrics`を1つへまとめる（群ごとにedge_idを合流させる）。"""
    merged: Metrics = {}
    for one in metrics:
        for group, rows in one.items():
            merged.setdefault(group, {}).update(rows)
    return merged
