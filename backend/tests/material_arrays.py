"""テストが`EdgeMaterialArrays`（本番が使う材料の形）を組み立てるための入力。

本番は材料をDBに導出させて列で受け取る（`MaterialSpec.value_sql`）。DBを持たないテストは
**導出済みの材料値**をここへ渡す——タグから材料をどう導くかはSQLの仕事で、
`tests/test_material_sql.py`が別に検証する。ここで再現すると導出が2組になる。

`materials`は区間id→(材料id→値)。渡さなかった材料は欠損（数値はNaN、分類はNone、
真偽はFalse）で、これはway_tagsに該当タグが無いときにSQLが返す値と同じ意味を持つ。
"""

from collections.abc import Collection, Mapping

import numpy as np

from app.domain.attributes import EdgeMaterialArrays, ElevationAttribute
from app.domain.graph import RoadGraphLike
from app.domain.hard_filters import HARD_FILTER_HIGHWAY_TYPES, hard_filter_columns
from app.domain.material_catalog import material_array_columns


def material_arrays(
    graph: RoadGraphLike | None,
    edge_ids: list[str],
    materials: Mapping[str, Mapping[str, object]] | None = None,
    *,
    elevation: Mapping[str, ElevationAttribute] | None = None,
    no_bicycle_edge_ids: Collection[str] = (),
) -> EdgeMaterialArrays:
    """導出済みの材料値から`EdgeMaterialArrays`を組み立てる。

    `graph`は区間の行そのものが持つ値（`highway`・距離・方位・中点）を読むために使い、
    Noneならそれらを既定値として扱う。`highway`材料と、`elevation`を渡した区間の
    `gradient_percent`はここから埋める——SQLも同じ行から読む（`re.highway`・
    `e.average_grade`）。明示的に`materials`で渡した値が優先される。
    """
    materials = materials or {}
    elevation = elevation or {}
    numeric_ids, boolean_ids, categorical_ids = material_array_columns()
    n = len(edge_ids)

    def _values(edge_id: str) -> dict[str, object]:
        row = dict(materials.get(edge_id) or {})
        # 区間そのものが持つ値はSQLも区間の行から読む（`highway`は`re.highway`、
        # `gradient_percent`は`e.average_grade`）。明示的に渡した値が優先される。
        if "highway" not in row:
            row["highway"] = _highway(graph, edge_id)
        attribute = elevation.get(edge_id)
        if attribute is not None and "gradient_percent" not in row:
            row["gradient_percent"] = attribute.average_grade
        return row

    rows = [_values(edge_id) for edge_id in edge_ids]

    numeric_values = np.full((n, len(numeric_ids)), np.nan)
    for column, material_id in enumerate(numeric_ids):
        for row_index, row in enumerate(rows):
            value = row.get(material_id)
            if value is not None:
                numeric_values[row_index, column] = float(value)
    boolean_values = np.zeros((n, len(boolean_ids)), dtype=bool)
    for column, material_id in enumerate(boolean_ids):
        for row_index, row in enumerate(rows):
            boolean_values[row_index, column] = bool(row.get(material_id))
    categorical_values = np.empty((n, len(categorical_ids)), dtype=object)
    for column, material_id in enumerate(categorical_ids):
        for row_index, row in enumerate(rows):
            categorical_values[row_index, column] = row.get(material_id)

    hard_filter_ids = hard_filter_columns()
    hard_filter_flags = np.zeros((n, len(hard_filter_ids)), dtype=bool)
    no_bicycle = set(no_bicycle_edge_ids)
    for column, name in enumerate(hard_filter_ids):
        if name in HARD_FILTER_HIGHWAY_TYPES:
            types = HARD_FILTER_HIGHWAY_TYPES[name]
            hard_filter_flags[:, column] = [_highway(graph, e) in types for e in edge_ids]
        elif name == "no_bicycle":
            hard_filter_flags[:, column] = [e in no_bicycle for e in edge_ids]

    def _elevation(pick) -> np.ndarray:
        out = np.full(n, np.nan)
        for row_index, edge_id in enumerate(edge_ids):
            attribute = elevation.get(edge_id)
            if attribute is not None and pick(attribute) is not None:
                out[row_index] = pick(attribute)
        return out

    def _elevation_text(pick) -> list[str | None]:
        return [
            None if elevation.get(edge_id) is None else pick(elevation[edge_id])
            for edge_id in edge_ids
        ]

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
        distance_m=np.array([_edge_value(graph, e, "distance_m", 0.0) for e in edge_ids], float),
        bearing_deg=np.array(
            [_edge_value(graph, e, "bearing_deg", np.nan) for e in edge_ids], float
        ),
        mid_lat=_mid(graph, edge_ids, "latitude"),
        mid_lon=_mid(graph, edge_ids, "longitude"),
        elevation_present=np.array([e in elevation for e in edge_ids], dtype=bool),
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


def _highway(graph: RoadGraphLike | None, edge_id: str) -> str | None:
    return _edge_value(graph, edge_id, "highway", None)


def _edge_value(graph: RoadGraphLike | None, edge_id: str, attribute: str, default):
    edge = None if graph is None else graph.edges.get(edge_id)
    value = default if edge is None else getattr(edge, attribute, default)
    return default if value is None else value


def _mid(graph: RoadGraphLike | None, edge_ids: list[str], attribute: str) -> np.ndarray:
    nodes = getattr(graph, "nodes", None) if graph is not None else None
    out = np.full(len(edge_ids), np.nan)
    if not nodes:
        return out
    for index, edge_id in enumerate(edge_ids):
        edge = graph.edges.get(edge_id)
        if edge is None:
            continue
        start, end = nodes.get(edge.from_node_id), nodes.get(edge.to_node_id)
        if start is not None and end is not None:
            out[index] = (getattr(start, attribute) + getattr(end, attribute)) / 2
    return out


__all__ = ["ElevationAttribute", "material_arrays"]
