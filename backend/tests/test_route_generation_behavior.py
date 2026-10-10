"""ルート生成の振る舞いを、公開の入口（`RouteGenerator`）だけから確かめる。

小さな道路網（3×3の格子、1辺約1km）を`RoadNetwork`で組み、生成の結果（`RouteCandidate`）の性質を見る。
探索の途中状態・キャッシュ・内部の関数には触らない——道路網の持ち方やエンジンの組み立てを作り替えても、
同じ道路網と設定から同じ性質の経路が出ることを、このファイルが通り続けることで示す。

ここで見ないもの:
- 探索アルゴリズムそのもの（ダイクストラ・A*・ターンの費用） → `test_routing.py`
- 候補の並べ方・周回の距離の幅・理由の文面・候補のidとラベル（戦略層） → `test_route_generator.py`。ここでは、エンジンが断った
  ときに候補が空になることまでを見る
- 材料の値の求め方 → `test_material_values.py`

道路網と、それをエンジンへ渡す道具は`tests/route_world.py`が持つ（HTTPの入口のテストと共有）。
"""

import logging
import math
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisDefinition, BreakpointLinearShape, MaterialTerm
from app.domain.geo import haversine_distance_km
from app.domain.graph import node_key
from app.domain.material_catalog import GRADIENT_PERCENT
from app.domain.rain import rain_window_material_id
from app.domain.road_network import RoadNetwork
from app.domain.route import Coordinates
from app.domain.wind import WindForecastSeries, WindLattice
from app.domain.time_zone import JST
from app.domain.traffic import stop_count_material_ids
from tests import rain_history_fake
from tests.axis_system_fixture import replaced_axis_definitions
from app.domain.route_request import FixedPoints
from tests.route_world import (
    AVOID_AXIS,
    BAD_MATERIAL,
    BASE_LAT,
    BASE_LON,
    CENTER,
    COORDINATES,
    ISLAND_WAY,
    LAT_STEP,
    LON_STEP,
    NODE_OF,
    NORTH_EAST,
    SOUTH_EAST,
    SOUTH_WEST,
    WAYS,
    at,
    avoid_axis_declared,
    generator_for,
    grid_network,
    lattice_network,
    lattice_node,
    lattice_ways,
    node_point,
    road_network,
    ways_of,
)


@pytest.fixture
def avoid_axis():
    """避けたい材料が1の区間ほど難しいと評価する公開軸を1本だけ宣言する（`avoid_weight`はこの軸の重み）。"""
    with avoid_axis_declared():
        yield


@pytest.fixture
def engine_over(monkeypatch, avoid_axis):
    """道路網から、本物のエンジンの上に戦略層（`RouteGenerator`）を組む。軸は`avoid_axis`の1本。"""

    def build(network: RoadNetwork, *, avoid_weight: float = 0.0, wind: WindForecastSeries | None = None):
        return generator_for(monkeypatch, network, avoid_weight, wind)

    return build


# ---------------------------------------------------------------------------------------


def assert_connected(candidate, start: int, end: int) -> None:
    """経路が`start`から始まり`end`で終わり、区間どうしが途切れずにつながる。"""
    assert candidate.node_ids[0] == node_key(start)
    assert candidate.node_ids[-1] == node_key(end)
    assert len(candidate.node_ids) == len(candidate.edge_ids) + 1
    lengths = [haversine_distance_km(at(int(a.split("-")[-1])), at(int(b.split("-")[-1])))
               for a, b in zip(candidate.node_ids, candidate.node_ids[1:])]
    assert all(length > 0 for length in lengths)
    assert math.isclose(sum(lengths), candidate.distance_km, abs_tol=0.02)


def fastest_of(candidates):
    """一覧の中で所要時間が最小の候補（基準線）。"""
    return min(candidates, key=lambda c: c.estimated_duration_seconds)


async def test_destination_route_runs_from_origin_to_destination(engine_over):
    generator = engine_over(grid_network())

    candidates = await generator.generate_via_waypoints(at(SOUTH_WEST), [], destination=at(NORTH_EAST), max_routes=3, start_time=DEPARTURE)

    assert candidates
    for candidate in candidates:
        assert_connected(candidate, SOUTH_WEST, NORTH_EAST)
    # 格子の対角は最短で4区間（約4km）。基準線（時間最短）はそれより遠回りしない。
    fastest = fastest_of(candidates)
    assert len(fastest.edge_ids) == 4
    # 探索用の区間は形を持たない。取り直した形で、4区間ぶんの折れ線になる。
    assert len(fastest.geometry["coordinates"]) == 5


