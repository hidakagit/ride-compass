"""ルート生成を公開の入口から確かめるテストが共有する、小さな道路網とその渡し口。

3×3の格子（1辺約1km）を`RoadNetwork`で組み、プロセス境界（DB・道路網の置き場・天気の予報ファイル）だけを代役にして、
本物の`GraphService`・エンジン・戦略層を通す。エンジンの入口の形が変わったら、ここ（`engine_for`）だけを直す。

使う側: `test_route_generation_behavior.py`（戦略層の入口）・`test_routes_generate.py`（HTTPの入口）。
"""

from contextlib import contextmanager
from dataclasses import replace

import numpy as np

from app.domain.geo import bearing_between, haversine_distance_km
from app.domain.graph import node_key
from app.domain.hard_filters import hard_filter_columns
from app.domain.road_network import RoadNetwork
from app.domain.route import Coordinates
from app.domain.route_preference import RoutePreference
from app.domain.wind import WindForecastSeries
from app.infrastructure import road_network_store
from app.services.graph_service import GraphService
from app.services.road_graph_engine import RoadGraphEngine
from tests.axis_system_fixture import axis_definition, replaced_axis_definitions

AVOID_AXIS = "avoid"
BAD_MATERIAL = "m_bad"
BASE_LAT, BASE_LON = 35.60, 139.60
LAT_STEP, LON_STEP = 0.009, 0.011  # 緯度・経度とも約1km

#: 格子のノード（行, 列）→ osm_node_id。行は南から北、列は西から東。
NODE_OF = {(row, col): 10 + row * 3 + col for row in range(3) for col in range(3)}
#: 道（1本1区間）→ (始点, 終点)。横の道は西→東、縦の道は南→北。
WAYS = {
    **{100 + row * 2 + col: (NODE_OF[row, col], NODE_OF[row, col + 1]) for row in range(3) for col in range(2)},
    **{200 + row * 3 + col: (NODE_OF[row, col], NODE_OF[row + 1, col]) for row in range(2) for col in range(3)},
}
SOUTH_WEST, NORTH_EAST, CENTER = NODE_OF[0, 0], NODE_OF[2, 2], NODE_OF[1, 1]
SOUTH_EAST, NORTH_WEST = NODE_OF[0, 2], NODE_OF[2, 0]
COORDINATES = {
    osm: (BASE_LAT + row * LAT_STEP, BASE_LON + col * LON_STEP) for (row, col), osm in NODE_OF.items()
}
#: 北東の角のすぐ東にある、格子とつながらない短い道（2ノード）。孤立した小塊の代わり。
ISLAND_NODES = {90: (COORDINATES[NORTH_EAST][0], COORDINATES[NORTH_EAST][1] + 0.004),
                91: (COORDINATES[NORTH_EAST][0], COORDINATES[NORTH_EAST][1] + 0.008)}
ISLAND_WAY = 300


def _coordinates(osm_node_id: int) -> tuple[float, float]:
    return {**COORDINATES, **ISLAND_NODES}[osm_node_id]


