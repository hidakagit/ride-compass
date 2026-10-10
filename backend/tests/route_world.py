"""ルート生成を公開の入口から確かめるテストが共有する、小さな道路網とその渡し口。

3×3の格子（1辺約1km。長さの要るテストには大きな格子・任意の道と地点の道路網も）を`RoadNetwork`で組み、プロセス境界（DB・道路網の置き場・天気の予報ファイル）だけを代役にして、
本物の`GraphService`・エンジンの組み立て（`services/route_generation_setup.py: assemble_route_generation_setup`）・戦略層を通す。

使う側: `test_route_generation_behavior.py`（戦略層の入口）・`test_routes_generate.py`（HTTPの入口）・
`test_routing.py`（生成の経路がPythonから呼ぶJIT）。
"""

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import replace

import numpy as np

from app.services.route_generation_setup import assemble_route_generation_setup
from app.domain.geo import bearing_between, haversine_distance_km
from app.domain.graph import node_key
from app.domain.hard_filters import DEFAULT_HARD_FILTERS, hard_filter_columns
from app.domain.cycling_speed import ROLLING_RESISTANCE_MATERIAL_ID
from app.domain.material_catalog import GRADIENT_PERCENT
from app.domain.road import UNKNOWN_ROAD_SURFACE
from app.domain.traffic import stop_count_material_ids
from app.domain.road_network import RoadNetwork
from app.domain.route import Coordinates
from app.domain.route_preference import RoutePreference
from app.domain.wind import WindForecastSeries
from app.infrastructure import road_network_store
from app.services.graph_service import GraphService
from app.services.weather_service import WeatherService
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


def grid_network(
    *, bad_ways=(), unknown_ways=(), oneway_ways=(), motorway_ways=(), island=False, no_gradient_ways=(), no_stop_count_ways=(),
    stop_density_of=None,
) -> RoadNetwork:
    """3×3の格子。`island`で格子とつながらない道を足す。ほかの引数は`road_network`と同じ。"""
    ways = dict(WAYS)
    if island:
        ways[ISLAND_WAY] = tuple(ISLAND_NODES)
    return road_network(
        ways, {**COORDINATES, **ISLAND_NODES}, bad_ways=bad_ways, unknown_ways=unknown_ways, oneway_ways=oneway_ways,
        motorway_ways=motorway_ways, no_gradient_ways=no_gradient_ways, no_stop_count_ways=no_stop_count_ways,
        stop_density_of=stop_density_of,
    )


def lattice_node(row: int, col: int) -> int:
    """`lattice_network`の格子のノード（行, 列）→ osm_node_id。行は南から北、列は西から東。"""
    return 1000 + row * 100 + col


def lattice_ways(size: int) -> dict[int, tuple[int, int]]:
    """`size`×`size`の格子の道（1本1区間、道→(始点, 終点)）。横の道は西→東、縦の道は南→北。"""
    ways: dict[int, tuple[int, int]] = {}
    for row in range(size):
        for col in range(size):
            if col + 1 < size:
                ways[len(ways) + 1] = (lattice_node(row, col), lattice_node(row, col + 1))
            if row + 1 < size:
                ways[len(ways) + 1] = (lattice_node(row, col), lattice_node(row + 1, col))
    return ways


def lattice_network(size: int, **attributes) -> RoadNetwork:
    """`size`×`size`の格子（1辺約1km、道は`lattice_ways`）。3×3では足りない長さ（経由地を通る周回等）を見るときに使う。
    `attributes`は`road_network`の道の性質（既定はどの道も平らで、避けたい材料を持たない）。"""
    coordinates = {
        lattice_node(row, col): (BASE_LAT + row * LAT_STEP, BASE_LON + col * LON_STEP)
        for row in range(size) for col in range(size)
    }
    return road_network(lattice_ways(size), coordinates, **attributes)