async def test_weight_on_an_axis_steers_the_route_away_from_what_it_scores_badly(engine_over):
    """南の道と東の道（南西→南東→北東）だけが避けたい材料を持つ。重みを掛けると、最も易しい候補はそこを通らない。"""
    bad = {100, 101, 202, 205}  # 南の横の道2本と東の縦の道2本
    generator = engine_over(grid_network(bad_ways=bad), avoid_weight=1.0)

    candidates = await generator.generate_via_waypoints(at(SOUTH_WEST), [], destination=at(NORTH_EAST), max_routes=3, start_time=DEPARTURE)

    easiest = min(candidates, key=lambda c: c.overall_difficulty.average)
    assert_connected(easiest, SOUTH_WEST, NORTH_EAST)
    assert not set(ways_of(easiest)) & bad


async def test_oneway_road_is_never_driven_against_its_direction(engine_over):
    """中央の縦の道（南→北だけ走れる）を、北→南の目的地ルートで逆走しない。"""
    oneway = {201, 204}
    generator = engine_over(grid_network(oneway_ways=oneway))

    candidates = await generator.generate_via_waypoints(
        at(NODE_OF[2, 1]), [], destination=at(NODE_OF[0, 1]), max_routes=3, start_time=DEPARTURE)

    assert candidates
    for candidate in candidates:
        assert_connected(candidate, NODE_OF[2, 1], NODE_OF[0, 1])
        assert not [e for e in candidate.edge_ids if int(e.split("-")[1]) in oneway and e.endswith("bwd")]


async def test_motorway_is_never_used_even_when_it_is_the_short_way(engine_over):
    motorway = {100, 101}  # 南の横の道
    generator = engine_over(grid_network(motorway_ways=motorway))

    candidates = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], destination=at(NODE_OF[0, 2]), max_routes=3, start_time=DEPARTURE)

    assert candidates
    for candidate in candidates:
        assert_connected(candidate, SOUTH_WEST, NODE_OF[0, 2])
        assert not set(ways_of(candidate)) & motorway


async def test_loop_returns_to_its_origin(engine_over):
    generator = engine_over(grid_network())

    candidates = await generator.generate_loops(at(CENTER), 4.0, 1.5, max_routes=3, start_time=DEPARTURE)

    assert candidates
    for candidate in candidates:
        assert_connected(candidate, CENTER, CENTER)


async def test_segments_cover_the_whole_route(engine_over):
    generator = engine_over(grid_network())

    (candidate, *_) = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], destination=at(NORTH_EAST), max_routes=1, start_time=DEPARTURE)

    assert math.isclose(sum(s.distance_km for s in candidate.segments), candidate.distance_km, abs_tol=0.02)


async def test_spliced_route_is_evaluated_as_sent(engine_over):
    generator = engine_over(grid_network())
    (candidate, *_) = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], destination=at(NORTH_EAST), max_routes=1, start_time=DEPARTURE)

    spliced = await generator.generate_spliced_route(at(SOUTH_WEST), at(NORTH_EAST), candidate.edge_ids, start_time=DEPARTURE)

    assert [c.edge_ids for c in spliced] == [candidate.edge_ids]


@pytest.mark.parametrize(
    ("origin", "destination", "edges"),
    [
        (SOUTH_WEST, NORTH_EAST, lambda edge_ids: edge_ids[:1] + edge_ids[2:]),  # 途中で途切れる
        (CENTER, NORTH_EAST, lambda edge_ids: edge_ids),  # 起点が違う
        (SOUTH_WEST, SOUTH_EAST, lambda edge_ids: edge_ids),  # 終点が違う
        (SOUTH_WEST, NORTH_EAST, lambda edge_ids: [*edge_ids, "way-999-seg0-fwd"]),  # 道路網に無い区間を含む
    ],
)
async def test_a_spliced_route_the_road_network_cannot_trace_is_refused(
        engine_over, caplog, origin, destination, edges):
    """断った理由は常時のログに残すが、ノード・区間のOSMのidは詳しい記録（DEBUG）にだけ載せる（公開の地図で場所をそのまま引けるため）。"""
    generator = engine_over(grid_network())
    (candidate, *_) = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], destination=at(NORTH_EAST), max_routes=1, start_time=DEPARTURE)

    with caplog.at_level(logging.DEBUG):
        assert await generator.generate_spliced_route(
            at(origin), at(destination), edges(candidate.edge_ids), start_time=DEPARTURE) == []

    levels = [r.levelno for r in caplog.records if re.search(r"osm-node-|way-\d", r.getMessage())]
    assert levels and set(levels) == {logging.DEBUG}


# --- 候補の選び方 ---