def grid_network(*, bad_ways=(), unknown_ways=(), oneway_ways=(), motorway_ways=(), island=False) -> RoadNetwork:
    """3×3の格子。`bad_ways`は避けたい材料が1（それ以外は0）、`unknown_ways`はその材料のデータが無い、
    `oneway_ways`は始点→終点だけ走れる、`motorway_ways`は高速道路。`island`で格子とつながらない道を足す。"""
    ways = dict(WAYS)
    if island:
        ways[ISLAND_WAY] = tuple(ISLAND_NODES)
    node_ids = np.array(sorted({osm for pair in ways.values() for osm in pair}), dtype=np.int64)
    rows: list[tuple[int, bool, int, int]] = []
    for way, (start, end) in sorted(ways.items()):
        rows.append((way, True, start, end))
        if way not in oneway_ways:
            rows.append((way, False, end, start))
    lat = np.array([_coordinates(i)[0] for i in node_ids])
    lon = np.array([_coordinates(i)[1] for i in node_ids])
    row_of = {int(osm): i for i, osm in enumerate(node_ids)}
    tail = np.array([row_of[a] for _w, _f, a, _b in rows], dtype=np.int32)
    head = np.array([row_of[b] for _w, _f, _a, b in rows], dtype=np.int32)
    n = len(rows)
    ways = np.array([w for w, _f, _a, _b in rows], dtype=np.int64)
    points = [(Coordinates(latitude=lat[a], longitude=lon[a]), Coordinates(latitude=lat[b], longitude=lon[b]))
              for a, b in zip(tail, head, strict=True)]
    hard_filter_ids = hard_filter_columns()
    flags = np.zeros((n, len(hard_filter_ids)), dtype=bool)
    if "motorway" in hard_filter_ids:
        flags[:, hard_filter_ids.index("motorway")] = np.isin(ways, list(motorway_ways))
    nan = np.full(n, np.nan)
    bad = np.isin(ways, list(bad_ways)).astype(float)
    bad[np.isin(ways, list(unknown_ways))] = np.nan
    return RoadNetwork(
        revision=1,
        node_osm_id=node_ids, node_lat=lat, node_lon=lon,
        node_has_signals=np.zeros(len(node_ids), dtype=bool), node_max_rank=np.zeros(len(node_ids), dtype=np.int64),
        edge_way_id=ways, edge_segment=np.zeros(n, dtype=np.int32),
        edge_forward=np.array([f for _w, f, _a, _b in rows]),
        edge_from=tail, edge_to=head,
        edge_highway=np.ones(n, dtype=np.int16), highway_vocab=(None, "residential"),
        edge_min_lon=np.minimum(lon[tail], lon[head]), edge_min_lat=np.minimum(lat[tail], lat[head]),
        edge_max_lon=np.maximum(lon[tail], lon[head]), edge_max_lat=np.maximum(lat[tail], lat[head]),
        numeric_ids=(BAD_MATERIAL,),
        numeric_values=bad.reshape(-1, 1),
        boolean_ids=(), boolean_values=np.zeros((n, 0), dtype=bool),
        categorical_ids=(), categorical_codes=np.zeros((n, 0), dtype=np.int16), categorical_vocab=(),
        hard_filter_ids=hard_filter_ids, hard_filter_flags=flags,
        distance_m=np.array([haversine_distance_km(a, b) * 1000 for a, b in points]),
        bearing_deg=np.array([bearing_between(a, b) for a, b in points]),
        mid_lat=(lat[tail] + lat[head]) / 2, mid_lon=(lon[tail] + lon[head]) / 2,
        elevation_present=np.zeros(n, dtype=bool),
        elevation_start_m=nan, elevation_end_m=nan, elevation_gain_m=nan, elevation_loss_m=nan,
        elevation_max_grade=nan, elevation_min_grade=nan,
    )


# --- 道路網をエンジンへ渡す道具（エンジンの入口の形が変わったら、ここだけを直す） ---


class NetworkRepository:
    """DBの代役。道路網はどこでも取込範囲の中で、区間の形は両端のノードを結ぶ直線。"""

    def __init__(self, network: RoadNetwork):
        self._coordinates = {
            node_key(int(osm)): [float(lat), float(lon)]
            for osm, lat, lon in zip(network.node_osm_id, network.node_lat, network.node_lon, strict=True)
        }

    async def is_covered(self, bbox):
        return True

    async def get_edges_with_geometry(self, edges):
        return {
            edge.edge_id: replace(edge, geometry=[self._coordinates[edge.from_node_id], self._coordinates[edge.to_node_id]])
            for edge in edges
        }


class Weather:
    """天気の代役。出発時点の風は無く、時別の風の予報は`series`（Noneなら無し）を返す。"""

    def __init__(self, series: WindForecastSeries | None = None):
        self._series = series

    async def get_conditions(self, origin):
        return None

    async def get_wind_forecast_lattice(self, bbox):
        return self._series


def engine_for(monkeypatch, network: RoadNetwork, avoid_weight: float, wind: WindForecastSeries | None):
    """道路網を全体の配列として読ませ、本物の`GraphService`とエンジンを組む。"""
    monkeypatch.setattr(road_network_store, "current", lambda: network)
    return RoadGraphEngine(
        GraphService(NetworkRepository(network)), Weather(wind),
        RoutePreference(weights={AVOID_AXIS: avoid_weight}),
        penalty_strength=1.0, assumed_speed_kmh=20.0,
    )


@contextmanager
def avoid_axis_declared():
    """避けたい材料が1の区間ほど難しいと評価する公開軸を1本だけ宣言する。"""
    with replaced_axis_definitions({AVOID_AXIS: axis_definition(AVOID_AXIS, material=BAD_MATERIAL, is_published=True)}):
        yield


def at(osm_node_id: int) -> Coordinates:
    lat, lon = _coordinates(osm_node_id)
    return Coordinates(latitude=lat, longitude=lon)


def ways_of(candidate) -> list[int]:
    return [int(edge_id.split("-")[1]) for edge_id in candidate.edge_ids]
