"""ルート生成の振る舞いを、公開の入口（`RouteGenerator`）だけから確かめる。

小さな道路網（3×3の格子、1辺約1km）を`RoadNetwork`で組み、生成の結果（`RouteCandidate`）の性質を見る。
探索の途中状態・キャッシュ・内部の関数には触らない——道路網の持ち方やエンジンの組み立てを作り替えても、
同じ道路網と設定から同じ性質の経路が出ることを、このファイルが通り続けることで示す。

ここで見ないもの:
- 探索アルゴリズムそのもの（ダイクストラ・A*・ターンの費用） → `test_routing.py`
- 候補の並べ方・理由の文面（戦略層） → `test_route_generator.py`
- 材料の値の求め方 → `test_material_values.py`

道路網をエンジンへ渡す道具は`engine_over`の1つだけに置く。エンジンの入口の形が変わったら、ここだけを直す。
"""

import itertools
import math

import numpy as np
import pytest

from app.domain.attributes import EdgeMaterialArrays, SearchMaterials
from app.domain.evaluation import build_static_edge_score_matrix
from app.domain.geo import bearing_between, haversine_distance_km
from app.domain.graph import LeanEdge, LeanNode, LeanRoadGraph
from app.domain.hard_filters import hard_filter_columns
from app.domain.road_network import RoadNetwork
from app.domain.route import Coordinates
from app.domain.route_preference import RoutePreference
from app.infrastructure.road_graph_repository import edge_key, node_key
from app.services.road_graph_engine import RoadGraphEngine
from app.services.route_generator import RouteGenerator
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


def _coordinates(osm_node_id: int) -> tuple[float, float]:
    row, col = next(key for key, value in NODE_OF.items() if value == osm_node_id)
    return BASE_LAT + row * LAT_STEP, BASE_LON + col * LON_STEP


def grid_network(*, bad_ways=(), oneway_ways=(), motorway_ways=()) -> RoadNetwork:
    """3×3の格子。`bad_ways`は避けたい材料が1、`oneway_ways`は始点→終点だけ走れる、`motorway_ways`は高速道路。"""
    node_ids = np.array(sorted(NODE_OF.values()), dtype=np.int64)
    rows: list[tuple[int, bool, int, int]] = []
    for way, (start, end) in sorted(WAYS.items()):
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
        numeric_values=np.isin(ways, list(bad_ways)).astype(float).reshape(-1, 1),
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

_TILE_KEYS = itertools.count()