async def test_fastest_route_ignores_the_axis_weights(engine_over):
    """基準線は軸の重みを一切使わない。避けたい道が最短でも、基準線はそこを通る（対価として比べる相手のため）。"""
    generator = engine_over(grid_network(bad_ways={100}), avoid_weight=5.0)

    candidates = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], destination=at(SOUTH_EAST), max_routes=3, start_time=DEPARTURE)

    fastest = fastest_of(candidates)
    assert ways_of(fastest) == [100, 101]


async def test_destination_candidates_never_ride_a_road_there_and_back(engine_over):
    """前向きと後ろ向きの探索が同じ道を通る経路は、行って戻る形になり経路として成立しない。"""
    generator = engine_over(grid_network(bad_ways={100, 101, 202, 205}), avoid_weight=1.0)

    candidates = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], destination=at(NORTH_EAST), max_routes=5, start_time=DEPARTURE)

    assert candidates
    for candidate in candidates:
        assert len(set(ways_of(candidate))) == len(candidate.edge_ids)


async def test_the_same_request_returns_the_same_routes(engine_over):
    """同点の候補も毎回同じ順で返す。変わると、区間の乗り換えで送り返すidが指す先が変わる。"""
    first = await engine_over(grid_network()).generate_via_waypoints(
        at(SOUTH_WEST), [], destination=at(NORTH_EAST), max_routes=5, start_time=DEPARTURE)
    second = await engine_over(grid_network()).generate_via_waypoints(
        at(SOUTH_WEST), [], destination=at(NORTH_EAST), max_routes=5, start_time=DEPARTURE)

    assert [c.edge_ids for c in first] == [c.edge_ids for c in second]


async def test_loop_candidates_are_never_the_same_loop_twice(engine_over):
    """向きを入れ替えただけの周回も同じ周回として扱い、一覧に2度並べない。"""
    generator = engine_over(grid_network())

    candidates = await generator.generate_loops(at(CENTER), 4.0, 1.5, max_routes=5, start_time=DEPARTURE)

    loops = [frozenset(ways_of(c)) for c in candidates]
    assert len(loops) == len(set(loops))


async def test_loop_never_drives_against_a_one_way_road(engine_over):
    oneway = {101, 103, 105, 202, 205}  # 東側の横の道（西→東だけ）と東の縦の道（南→北だけ）
    generator = engine_over(grid_network(oneway_ways=oneway))

    candidates = await generator.generate_loops(at(CENTER), 4.0, 1.5, max_routes=5, start_time=DEPARTURE)

    assert candidates
    for candidate in candidates:
        assert_connected(candidate, CENTER, CENTER)
        assert not [e for e in candidate.edge_ids if int(e.split("-")[1]) in oneway and e.endswith("bwd")]


# --- 経由地・目的地の扱い ---


#: 経由地・目的地を置いた生成を見る格子（6×6、1辺約1km）。3×3では、置いた点を通っても候補が分かれる長さが無い。
LATTICE = lattice_network(6)


def lattice_at(row: int, col: int) -> Coordinates:
    return node_point(LATTICE, lattice_node(row, col))


def passes_in_order(candidate, start: int, stops: list[int], end: int) -> bool:
    """経路が`start`から始まり、`stops`を置いた順に通り、`end`で終わる。"""
    nodes = candidate.node_ids
    if nodes[0] != node_key(start) or nodes[-1] != node_key(end):
        return False
    position = 0
    for stop in stops:
        if node_key(stop) not in nodes[position:]:
            return False
        position = nodes.index(node_key(stop), position)
    return True


@pytest.mark.parametrize(
    ("origin", "waypoints", "destination", "distance"),
    [
        pytest.param((1, 1), [(1, 4), (4, 4)], None, None, id="距離なし・経由地を通って出発地へ戻る"),
        pytest.param((1, 1), [(2, 1)], (4, 3), None, id="距離なし・経由地を通って目的地へ"),
        pytest.param((2, 2), [(2, 3), (3, 3)], None, (12.0, 2.0), id="距離あり・経由地を通って出発地へ戻る"),
        pytest.param((1, 1), [], (4, 4), (10.0, 2.0), id="距離あり・目的地へ寄り道して"),
        pytest.param((1, 1), [(1, 3)], (4, 4), (10.0, 2.0), id="距離あり・経由地を通って目的地へ"),
    ],
)
async def test_routes_through_placed_points_keep_their_order_come_in_several_and_fit_the_distance(
    engine_over, origin, waypoints, destination, distance,
):
    """経由地は置いた順に通り（夕食のあと銭湯、の順は利用者の意図）、終点は目的地か出発地。候補は1本に限らず
    求めた数まで出て、距離を決めたときは全長が目標±許容に入る。所要時間が最短の1本（基準線）は、目的地へ距離を
    決めずに向かうときだけ含む（距離を決めると、最短の1本は目標の距離と噛み合わない）。"""
    generator = engine_over(LATTICE)
    start, stops = lattice_node(*origin), [lattice_node(*point) for point in waypoints]
    end = start if destination is None else lattice_node(*destination)
    end_point = None if destination is None else lattice_at(*destination)

    if distance is None:
        candidates = await generator.generate_via_waypoints(
            lattice_at(*origin), [lattice_at(*point) for point in waypoints], destination=end_point, max_routes=5, start_time=DEPARTURE)
    else:
        target, tolerance = distance
        candidates = await generator.generate_loops(
            lattice_at(*origin), target, tolerance, max_routes=5, start_time=DEPARTURE,
            points=FixedPoints(waypoints=[lattice_at(*point) for point in waypoints], destination=end_point))

    assert len(candidates) >= 2
    for candidate in candidates:
        assert passes_in_order(candidate, start, stops, end)
        if distance is not None:
            assert abs(candidate.distance_km - target) <= tolerance
    assert sum(candidate.is_fastest for candidate in candidates) == (distance is None and destination is not None)