def road_network(
    ways: dict[int, tuple[int, int]], coordinates: dict[int, tuple[float, float]],
    *, bad_ways=(), bad_forward_ways=(), unknown_ways=(), oneway_ways=(), motorway_ways=(), no_gradient_ways=(),
    no_stop_count_ways=(), stop_density_of=None,
) -> RoadNetwork:
    """道（1本1区間、道→(始点, 終点)）とノードの地点（osm_node_id→(緯度, 経度)）から道路網を組む。

    `bad_ways`は避けたい材料が1（それ以外は0）、`bad_forward_ways`は始点→終点の向きだけ避けたい材料が1、
    `unknown_ways`はその材料のデータが無い、`oneway_ways`は始点→終点だけ走れる、`motorway_ways`は高速道路。
    勾配はどの道も平ら（0%）で、`no_gradient_ways`だけ値が無い。停止要因（信号・一時停止等）はどの道にも無い（0件）で、`no_stop_count_ways`だけ件数の値が無い。
    `stop_density_of`（道→1kmあたりの回数）の道だけ、どの種類の停止要因もその密度で持つ。
    路面はどの道も、路面のタグの無い一般の道（取込んだ道の大半がこれ）。"""
    node_ids = np.array(sorted({osm for pair in ways.values() for osm in pair}), dtype=np.int64)
    rows: list[tuple[int, bool, int, int]] = []
    for way, (start, end) in sorted(ways.items()):
        rows.append((way, True, start, end))
        if way not in oneway_ways:
            rows.append((way, False, end, start))
    lat = np.array([coordinates[int(i)][0] for i in node_ids])
    lon = np.array([coordinates[int(i)][1] for i in node_ids])
    row_of = {int(osm): i for i, osm in enumerate(node_ids)}
    tail = np.array([row_of[a] for _w, _f, a, _b in rows], dtype=np.int32)
    head = np.array([row_of[b] for _w, _f, _a, b in rows], dtype=np.int32)
    n = len(rows)
    way_of_row = np.array([w for w, _f, _a, _b in rows], dtype=np.int64)
    forward = np.array([f for _w, f, _a, _b in rows])
    points = [(Coordinates(latitude=lat[a], longitude=lon[a]), Coordinates(latitude=lat[b], longitude=lon[b]))
              for a, b in zip(tail, head, strict=True)]
    hard_filter_ids = hard_filter_columns()
    flags = np.zeros((n, len(hard_filter_ids)), dtype=bool)
    if "motorway" in hard_filter_ids:
        flags[:, hard_filter_ids.index("motorway")] = np.isin(way_of_row, list(motorway_ways))
    nan = np.full(n, np.nan)
    bad = (np.isin(way_of_row, list(bad_ways)) | (np.isin(way_of_row, list(bad_forward_ways)) & forward)).astype(float)
    bad[np.isin(way_of_row, list(unknown_ways))] = np.nan
    gradient = np.where(np.isin(way_of_row, list(no_gradient_ways)), np.nan, 0.0)
    stop_count = np.where(np.isin(way_of_row, list(no_stop_count_ways)), np.nan, 0.0)
    for way, density in (stop_density_of or {}).items():
        stop_count[way_of_row == way] = density
    return RoadNetwork(
        revision=1,
        node_osm_id=node_ids, node_lat=lat, node_lon=lon,
        node_has_signals=np.zeros(len(node_ids), dtype=bool), node_max_rank=np.zeros(len(node_ids), dtype=np.int64),
        edge_way_id=way_of_row, edge_segment=np.zeros(n, dtype=np.int32),
        edge_forward=forward,
        edge_from=tail, edge_to=head,
        edge_highway=np.zeros(n, dtype=np.int16), highway_vocab=("residential",),
        edge_min_lon=np.minimum(lon[tail], lon[head]), edge_min_lat=np.minimum(lat[tail], lat[head]),
        edge_max_lon=np.maximum(lon[tail], lon[head]), edge_max_lat=np.maximum(lat[tail], lat[head]),
        numeric_ids=(BAD_MATERIAL, GRADIENT_PERCENT, *stop_count_material_ids()),
        numeric_values=np.column_stack([bad, gradient, *(stop_count for _ in stop_count_material_ids())]),
        categorical_ids=(ROLLING_RESISTANCE_MATERIAL_ID,), categorical_codes=np.ones((n, 1), dtype=np.int16),
        categorical_vocab=((None, UNKNOWN_ROAD_SURFACE.key),),
        hard_filter_ids=hard_filter_ids, hard_filter_flags=flags,
        distance_m=np.array([haversine_distance_km(a, b) * 1000 for a, b in points]),
        bearing_deg=np.array([bearing_between(a, b) for a, b in points]),
        mid_lat=(lat[tail] + lat[head]) / 2, mid_lon=(lon[tail] + lon[head]) / 2,
        elevation_present=np.zeros(n, dtype=bool),
        elevation_gain_m=nan, elevation_loss_m=nan,
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
    """天気の代役。出発時点の風は無く、時別の風の予報は`series`（Noneなら無し）を返す。雨の観測は本物の
    `WeatherService`から読む（Redisの履歴。`tests/rain_history_fake.py: observe`で作る）。"""

    def __init__(self, series: WindForecastSeries | None = None):
        self._series = series
        self._rain = WeatherService()

    async def get_departure_wind(self, origin):
        return None

    async def get_wind_forecast_lattice(self, bbox):
        return self._series

    async def get_station_rain_materials(self, now):
        return await self._rain.get_station_rain_materials(now)


def serve_road_network(monkeypatch, current: Callable[[], RoadNetwork]) -> None:
    """道路網全体の配列を置き場から読まず、`current`が返すものとして読ませる（`road_network_store.current`の差し替え）。"""
    monkeypatch.setattr(road_network_store, "current", current)


def generator_for(monkeypatch, network: RoadNetwork, avoid_weight: float, wind: WindForecastSeries | None):
    """道路網を全体の配列として読ませ、本物の`GraphService`とエンジンの上に戦略層（`RouteGenerator`）を組む。"""
    serve_road_network(monkeypatch, lambda: network)
    return assemble_route_generation_setup(
        GraphService(NetworkRepository(network)), Weather(wind),
        preference_override=RoutePreference(weights={AVOID_AXIS: avoid_weight}),
        penalty_strength=1.0, max_average_grade_percent=None, hard_filters=DEFAULT_HARD_FILTERS,
        assumed_speed_kmh=20.0,
    ).generator


@contextmanager
def avoid_axis_declared():
    """避けたい材料が1の区間ほど難しいと評価する公開軸を1本だけ宣言する。"""
    with replaced_axis_definitions({AVOID_AXIS: axis_definition(AVOID_AXIS, material=BAD_MATERIAL, is_published=True)}):
        yield


def at(osm_node_id: int) -> Coordinates:
    lat, lon = _coordinates(osm_node_id)
    return Coordinates(latitude=lat, longitude=lon)


def node_point(network: RoadNetwork, osm_node_id: int) -> Coordinates:
    """道路網`network`のノードの地点（`grid_network`以外の道路網の`at`）。"""
    (row,) = np.flatnonzero(network.node_osm_id == osm_node_id)
    return Coordinates(latitude=float(network.node_lat[row]), longitude=float(network.node_lon[row]))


def ways_of(candidate) -> list[int]:
    return [int(edge_id.split("-")[1]) for edge_id in candidate.edge_ids]
