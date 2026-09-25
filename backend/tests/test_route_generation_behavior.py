"""ルート生成の振る舞いを、公開の入口（`RouteGenerator`）だけから確かめる。

小さな道路網（3×3の格子、1辺約1km）を`RoadNetwork`で組み、生成の結果（`RouteCandidate`）の性質を見る。
探索の途中状態・キャッシュ・内部の関数には触らない——道路網の持ち方やエンジンの組み立てを作り替えても、
同じ道路網と設定から同じ性質の経路が出ることを、このファイルが通り続けることで示す。

ここで見ないもの:
- 探索アルゴリズムそのもの（ダイクストラ・A*・ターンの費用） → `test_routing.py`
- 候補の並べ方・理由の文面（戦略層） → `test_route_generator.py`
- 材料の値の求め方 → `test_material_values.py`

道路網と、それをエンジンへ渡す道具は`tests/route_world.py`が持つ（HTTPの入口のテストと共有）。
"""

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.domain.geo import haversine_distance_km
from app.domain.graph import node_key
from app.domain.road_network import RoadNetwork
from app.domain.route import Coordinates
from app.domain.wind import WindForecastSeries, WindLattice
from app.services.route_generator import JST, RouteGenerator
from tests.route_world import (
    AVOID_AXIS,
    BASE_LAT,
    BASE_LON,
    CENTER,
    LAT_STEP,
    LON_STEP,
    NODE_OF,
    NORTH_EAST,
    NORTH_WEST,
    SOUTH_EAST,
    SOUTH_WEST,
    at,
    avoid_axis_declared,
    engine_for,
    grid_network,
    ways_of,
)


@pytest.fixture
def engine_over(monkeypatch):
    """道路網から、本物のエンジンの上に戦略層（`RouteGenerator`）を組む。"""

    def build(network: RoadNetwork, *, avoid_weight: float = 0.0, wind: WindForecastSeries | None = None):
        return RouteGenerator(engine_for(monkeypatch, network, avoid_weight, wind))

    return build


@pytest.fixture
def preview_over(monkeypatch):
    """道路網から、2点間の区間確認（`/api/routes/preview`の入口）を組む。"""

    def build(network: RoadNetwork):
        return engine_for(monkeypatch, network, 0.0, None).preview_segment

    return build


# ---------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _avoid_axis():
    with avoid_axis_declared():
        yield


def assert_connected(candidate, start: int, end: int) -> None:
    """経路が`start`から始まり`end`で終わり、区間どうしが途切れずにつながる。"""
    assert candidate.node_ids[0] == node_key(start)
    assert candidate.node_ids[-1] == node_key(end)
    assert len(candidate.node_ids) == len(candidate.edge_ids) + 1
    lengths = [haversine_distance_km(at(int(a.split("-")[-1])), at(int(b.split("-")[-1])))
               for a, b in zip(candidate.node_ids, candidate.node_ids[1:])]
    assert all(length > 0 for length in lengths)
    assert math.isclose(sum(lengths), candidate.distance_km, abs_tol=0.02)


async def test_destination_route_runs_from_origin_to_destination(engine_over):
    generator = engine_over(grid_network())

    candidates = await generator.generate_via_waypoints(at(SOUTH_WEST), [], 4.0, destination=at(NORTH_EAST), max_routes=3)

    assert candidates
    for candidate in candidates:
        assert_connected(candidate, SOUTH_WEST, NORTH_EAST)
    # 格子の対角は最短で4区間（約4km）。基準線（時間最短）はそれより遠回りしない。
    fastest = next(c for c in candidates if c.is_fastest)
    assert len(fastest.edge_ids) == 4