def physical_segments(candidate) -> list[frozenset[str]]:
    """経路の区間を、進行方向を問わない道の区間（両端のノードの組）で並べたもの。"""
    return [frozenset(pair) for pair in zip(candidate.node_ids, candidate.node_ids[1:])]


#: 横の道(2, *)だけが避けたい材料を持たない格子。避けたい軸に重みがあると、横の道が来た道でも、罰が無ければ帰りは
#: 横の道へ寄る。
ROW_2_ONLY = lattice_network(6, bad_ways={
    way for way, (start, end) in lattice_ways(6).items()
    if not (start // 100 % 10 == 2 and end // 100 % 10 == 2)
})


@pytest.mark.parametrize(
    ("network", "avoid_weight", "waypoints", "distance", "fixed_count"),
    [
        # 出発地(2,1) → (2,4) → (2,2) は、置いた点どうしを素直な道で結ぶと同じ横の道を戻る。最後の(2,2)→出発地の
        # 最短は走った横の道そのもの（避けなければ2度目を走る）。
        pytest.param(LATTICE, 0.0, [(2, 4), (2, 2)], None, 5, id="距離なし"),
        # 出発地(2,1) → (2,4)のあと、全長8kmの周回の残りを選ぶ。避けなければ帰りは易しい横の道（来た道）へ寄る。
        pytest.param(ROW_2_ONLY, 1.0, [(2, 4)], (8.0, 1.5), 3, id="距離あり"),
    ],
)
async def test_the_freely_chosen_part_avoids_every_road_already_ridden_but_the_placed_legs_do_not(
    engine_over, network, avoid_weight, waypoints, distance, fixed_count,
):
    """自由に選ぶ部分（最後の経由地から先）は、置いた点どうしの区間を含め、それまでに走った道を避ける。置いた点どうしの
    区間は避けずに素直な道で結ぶ（遠回りすると、置いた点の間が利用者の思う道でなくなる）。"""
    generator = engine_over(network, avoid_weight=avoid_weight)
    origin = lattice_node(2, 1)
    points = FixedPoints(waypoints=[lattice_at(*point) for point in waypoints], destination=None)

    if distance is None:
        candidates = await generator.generate_via_waypoints(
            lattice_at(2, 1), points.waypoints, destination=None, max_routes=3, start_time=DEPARTURE)
    else:
        candidates = await generator.generate_loops(
            lattice_at(2, 1), *distance, max_routes=3, start_time=DEPARTURE, points=points)

    assert candidates
    stops = [origin, *(lattice_node(*point) for point in waypoints)]
    straight = [node_key(lattice_node(2, col)) for col in range(1, 5)]
    for candidate in candidates:
        fixed_nodes = candidate.node_ids[:fixed_count + 1]
        assert [n for n in fixed_nodes if n in straight] == fixed_nodes  # 置いた点どうしは横の道のまま
        assert passes_in_order(candidate, origin, stops[1:], origin)
        segments = physical_segments(candidate)
        free = segments[fixed_count:]
        assert not set(free) & set(segments[:fixed_count])
        assert len(set(free)) == len(free)


#: 1周8kmの輪。出発地Oから北のAを通って北東のWまで2km、反対回り（南西の4点）でWまで6km。O→A→Wの向きだけ
#: 避けたい材料を持ち、逆向き（W→A→O）は持たない。
RING_COORDINATES = {
    1: (BASE_LAT, BASE_LON),  # O
    2: (BASE_LAT + LAT_STEP, BASE_LON),  # A
    3: (BASE_LAT + LAT_STEP, BASE_LON + LON_STEP),  # W
    4: (BASE_LAT + 2 * LAT_STEP, BASE_LON + LON_STEP),
    5: (BASE_LAT + 2 * LAT_STEP, BASE_LON - LON_STEP),
    6: (BASE_LAT, BASE_LON - LON_STEP),
}
RING = road_network(
    {1: (1, 2), 2: (2, 3), 3: (3, 4), 4: (4, 5), 5: (5, 6), 6: (6, 1)}, RING_COORDINATES, bad_forward_ways={1, 2},
)


@pytest.mark.parametrize(
    ("waypoints", "expected"),
    [
        pytest.param([3], [1, 6, 5, 4, 3, 2, 1], id="経由地1つは逆に回ってよい"),
        pytest.param([2, 3], [1, 2, 3, 4, 5, 6, 1], id="経由地2つは置いた順のまま"),
    ],
)
async def test_a_loop_is_ridden_the_easier_way_round_only_when_that_keeps_the_placed_order(
    engine_over, waypoints, expected,
):
    """O→A→Wは避けたい道で、W→A→Oはそうでない。Wだけを置いた周回は、逆に回ってもWを通るので易しい向き
    （O→南西→W→A→O）で出す。A・Wの順に置いた周回は、逆に回るとWがAより先になるので、難しくても置いた順で出す。"""
    generator = engine_over(RING, avoid_weight=1.0)

    candidates = await generator.generate_via_waypoints(
        node_point(RING, 1), [node_point(RING, point) for point in waypoints], destination=None, max_routes=1, start_time=DEPARTURE)

    assert [candidate.node_ids for candidate in candidates] == [[node_key(n) for n in expected]]


@pytest.mark.parametrize("where", ["waypoint", "destination"])
async def test_a_point_far_from_every_road_is_refused(engine_over, where):
    """道の無い所を指した点を、何kmも離れた道へ黙って寄せない。"""
    generator = engine_over(grid_network())
    far = Coordinates(latitude=BASE_LAT + 0.3, longitude=BASE_LON + 0.3)

    if where == "waypoint":
        candidates = await generator.generate_via_waypoints(at(SOUTH_WEST), [far], destination=None, max_routes=1, start_time=DEPARTURE)
    else:
        candidates = await generator.generate_via_waypoints(at(SOUTH_WEST), [], destination=far, max_routes=3, start_time=DEPARTURE)

    assert candidates == []


async def test_a_destination_on_an_isolated_road_is_moved_to_the_nearest_reachable_node(engine_over):
    """指した先が本線とつながらない小塊だと、そこへ着く経路は無い。すぐ近くの本線へ移して、移したことを返す。"""
    generator = engine_over(grid_network(island=True))

    candidates = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], destination=at(91), max_routes=3, start_time=DEPARTURE)

    assert candidates
    for candidate in candidates:
        assert_connected(candidate, SOUTH_WEST, NORTH_EAST)
    assert generator.last_destination_correction == at(NORTH_EAST)