class _NetworkGraphService:
    """道路網の全体を、どの範囲を聞かれても返す`GraphService`の代役。"""

    def __init__(self, network: RoadNetwork):
        osm = network.node_osm_id
        nodes = {
            node_key(int(osm[i])): LeanNode(node_id=node_key(int(osm[i])), latitude=float(network.node_lat[i]),
                                            longitude=float(network.node_lon[i]), osm_node_id=int(osm[i]))
            for i in range(network.node_count)
        }
        edges = {}
        for i in range(network.edge_count):
            key = edge_key(int(network.edge_way_id[i]), int(network.edge_segment[i]), bool(network.edge_forward[i]))
            edges[key] = LeanEdge(
                edge_id=key, from_node_id=node_key(int(osm[network.edge_from[i]])),
                to_node_id=node_key(int(osm[network.edge_to[i]])), geometry=[],
                distance_m=float(network.distance_m[i]), osm_way_id=int(network.edge_way_id[i]),
                segment_index=int(network.edge_segment[i]), forward=bool(network.edge_forward[i]),
                highway=network.highway_vocab[network.edge_highway[i]], bearing_deg=float(network.bearing_deg[i]),
            )
        self._nodes = nodes
        materials = EdgeMaterialArrays(
            edge_ids=list(edges),
            numeric_ids=network.numeric_ids, numeric_values=np.asarray(network.numeric_values),
            boolean_ids=network.boolean_ids, boolean_values=np.asarray(network.boolean_values),
            categorical_ids=network.categorical_ids,
            categorical_values=np.zeros((network.edge_count, 0), dtype=object),
            hard_filter_ids=network.hard_filter_ids, hard_filter_flags=np.asarray(network.hard_filter_flags),
            distance_m=network.distance_m, bearing_deg=network.bearing_deg,
            mid_lat=network.mid_lat, mid_lon=network.mid_lon, elevation_present=network.elevation_present,
            elevation_start_m=network.elevation_start_m, elevation_end_m=network.elevation_end_m,
            elevation_gain_m=network.elevation_gain_m, elevation_loss_m=network.elevation_loss_m,
            elevation_max_grade=network.elevation_max_grade, elevation_min_grade=network.elevation_min_grade,
        )
        self._built = (
            SearchMaterials(graph=LeanRoadGraph(graph_version="test", nodes=nodes, edges=edges), materials=materials),
            build_static_edge_score_matrix(materials),
            frozenset({(12, next(_TILE_KEYS), 0)}),
        )

    async def get_search_materials_for_bbox(self, bbox):
        return self._built

    async def get_accident_years_covered(self):
        return 1

    async def get_edges_with_geometry(self, edges):
        return {
            edge.edge_id: LeanEdge(
                edge_id=edge.edge_id, from_node_id=edge.from_node_id, to_node_id=edge.to_node_id,
                geometry=[[self._nodes[edge.from_node_id].latitude, self._nodes[edge.from_node_id].longitude],
                          [self._nodes[edge.to_node_id].latitude, self._nodes[edge.to_node_id].longitude]],
                distance_m=edge.distance_m, osm_way_id=edge.osm_way_id, segment_index=edge.segment_index,
                forward=edge.forward, highway=edge.highway, bearing_deg=edge.bearing_deg,
            )
            for edge in edges
        }


class _NoWeather:
    async def get_conditions(self, origin):
        return None

    async def get_wind_forecast_lattice(self, bbox):
        return None


def engine_over(network: RoadNetwork, *, avoid_weight: float = 0.0) -> RouteGenerator:
    engine = RoadGraphEngine(
        _NetworkGraphService(network), _NoWeather(), RoutePreference(weights={AVOID_AXIS: avoid_weight}),
        penalty_strength=1.0, assumed_speed_kmh=20.0,
    )
    return RouteGenerator(engine)


# ---------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _avoid_axis():
    """避けたい材料が1の区間ほど難しいと評価する公開軸を1本だけ宣言する。"""
    with replaced_axis_definitions({AVOID_AXIS: axis_definition(AVOID_AXIS, material=BAD_MATERIAL, is_published=True)}):
        yield


def at(osm_node_id: int) -> Coordinates:
    lat, lon = _coordinates(osm_node_id)
    return Coordinates(latitude=lat, longitude=lon)


def ways_of(candidate) -> list[int]:
    return [int(edge_id.split("-")[1]) for edge_id in candidate.edge_ids]


def assert_connected(candidate, start: int, end: int) -> None:
    """経路が`start`から始まり`end`で終わり、区間どうしが途切れずにつながる。"""
    assert candidate.node_ids[0] == node_key(start)
    assert candidate.node_ids[-1] == node_key(end)
    assert len(candidate.node_ids) == len(candidate.edge_ids) + 1
    lengths = [haversine_distance_km(at(int(a.split("-")[-1])), at(int(b.split("-")[-1])))
               for a, b in zip(candidate.node_ids, candidate.node_ids[1:])]
    assert all(length > 0 for length in lengths)
    assert math.isclose(sum(lengths), candidate.distance_km, abs_tol=0.02)