async def test_weight_on_an_axis_steers_the_route_away_from_what_it_scores_badly(engine_over):
    """南の道と東の道（南西→南東→北東）だけが避けたい材料を持つ。重みを掛けると、最も易しい候補はそこを通らない。"""
    bad = {100, 101, 202, 205}  # 南の横の道2本と東の縦の道2本
    generator = engine_over(grid_network(bad_ways=bad), avoid_weight=1.0)

    candidates = await generator.generate_via_waypoints(at(SOUTH_WEST), [], 4.0, destination=at(NORTH_EAST), max_routes=3)

    easiest = min((c for c in candidates if not c.is_fastest), key=lambda c: c.overall_difficulty,
                  default=candidates[0])
    assert_connected(easiest, SOUTH_WEST, NORTH_EAST)
    assert not set(ways_of(easiest)) & bad


async def test_oneway_road_is_never_driven_against_its_direction(engine_over):
    """中央の縦の道（南→北だけ走れる）を、北→南の目的地ルートで逆走しない。"""
    oneway = {201, 204}
    generator = engine_over(grid_network(oneway_ways=oneway))

    candidates = await generator.generate_via_waypoints(
        at(NODE_OF[2, 1]), [], 3.0, destination=at(NODE_OF[0, 1]), max_routes=3)

    assert candidates
    for candidate in candidates:
        assert_connected(candidate, NODE_OF[2, 1], NODE_OF[0, 1])
        assert not [e for e in candidate.edge_ids if int(e.split("-")[1]) in oneway and e.endswith("bwd")]


async def test_motorway_is_never_used_even_when_it_is_the_short_way(engine_over):
    motorway = {100, 101}  # 南の横の道
    generator = engine_over(grid_network(motorway_ways=motorway))

    candidates = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], 3.0, destination=at(NODE_OF[0, 2]), max_routes=3)

    assert candidates
    for candidate in candidates:
        assert_connected(candidate, SOUTH_WEST, NODE_OF[0, 2])
        assert not set(ways_of(candidate)) & motorway


async def test_loop_returns_to_its_origin_within_the_distance_tolerance(engine_over):
    generator = engine_over(grid_network())

    candidates = await generator.generate_loops(at(CENTER), 4.0, 1.5, max_routes=3)

    assert candidates
    for candidate in candidates:
        assert_connected(candidate, CENTER, CENTER)
        assert abs(candidate.distance_km - 4.0) <= 1.5


async def test_segments_cover_the_whole_route(engine_over):
    generator = engine_over(grid_network())

    (candidate, *_) = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], 4.0, destination=at(NORTH_EAST), max_routes=1)

    assert math.isclose(sum(s.distance_km for s in candidate.segments), candidate.distance_km, abs_tol=0.02)
    assert candidate.estimated_duration_seconds is not None and candidate.estimated_duration_seconds > 0


async def test_spliced_route_is_evaluated_as_sent_and_a_broken_one_is_refused(engine_over):
    generator = engine_over(grid_network())
    (candidate, *_) = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], 4.0, destination=at(NORTH_EAST), max_routes=1)

    spliced = await generator.generate_spliced_route(at(SOUTH_WEST), at(NORTH_EAST), 4.0, candidate.edge_ids)
    broken = await generator.generate_spliced_route(
        at(SOUTH_WEST), at(NORTH_EAST), 4.0, candidate.edge_ids[:1] + candidate.edge_ids[2:])

    assert [c.edge_ids for c in spliced] == [candidate.edge_ids]
    assert broken == []
    assert generator.last_no_candidates_reason


# --- 候補の選び方 ---


async def test_fastest_route_ignores_the_axis_weights(engine_over):
    """基準線は軸の重みを一切使わない。避けたい道が最短でも、基準線はそこを通る（対価として比べる相手のため）。"""
    generator = engine_over(grid_network(bad_ways={100}), avoid_weight=5.0)

    candidates = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], 3.0, destination=at(SOUTH_EAST), max_routes=3)

    fastest = next(c for c in candidates if c.is_fastest)
    assert ways_of(fastest) == [100, 101]