def _stuck_by_north_east(stuck: str, east_deg: float) -> tuple[RoadNetwork, Coordinates]:
    """格子と、北東の角から`east_deg`だけ東の点。その点の一番近い道は、格子へ出入りできない——`island`は格子と
    つながらない道、`one_way_spur`は北東の角から入るだけの一方通行の行き止まり（入れるが出られない）。"""
    end = (COORDINATES[NORTH_EAST][0], COORDINATES[NORTH_EAST][1] + east_deg)
    if stuck == "island":
        ways = {**WAYS, ISLAND_WAY: (90, 91)}
        coordinates = {**COORDINATES, 90: (end[0], end[1] - 0.004), 91: end}
        oneway: set[int] = set()
    else:
        ways = {**WAYS, ISLAND_WAY: (NORTH_EAST, 92)}
        coordinates = {**COORDINATES, 92: end}
        oneway = {ISLAND_WAY}
    return road_network(ways, coordinates, oneway_ways=oneway), Coordinates(latitude=end[0], longitude=end[1])


@pytest.mark.parametrize("stuck", ["island", "one_way_spur"])
@pytest.mark.parametrize("placed", ["origin_of_distance_loop", "origin_of_waypoint_loop", "waypoint"])
async def test_a_point_whose_nearest_road_cannot_be_left_is_moved_to_the_nearest_road_that_can(engine_over, stuck, placed):
    """出発地・経由地の一番近い道から格子へ出入りできないと、そこを通る経路は無い。すぐ近くの出入りできる道へ寄せて出す。"""
    network, point = _stuck_by_north_east(stuck, 0.008)
    generator = engine_over(network)

    if placed == "origin_of_distance_loop":
        candidates = await generator.generate_loops(point, 6.0, 1.5, max_routes=3, start_time=DEPARTURE)  # 角から回れる長さ
    elif placed == "origin_of_waypoint_loop":
        candidates = await generator.generate_via_waypoints(
            point, [at(SOUTH_WEST)], destination=None, max_routes=3, start_time=DEPARTURE)
    else:
        candidates = await generator.generate_via_waypoints(
            at(SOUTH_WEST), [point], destination=None, max_routes=3, start_time=DEPARTURE)

    assert candidates
    start = SOUTH_WEST if placed == "waypoint" else NORTH_EAST
    for candidate in candidates:
        assert_connected(candidate, start, start)
        assert node_key(NORTH_EAST) in candidate.node_ids