async def test_destination_route_runs_from_origin_to_destination():
    generator = engine_over(grid_network())

    candidates = await generator.generate_via_waypoints(at(SOUTH_WEST), [], 4.0, destination=at(NORTH_EAST), max_routes=3)

    assert candidates
    for candidate in candidates:
        assert_connected(candidate, SOUTH_WEST, NORTH_EAST)
    # 格子の対角は最短で4区間（約4km）。基準線（時間最短）はそれより遠回りしない。
    fastest = next(c for c in candidates if c.is_fastest)
    assert len(fastest.edge_ids) == 4


async def test_weight_on_an_axis_steers_the_route_away_from_what_it_scores_badly():
    """南の道と東の道（南西→南東→北東）だけが避けたい材料を持つ。重みを掛けると、最も易しい候補はそこを通らない。"""
    bad = {100, 101, 202, 205}  # 南の横の道2本と東の縦の道2本
    generator = engine_over(grid_network(bad_ways=bad), avoid_weight=1.0)

    candidates = await generator.generate_via_waypoints(at(SOUTH_WEST), [], 4.0, destination=at(NORTH_EAST), max_routes=3)

    easiest = min((c for c in candidates if not c.is_fastest), key=lambda c: c.overall_difficulty,
                  default=candidates[0])
    assert_connected(easiest, SOUTH_WEST, NORTH_EAST)
    assert not set(ways_of(easiest)) & bad


async def test_oneway_road_is_never_driven_against_its_direction():
    """中央の縦の道（南→北だけ走れる）を、北→南の目的地ルートで逆走しない。"""
    oneway = {201, 204}
    generator = engine_over(grid_network(oneway_ways=oneway))

    candidates = await generator.generate_via_waypoints(
        at(NODE_OF[2, 1]), [], 3.0, destination=at(NODE_OF[0, 1]), max_routes=3)

    assert candidates
    for candidate in candidates:
        assert_connected(candidate, NODE_OF[2, 1], NODE_OF[0, 1])
        assert not [e for e in candidate.edge_ids if int(e.split("-")[1]) in oneway and e.endswith("bwd")]


async def test_motorway_is_never_used_even_when_it_is_the_short_way():
    motorway = {100, 101}  # 南の横の道
    generator = engine_over(grid_network(motorway_ways=motorway))

    candidates = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], 3.0, destination=at(NODE_OF[0, 2]), max_routes=3)

    assert candidates
    for candidate in candidates:
        assert_connected(candidate, SOUTH_WEST, NODE_OF[0, 2])
        assert not set(ways_of(candidate)) & motorway


async def test_loop_returns_to_its_origin_within_the_distance_tolerance():
    generator = engine_over(grid_network())

    candidates = await generator.generate_loops(at(CENTER), 4.0, 1.5, max_routes=3)

    assert candidates
    for candidate in candidates:
        assert_connected(candidate, CENTER, CENTER)
        assert abs(candidate.distance_km - 4.0) <= 1.5


async def test_segments_cover_the_whole_route():
    generator = engine_over(grid_network())

    (candidate, *_) = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], 4.0, destination=at(NORTH_EAST), max_routes=1)

    assert math.isclose(sum(s.distance_km for s in candidate.segments), candidate.distance_km, abs_tol=0.02)
    assert candidate.estimated_duration_seconds is not None and candidate.estimated_duration_seconds > 0


async def test_spliced_route_is_evaluated_as_sent_and_a_broken_one_is_refused():
    generator = engine_over(grid_network())
    (candidate, *_) = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], 4.0, destination=at(NORTH_EAST), max_routes=1)

    spliced = await generator.generate_spliced_route(at(SOUTH_WEST), at(NORTH_EAST), 4.0, candidate.edge_ids)
    broken = await generator.generate_spliced_route(
        at(SOUTH_WEST), at(NORTH_EAST), 4.0, candidate.edge_ids[:1] + candidate.edge_ids[2:])

    assert [c.edge_ids for c in spliced] == [candidate.edge_ids]
    assert broken == []
    assert generator.last_no_candidates_reason