async def test_destination_candidates_never_ride_a_road_there_and_back(engine_over):
    """前向きと後ろ向きの探索が同じ道を通る経路は、行って戻る形になり経路として成立しない。"""
    generator = engine_over(grid_network(bad_ways={100, 101, 202, 205}), avoid_weight=1.0)

    candidates = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], 4.0, destination=at(NORTH_EAST), max_routes=5)

    assert candidates
    for candidate in candidates:
        assert len(set(ways_of(candidate))) == len(candidate.edge_ids)


async def test_the_same_request_returns_the_same_routes(engine_over):
    """同点の候補も毎回同じ順で返す。変わると、区間の乗り換えで送り返すidが指す先が変わる。"""
    first = await engine_over(grid_network()).generate_via_waypoints(
        at(SOUTH_WEST), [], 4.0, destination=at(NORTH_EAST), max_routes=5)
    second = await engine_over(grid_network()).generate_via_waypoints(
        at(SOUTH_WEST), [], 4.0, destination=at(NORTH_EAST), max_routes=5)

    assert [c.edge_ids for c in first] == [c.edge_ids for c in second]


async def test_loop_candidates_are_never_the_same_loop_twice(engine_over):
    """向きを入れ替えただけの周回も同じ周回として扱い、一覧に2度並べない。"""
    generator = engine_over(grid_network())

    candidates = await generator.generate_loops(at(CENTER), 4.0, 1.5, max_routes=5)

    loops = [frozenset(ways_of(c)) for c in candidates]
    assert len(loops) == len(set(loops))


async def test_loop_never_drives_against_a_one_way_road(engine_over):
    oneway = {101, 103, 105, 202, 205}  # 東側の横の道（西→東だけ）と東の縦の道（南→北だけ）
    generator = engine_over(grid_network(oneway_ways=oneway))

    candidates = await generator.generate_loops(at(CENTER), 4.0, 1.5, max_routes=5)

    assert candidates
    for candidate in candidates:
        assert_connected(candidate, CENTER, CENTER)
        assert not [e for e in candidate.edge_ids if int(e.split("-")[1]) in oneway and e.endswith("bwd")]


# --- 経由地・目的地の扱い ---


async def test_waypoint_route_passes_each_waypoint_in_the_given_order(engine_over):
    generator = engine_over(grid_network())

    (candidate,) = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [at(NORTH_WEST), at(NORTH_EAST)], 6.0)

    assert_connected(candidate, SOUTH_WEST, SOUTH_WEST)
    assert candidate.node_ids.index(node_key(NORTH_WEST)) < candidate.node_ids.index(node_key(NORTH_EAST))


@pytest.mark.parametrize("where", ["waypoint", "destination"])
async def test_a_point_far_from_every_road_is_refused_with_a_reason(engine_over, where):
    """道の無い所を指した点を、何kmも離れた道へ黙って寄せない。"""
    generator = engine_over(grid_network())
    far = Coordinates(latitude=BASE_LAT + 0.3, longitude=BASE_LON + 0.3)

    if where == "waypoint":
        candidates = await generator.generate_via_waypoints(at(SOUTH_WEST), [far], 4.0)
    else:
        candidates = await generator.generate_via_waypoints(at(SOUTH_WEST), [], 4.0, destination=far, max_routes=3)

    assert candidates == []
    assert generator.last_no_candidates_reason


async def test_a_destination_on_an_isolated_road_is_moved_to_the_nearest_reachable_node(engine_over):
    """指した先が本線とつながらない小塊だと、そこへ着く経路は無い。すぐ近くの本線へ移して、移したことを返す。"""
    generator = engine_over(grid_network(island=True))

    candidates = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], 4.0, destination=at(91), max_routes=3)

    assert candidates
    for candidate in candidates:
        assert_connected(candidate, SOUTH_WEST, NORTH_EAST)
    assert generator.last_destination_correction == at(NORTH_EAST)


async def test_a_spliced_route_that_does_not_start_or_end_where_asked_is_refused(engine_over):
    generator = engine_over(grid_network())
    (candidate, *_) = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], 4.0, destination=at(NORTH_EAST), max_routes=1)

    wrong_start = await generator.generate_spliced_route(at(CENTER), at(NORTH_EAST), 4.0, candidate.edge_ids)
    wrong_end = await generator.generate_spliced_route(at(SOUTH_WEST), at(SOUTH_EAST), 4.0, candidate.edge_ids)

    assert wrong_start == []
    assert wrong_end == []