@pytest.mark.parametrize("placed", ["origin", "waypoint", "destination"])
async def test_a_point_whose_only_nearby_road_cannot_be_left_is_refused(engine_over, placed):
    """出入りできる道が近くに無いなら、指した覚えのない遠くの道へ黙って寄せない。"""
    network, point = _stuck_by_north_east("island", 0.03)  # 北東の角から約2.7km
    generator = engine_over(network)

    if placed == "origin":
        candidates = await generator.generate_loops(point, 4.0, 1.5, max_routes=3, start_time=DEPARTURE)
    elif placed == "waypoint":
        candidates = await generator.generate_via_waypoints(
            at(SOUTH_WEST), [point], destination=None, max_routes=3, start_time=DEPARTURE)
    else:
        candidates = await generator.generate_via_waypoints(
            at(SOUTH_WEST), [], destination=point, max_routes=3, start_time=DEPARTURE)

    assert candidates == []
    assert generator.last_no_candidates_reason


# --- 区間の表示 ---


DEPARTURE = datetime(2026, 9, 22, 8, 10, tzinfo=JST)


async def test_segment_arrival_times_run_from_the_departure_within_the_duration(engine_over):
    """到達予想は探索と同じ時計で積む。最初の区間は出発時刻に始まり、どの区間も所要時間の内に入る。"""
    generator = engine_over(grid_network())

    (candidate, *_) = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], destination=at(NORTH_EAST), max_routes=1, start_time=DEPARTURE)

    arrivals = [datetime.fromisoformat(s.estimated_arrival_time) for s in candidate.segments]
    assert arrivals[0] == DEPARTURE
    assert arrivals == sorted(set(arrivals))
    assert arrivals[-1] < DEPARTURE + timedelta(seconds=candidate.estimated_duration_seconds)


async def test_a_segment_without_data_does_not_show_the_axis_as_zero(engine_over):
    """データの無い区間に0を出すと、「データが無い」と「良い」が画面で区別できない。"""
    generator = engine_over(grid_network(unknown_ways={100}), avoid_weight=1.0)

    candidates = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], destination=at(SOUTH_EAST), max_routes=3, start_time=DEPARTURE)

    fastest = fastest_of(candidates)
    first, second = fastest.segments
    assert AVOID_AXIS not in first.axis_difficulties
    assert second.axis_difficulties[AVOID_AXIS] == 0.0


def _slope_axis(*, is_published: bool) -> AxisDefinition:
    """勾配の符号付きの値を地図が塗る軸（本番の勾配の軸と同じく、勾配の絶対値を読む折れ線）。"""
    return AxisDefinition(
        axis_id="slope", label="勾配", default_weight=0.0, is_published=is_published,
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material=GRADIENT_PERCENT)], preprocess="abs", breakpoints=[(0.0, 0.0), (10.0, 100.0)],
        ),
    )


@pytest.mark.parametrize(("is_published", "carried"), [(True, True), (False, False)])
async def test_a_published_slope_axis_carries_its_grade_on_every_segment_even_with_no_weight(
    engine_over, is_published, carried,
):
    """地図のレンズはルートを作ったあとにも勾配へ切り替わり、切り替えでは作り直さない。重み0の勾配の軸でも
    区間が勾配の値を持たないと、あとから勾配のレンズにしたとき全区間が「データなし」になる。下書きの軸はレンズに出ない。"""
    network = grid_network()
    flat = np.zeros(len(network.edge_way_id))
    surveyed = replace(network, elevation_present=flat == 0, elevation_gain_m=flat, elevation_loss_m=flat)
    with replaced_axis_definitions({**AXIS_DEFINITIONS, "slope": _slope_axis(is_published=is_published)}):
        candidates = await engine_over(surveyed).generate_via_waypoints(
            at(SOUTH_WEST), [], destination=at(SOUTH_EAST), max_routes=1, start_time=DEPARTURE)

    assert [GRADIENT_PERCENT in segment.material_values for segment in candidates[0].segments] == [carried, carried]


