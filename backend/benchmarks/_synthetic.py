"""ベンチマーク間で共有する合成道路網ジェネレータ。

DB接続無しでノード数・エッジ数を狙った規模へスケールさせるため、rows x cols の格子状の
道路網（碁盤目の街区を模したもの）を生成する。隣接する格子点の間を1区間とし、全ノードが
そのまま交差点になる（rows*cols ノード）。

取込・派生を通したときと同じ形（向きごとに1本の`LeanEdge`）で組む——探索フェーズが読むのは
この形だけで、DBから来たグラフと区別がつかないようにする。
"""

from __future__ import annotations

from app.domain.geo import LatLonPoint, bearing_between, haversine_distance_km
from app.domain.graph import LeanEdge, LeanNode, LeanRoadGraph
from app.domain.route import Coordinates
from app.infrastructure.road_graph_repository import edge_key, node_key

TOKYO_LAT = 35.7
TOKYO_LON = 139.7
GRID_SPACING_DEG = 0.001  # 概ね110m四方の街区


def make_grid_graph(rows: int, cols: int) -> LeanRoadGraph:
    coords: dict[int, tuple[float, float]] = {}
    for r in range(rows):
        for c in range(cols):
            coords[r * cols + c] = (TOKYO_LAT + r * GRID_SPACING_DEG, TOKYO_LON + c * GRID_SPACING_DEG)

    nodes = {
        node_key(osm_node_id): LeanNode(
            node_id=node_key(osm_node_id), latitude=lat, longitude=lon, osm_node_id=osm_node_id)
        for osm_node_id, (lat, lon) in coords.items()
    }

    pairs: list[tuple[int, int]] = []
    for r in range(rows):
        for c in range(cols - 1):
            pairs.append((r * cols + c, r * cols + c + 1))
    for c in range(cols):
        for r in range(rows - 1):
            pairs.append((r * cols + c, (r + 1) * cols + c))

    edges: dict[str, LeanEdge] = {}
    for way_id, (a, b) in enumerate(pairs):
        start, end = LatLonPoint(*coords[a]), LatLonPoint(*coords[b])
        distance_m = haversine_distance_km(start, end) * 1000
        for forward in (True, False):
            tail, head = (a, b) if forward else (b, a)
            key = edge_key(way_id, 0, forward)
            edges[key] = LeanEdge(
                edge_id=key, from_node_id=node_key(tail), to_node_id=node_key(head),
                geometry=[], distance_m=distance_m, osm_way_id=way_id, segment_index=0,
                forward=forward, highway="residential",
                bearing_deg=bearing_between(start, end) if forward else bearing_between(end, start),
            )

    return LeanRoadGraph(graph_version="synthetic", nodes=nodes, edges=edges)


def grid_point(rows: int, cols: int, row_fraction: float = 0.5, col_fraction: float = 0.5) -> Coordinates:
    """格子の内部（既定は中央）に相当する緯度経度を返す（find_nearest_node等の探索対象）。"""
    return Coordinates(
        latitude=TOKYO_LAT + rows * row_fraction * GRID_SPACING_DEG,
        longitude=TOKYO_LON + cols * col_fraction * GRID_SPACING_DEG,
    )
