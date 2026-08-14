"""ベンチマーク間で共有する合成道路網ジェネレータ。

実際のOverpass/PostGIS接続無しでノード数・エッジ数をベンチマークごとに狙った規模へ
スケールさせるため、rows x cols の格子状の道路網（碁盤目の街区を模したもの）を生成する。
各Wayは隣接ノード2点のみで構成するため、`build_road_graph`の交差点分割ロジック上、
全ノードがそのまま交差点（Node）になる（rows*cols ノード = rows*cols グラフNode）。
"""

from __future__ import annotations

from app.domain.graph import RoadGraph, WaySpec, build_road_graph
from app.domain.route import Coordinates

TOKYO_LAT = 35.7
TOKYO_LON = 139.7
GRID_SPACING_DEG = 0.001  # 概ね110m四方の街区


def make_grid_way_specs(rows: int, cols: int) -> tuple[list[WaySpec], dict[int, tuple[float, float]]]:
    node_coords: dict[int, tuple[float, float]] = {}
    for r in range(rows):
        for c in range(cols):
            node_id = r * cols + c
            node_coords[node_id] = (TOKYO_LAT + r * GRID_SPACING_DEG, TOKYO_LON + c * GRID_SPACING_DEG)

    ways: list[WaySpec] = []
    way_id = 0
    for r in range(rows):
        for c in range(cols - 1):
            a, b = r * cols + c, r * cols + c + 1
            ways.append(WaySpec(osm_way_id=way_id, node_ids=[a, b], highway="residential"))
            way_id += 1
    for c in range(cols):
        for r in range(rows - 1):
            a, b = r * cols + c, (r + 1) * cols + c
            ways.append(WaySpec(osm_way_id=way_id, node_ids=[a, b], highway="residential"))
            way_id += 1

    return ways, node_coords


def make_grid_graph(rows: int, cols: int) -> RoadGraph:
    ways, node_coords = make_grid_way_specs(rows, cols)
    return build_road_graph(ways, node_coords)


def grid_point(rows: int, cols: int, row_fraction: float = 0.5, col_fraction: float = 0.5) -> Coordinates:
    """格子の内部（既定は中央）に相当する緯度経度を返す（find_nearest_node等の探索対象）。"""
    return Coordinates(
        latitude=TOKYO_LAT + rows * row_fraction * GRID_SPACING_DEG,
        longitude=TOKYO_LON + cols * col_fraction * GRID_SPACING_DEG,
    )


def synthetic_road_surface_ways(count: int, points_per_way: int = 12) -> list[dict]:
    """RegionService/encode_road_surface_tileが受け取る形の合成way一覧を生成する。
    座標はタイルz=14あたりの1タイル分の範囲に収まる程度の広がりにする。
    """
    ways = []
    for i in range(count):
        base_lat = TOKYO_LAT + (i % 50) * 0.0005
        base_lon = TOKYO_LON + (i // 50) * 0.0005
        coordinates = [[base_lat + j * 0.00003, base_lon + j * 0.00002] for j in range(points_per_way)]
        ways.append({"coordinates": coordinates, "surface_good": (i % 3 != 0)})
    return ways
