"""テストが`EdgeMaterialArrays`（本番が使う材料の形）を組み立てるための足場。

本番は材料をDBに導出させて列で受け取る（`domain/material_sql.py: MATERIAL_VALUE_SQL`）。
DBを持たないテストが同じ形を用意できるよう、ここで組み立てる。

`from_bundles`は`EdgeMaterialBundle`（Python側のextractorが読む形）から変換する。
**extractorが本番経路から外れたら消す**——材料の導出をPythonへ残すための口ではなく、
既存テストの入力の書き方を保ったまま新しい形へ渡すための橋である。
"""

from collections.abc import Mapping

import numpy as np

from app.domain.attributes import EdgeMaterialArrays, EdgeMaterialBundle, ElevationAttribute
from app.domain.graph import RoadGraphLike
from app.domain.hard_filters import HARD_FILTER_HIGHWAY_TYPES, HARD_FILTER_TAG_PREDICATE_SQL
from app.domain.material_catalog import (
    MATERIAL_CATALOG,
    MaterialExtractionContext,
    material_array_group,
    resolve_materials,
)
from app.domain.material_sql import MATERIAL_VALUE_SQL
from app.domain.recipe import tag_value_is


def _grouped_ids() -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    groups: dict[str, list[str]] = {"numeric": [], "boolean": [], "categorical": []}
    for material_id in sorted(MATERIAL_VALUE_SQL):
        groups[material_array_group(MATERIAL_CATALOG[material_id])].append(material_id)
    return tuple(groups["numeric"]), tuple(groups["boolean"]), tuple(groups["categorical"])


def material_arrays_from_bundles(
    graph: RoadGraphLike | None,
    edge_ids: list[str],
    materials: Mapping[str, EdgeMaterialBundle],
    accident_years_covered: int = 1,
) -> EdgeMaterialArrays:
    """`EdgeMaterialBundle`の辞書から`EdgeMaterialArrays`を組み立てる。

    `graph`は`highway`と`distance_m`を読むためだけに使う。Noneなら両方とも既定値
    （highwayなし・距離0）として扱う。
    """
    from app.domain.attributes import edge_metrics_from_bundles

    if graph is None:
        graph = _GraphlessEdges(edge_ids)

    metrics = edge_metrics_from_bundles(materials)
    numeric_ids, boolean_ids, categorical_ids = _grouped_ids()
    n = len(edge_ids)
    resolved: list[dict[str, object]] = []
    no_bicycle = np.zeros(n, dtype=bool)
    for i, edge_id in enumerate(edge_ids):
        bundle = materials.get(edge_id)
        edge = graph.edges[edge_id]
        way_tags = bundle.way_tags if bundle is not None else {}
        if way_tags is not None and tag_value_is(way_tags, "bicycle", "no"):
            no_bicycle[i] = True
        resolved.append(
            resolve_materials(
                MaterialExtractionContext(
                    edge_id=edge_id,
                    highway=edge.highway,
                    way_tags=way_tags,
                    distance_km=edge.distance_m / 1000,
                    elevation_attributes={
                        e: m.elevation_attribute
                        for e, m in materials.items()
                        if m.elevation_attribute is not None
                    },
                    surface_attributes={e: m.surface for e, m in materials.items()},
                    designated_edge_ids={e for e, m in materials.items() if m.is_designated},
                    metrics=metrics,
                    accident_years_covered=accident_years_covered,
                )
            )
        )

    hard_filter_ids = tuple(sorted({*HARD_FILTER_HIGHWAY_TYPES, *HARD_FILTER_TAG_PREDICATE_SQL}))
    hard_filter_flags = np.zeros((n, len(hard_filter_ids)), dtype=bool)
    for i, name in enumerate(hard_filter_ids):
        if name in HARD_FILTER_HIGHWAY_TYPES:
            types = HARD_FILTER_HIGHWAY_TYPES[name]
            hard_filter_flags[:, i] = [graph.edges[e].highway in types for e in edge_ids]
        elif name == "no_bicycle":
            hard_filter_flags[:, i] = no_bicycle

    numeric_values = np.full((n, len(numeric_ids)), np.nan)
    for i, material_id in enumerate(numeric_ids):
        for r, values in enumerate(resolved):
            value = values.get(material_id)
            if value is not None:
                numeric_values[r, i] = float(value)
    boolean_values = np.zeros((n, len(boolean_ids)), dtype=bool)
    for i, material_id in enumerate(boolean_ids):
        for r, values in enumerate(resolved):
            boolean_values[r, i] = bool(values.get(material_id))
    categorical_values = np.empty((n, len(categorical_ids)), dtype=object)
    for i, material_id in enumerate(categorical_ids):
        for r, values in enumerate(resolved):
            categorical_values[r, i] = values.get(material_id)

    def _elevation(pick) -> np.ndarray:
        out = np.full(n, np.nan)
        for r, edge_id in enumerate(edge_ids):
            bundle = materials.get(edge_id)
            attribute = bundle.elevation_attribute if bundle is not None else None
            if attribute is not None:
                value = pick(attribute)
                if value is not None:
                    out[r] = value
        return out

    def _elevation_text(pick) -> list[str | None]:
        out: list[str | None] = []
        for edge_id in edge_ids:
            bundle = materials.get(edge_id)
            attribute = bundle.elevation_attribute if bundle is not None else None
            out.append(None if attribute is None else pick(attribute))
        return out

    return EdgeMaterialArrays(
        edge_ids=list(edge_ids),
        numeric_ids=numeric_ids,
        numeric_values=numeric_values,
        boolean_ids=boolean_ids,
        boolean_values=boolean_values,
        categorical_ids=categorical_ids,
        categorical_values=categorical_values,
        hard_filter_ids=hard_filter_ids,
        hard_filter_flags=hard_filter_flags,
        distance_m=np.array([graph.edges[e].distance_m for e in edge_ids], dtype=float),
        bearing_deg=np.array(
            [
                graph.edges[e].bearing_deg if graph.edges[e].bearing_deg is not None else np.nan
                for e in edge_ids
            ],
            dtype=float,
        ),
        mid_lat=_mid(graph, edge_ids, "latitude"),
        mid_lon=_mid(graph, edge_ids, "longitude"),
        elevation_present=np.array(
            [
                materials.get(edge_id) is not None
                and materials[edge_id].elevation_attribute is not None
                for edge_id in edge_ids
            ],
            dtype=bool,
        ),
        elevation_start_m=_elevation(lambda a: a.start_elevation_m),
        elevation_end_m=_elevation(lambda a: a.end_elevation_m),
        elevation_gain_m=_elevation(lambda a: a.elevation_gain_m),
        elevation_loss_m=_elevation(lambda a: a.elevation_loss_m),
        elevation_max_grade=_elevation(lambda a: a.max_grade),
        elevation_min_grade=_elevation(lambda a: a.min_grade),
        elevation_data_source=_elevation_text(lambda a: a.data_source),
        elevation_data_version=_elevation_text(lambda a: a.data_version),
        elevation_calculated_at=_elevation_text(lambda a: a.calculated_at),
    )