@pytest.mark.parametrize("missing", ["no_gradient_ways", "no_stop_count_ways"])
async def test_the_share_of_the_route_timed_without_data_is_reported(engine_over, missing):
    """勾配の値が無い道は平地、停止要因の件数が無い道は待ち無しとして所要時間を出す。その距離の割合を候補が持ち、
    画面が利用者へ知らせる。南西→南東の最速は同じ長さの2本の道で、1本目だけ値が無い。"""
    generator = engine_over(grid_network(**{missing: {100}}))

    candidates = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], destination=at(SOUTH_EAST), max_routes=3, start_time=DEPARTURE)

    fastest = fastest_of(candidates)
    assert ways_of(fastest)[0] == 100
    assert fastest.missing_travel_data_share == pytest.approx(0.5, abs=0.01)
    complete = await engine_over(grid_network()).generate_via_waypoints(
        at(SOUTH_WEST), [], destination=at(SOUTH_EAST), max_routes=3, start_time=DEPARTURE)
    assert fastest_of(complete).missing_travel_data_share == 0.0


def _rain_axis(axis_id: str, *materials: str) -> AxisDefinition:
    terms = [MaterialTerm(material=rain_window_material_id(3)), *(MaterialTerm(material=m) for m in materials)]
    return AxisDefinition(
        axis_id=axis_id, label="雨", default_weight=0.0, is_published=True,
        shape=BreakpointLinearShape(terms=terms, breakpoints=[(0.0, 0.0), (10.0, 100.0)]),
    )


#: 雨の材料だけを読む軸と、雨と道の材料（避けたい材料）を足して読む軸。
RAIN_AXES = {"rain": _rain_axis("rain"), "rain_and_bad": _rain_axis("rain_and_bad", BAD_MATERIAL)}

#: 南の道の西半分（道100、中点139.6055E）の近くと、東半分（道101、中点139.6165E）の近くの雨量計。
RAIN_GAUGES = {
    "west": {"lat": [35, 36.0], "lon": [139, 36.0], "kjName": "西"},
    "east": {"lat": [35, 36.0], "lon": [139, 37.32], "kjName": "東"},
}


async def test_each_segment_is_scored_with_the_rain_at_the_gauge_nearest_its_midpoint(engine_over, fake_redis):
    """雨の材料は区間の中点に最も近い雨量計の今の観測で、道の材料と同じく区間の得点とルートの生値（mm）に載る
    ——雨と道の材料を1つの軸で足すこともできる。南西→南東の最速は道100（西の雨量計）と道101（東の雨量計）で、
    西では1時間1.0mmの雨が続き、東は降っていない。"""
    await rain_history_fake.observe(RAIN_GAUGES, {"west": 1.0, "east": 0.0})

    with replaced_axis_definitions({**AXIS_DEFINITIONS, **RAIN_AXES}):
        candidates = await engine_over(grid_network(bad_ways={101})).generate_via_waypoints(
            at(SOUTH_WEST), [], destination=at(SOUTH_EAST), max_routes=3, start_time=DEPARTURE)

    fastest = fastest_of(candidates)
    assert ways_of(fastest) == [100, 101]
    # 3時間の雨量は1時間1.0mmの3本ぶん。道101の避けたい材料1は、雨の0mmに足されて10点になる。
    assert [segment.axis_difficulties["rain"] for segment in fastest.segments] == [30.0, 0.0]
    assert [segment.axis_difficulties["rain_and_bad"] for segment in fastest.segments] == [30.0, 10.0]
    assert fastest.axis_raw_values["rain"] == pytest.approx(
        3.0 * fastest.segments[0].distance_km / sum(segment.distance_km for segment in fastest.segments), rel=1e-3)


#: 信号の密度（回/km）を、0から始まる直線（9.58回/kmで100点、その先は100点）で点数にする軸（本番の停止密度の軸の形）。
STOP_AXIS = AxisDefinition(
    axis_id="stops", label="停止", default_weight=0.0, is_published=True,
    shape=BreakpointLinearShape(
        terms=[MaterialTerm(material=stop_count_material_ids()[0])], breakpoints=[(0.0, 0.0), (9.58, 100.0)],
    ),
)