# --- 区間の表示 ---


DEPARTURE = datetime(2026, 9, 22, 8, 10, tzinfo=JST)


async def test_segment_arrival_times_run_from_the_departure_within_the_duration(engine_over):
    """到達予想は探索と同じ時計で積む。最初の区間は出発時刻に始まり、どの区間も所要時間の内に入る。"""
    generator = engine_over(grid_network())

    (candidate, *_) = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], 4.0, destination=at(NORTH_EAST), max_routes=1, start_time=DEPARTURE)

    arrivals = [datetime.fromisoformat(s.estimated_arrival_time) for s in candidate.segments]
    assert arrivals[0] == DEPARTURE
    assert arrivals == sorted(set(arrivals))
    assert arrivals[-1] < DEPARTURE + timedelta(seconds=candidate.estimated_duration_seconds)


async def test_a_segment_without_data_does_not_show_the_axis_as_zero(engine_over):
    """データの無い区間に0を出すと、「データが無い」と「良い」が画面で区別できない。"""
    generator = engine_over(grid_network(unknown_ways={100}), avoid_weight=1.0)

    candidates = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], 3.0, destination=at(SOUTH_EAST), max_routes=3)

    fastest = next(c for c in candidates if c.is_fastest)
    first, second = fastest.segments
    assert AVOID_AXIS not in first.axis_difficulties
    assert second.axis_difficulties[AVOID_AXIS] == 0.0


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
        at(SOUTH_WEST), [], 4.0, destination=at(NORTH_EAST), max_routes=1,
        start_time=DEPARTURE.astimezone(timezone.utc))

    assert {s.wind.forecast_at for s in candidate.segments} == {"2026-09-22T08:00"}
    assert not any(s.wind.extended for s in candidate.segments)


async def test_segment_wind_beyond_the_forecast_is_marked_as_extended(engine_over):
    generator = engine_over(grid_network(), wind=_wind(HOURS_OF_THE_DAY[5:7], [3.0, 3.0, 3.0, 3.0]))

    (candidate, *_) = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], 4.0, destination=at(NORTH_EAST), max_routes=1, start_time=DEPARTURE)

    assert all(s.wind.extended for s in candidate.segments)


async def test_each_segment_takes_the_wind_of_the_grid_point_nearest_to_it(engine_over):
    """起点1か所の予報を全区間に使うと、海沿いや山で違う風になる。西の2点は弱い風、東の2点は強い風。"""
    generator = engine_over(grid_network(), wind=_wind(HOURS_OF_THE_DAY, [2.0, 8.0, 2.0, 8.0]))

    candidates = await generator.generate_via_waypoints(
        at(SOUTH_WEST), [], 3.0, destination=at(SOUTH_EAST), max_routes=3, start_time=DEPARTURE)

    fastest = next(c for c in candidates if c.is_fastest)
    assert [s.wind.speed_ms for s in fastest.segments] == [2.0, 8.0]


# --- 2点間の区間確認 ---


async def test_preview_follows_the_roads_between_two_points(preview_over):
    preview = preview_over(grid_network())

    segment = await preview(at(SOUTH_WEST), at(NORTH_EAST))

    assert segment is not None
    assert math.isclose(segment.distance_km, 4.0, abs_tol=0.1)
    # 探索用の区間は形を持たない。取り直した形で、4区間ぶんの折れ線になる。
    assert len(segment.geometry["coordinates"]) == 5


async def test_preview_is_none_when_an_end_is_far_from_every_road(preview_over):
    preview = preview_over(grid_network())

    far = Coordinates(latitude=BASE_LAT + 0.3, longitude=BASE_LON + 0.3)

    assert await preview(at(SOUTH_WEST), far) is None