def empty_material_arrays(edge_ids: list[str]) -> EdgeMaterialArrays:
    """材料が1つも分かっていない状態の表（欠損のみ）。"""
    return material_arrays_from_bundles(
        None, edge_ids, {edge_id: _EMPTY_BUNDLE for edge_id in edge_ids}
    )


_EMPTY_BUNDLE = EdgeMaterialBundle(
    surface=None, way_tags={}, attribute_counts=None, elevation_attribute=None, is_designated=False
)


def _mid(graph, edge_ids: list[str], attribute: str) -> np.ndarray:
    nodes = getattr(graph, "nodes", None)
    if not nodes:
        return np.full(len(edge_ids), np.nan)
    out = np.full(len(edge_ids), np.nan)
    for i, edge_id in enumerate(edge_ids):
        edge = graph.edges[edge_id]
        start, end = nodes.get(edge.from_node_id), nodes.get(edge.to_node_id)
        if start is not None and end is not None:
            out[i] = (getattr(start, attribute) + getattr(end, attribute)) / 2
    return out


class _GraphlessEdges:
    """`material_arrays_from_bundles`がhighway/distanceを読むためだけの最小のグラフ。"""

    nodes: dict = {}

    def __init__(self, edge_ids: list[str]) -> None:
        self.edges = {edge_id: _StubEdge() for edge_id in edge_ids}


class _StubEdge:
    highway = None
    distance_m = 0.0
    bearing_deg = None
    from_node_id = ""
    to_node_id = ""


__all__ = [
    "ElevationAttribute",
    "empty_material_arrays",
    "material_arrays_from_bundles",
]