async def test_a_route_scores_a_density_axis_from_its_mean_count_rather_than_the_mean_of_segment_scores(engine_over):
    """1kmあたりの回数で測る軸は、ルートの値を回数の距離平均から点数にする。南西→南東の最速は同じ長さの道100（12回/km）と
    道101（0回/km）で、区間の点数（頭打ちの100点と0点）の平均は50点だが、回数の平均（6回/km）の点数は62.6点。
    待ちの秒で遠回りが速くならないよう、南西と南東から北へ出る道は走れない道にする。"""
    network = grid_network(stop_density_of={100: 12.0}, motorway_ways={200, 202})
    with replaced_axis_definitions({**AXIS_DEFINITIONS, "stops": STOP_AXIS}):
        candidates = await engine_over(network).generate_via_waypoints(
            at(SOUTH_WEST), [], destination=at(SOUTH_EAST), max_routes=3, start_time=DEPARTURE)

    fastest = fastest_of(candidates)
    assert ways_of(fastest) == [100, 101]
    assert [segment.axis_difficulties["stops"] for segment in fastest.segments] == [100.0, 0.0]
    assert fastest.axis_difficulties["stops"] == 62.6


async def test_without_an_observation_history_only_the_rain_axis_has_no_data(engine_over, fake_redis):
    """履歴が無い（バッチがまだ・Redisが不通）ときもルートは出て、雨を読む軸だけが「データなし」になる。"""

    with replaced_axis_definitions({**AXIS_DEFINITIONS, **RAIN_AXES}):
        candidates = await engine_over(grid_network()).generate_via_waypoints(
            at(SOUTH_WEST), [], destination=at(SOUTH_EAST), max_routes=3, start_time=DEPARTURE)

    fastest = fastest_of(candidates)
    assert all("rain" not in segment.axis_difficulties for segment in fastest.segments)
    assert all(segment.axis_difficulties[AVOID_AXIS] == 0.0 for segment in fastest.segments)


def _wind(times: list[datetime], speed_by_point: list[float]) -> WindForecastSeries:
    """格子の角4点（南西・南東・北西・北東）に置いた時別の風。風速は時刻によらず点ごとに一定。"""
    lattice = WindLattice(south=BASE_LAT, west=BASE_LON, lat_step=2 * LAT_STEP, lon_step=2 * LON_STEP, rows=2, cols=2)
    speed = np.repeat(np.array(speed_by_point, dtype=float)[:, None], len(times), axis=1)
    return WindForecastSeries(times=times, speed_ms=speed, direction_deg=np.zeros_like(speed), lattice=lattice)


HOURS_OF_THE_DAY = [datetime(2026, 9, 22, h) for h in range(24)]


async def test_segment_wind_is_the_forecast_for_the_local_time_of_passing(engine_over):
    """予報の時刻は日本時間。出発時刻を別のタイムゾーンで渡されても、通る時刻の予報を読む（ずれると9時間違う風になる）。"""
    generator = engine_over(grid_network(), wind=_wind(HOURS_OF_THE_DAY, [3.0, 3.0, 3.0, 3.0]))

    (candidate, *_) = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], destination=at(NORTH_EAST), max_routes=1,
        start_time=DEPARTURE.astimezone(timezone.utc))

    assert {s.wind.forecast_at for s in candidate.segments} == {"2026-09-22T08:00"}
    assert not any(s.wind.extended for s in candidate.segments)


async def test_segment_wind_beyond_the_forecast_is_marked_as_extended(engine_over):
    generator = engine_over(grid_network(), wind=_wind(HOURS_OF_THE_DAY[5:7], [3.0, 3.0, 3.0, 3.0]))

    (candidate, *_) = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], destination=at(NORTH_EAST), max_routes=1, start_time=DEPARTURE)

    assert all(s.wind.extended for s in candidate.segments)


async def test_each_segment_takes_the_wind_of_the_grid_point_nearest_to_it(engine_over):
    """起点1か所の予報を全区間に使うと、海沿いや山で違う風になる。西の2点は弱い風、東の2点は強い風。"""
    generator = engine_over(grid_network(), wind=_wind(HOURS_OF_THE_DAY, [2.0, 8.0, 2.0, 8.0]))

    candidates = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], destination=at(SOUTH_EAST), max_routes=3, start_time=DEPARTURE)

    fastest = fastest_of(candidates)
    assert [s.wind.speed_ms for s in fastest.segments] == [2.0, 8.0]


async def test_a_route_timed_without_the_wind_forecast_says_so(engine_over):
    """風の予報が読めないときは無風として所要時間を出す。出したことを候補が持ち、画面が利用者へ知らせる。"""
    without = await engine_over(grid_network()).generate_via_waypoints(
        at(SOUTH_WEST), [], destination=at(NORTH_EAST), max_routes=1, start_time=DEPARTURE)
    with_wind = await engine_over(grid_network(), wind=_wind(HOURS_OF_THE_DAY, [3.0] * 4)).generate_via_waypoints(
        at(SOUTH_WEST), [], destination=at(NORTH_EAST), max_routes=1, start_time=DEPARTURE)

    assert all(c.wind_unavailable for c in without)
    assert not any(c.wind_unavailable for c in with_wind)
