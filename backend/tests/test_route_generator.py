"""RouteGenerator（周回生成戦略、エンジン非依存）の単体テスト。

エンジンの中身（openrouteservice/Road Graph）は各エンジンのテスト
（test_openrouteservice_engine.py / test_road_graph_engine.py）で検証し、
ここでは戦略側の責務（経由地点の計算・距離許容範囲フィルタ・失敗方位のスキップ・
評価が生存候補だけに行われること・total_scoreソート）をFakeエンジンで検証する。
"""

from app.domain.errors import RoutingError
from app.domain.route import Coordinates, RouteCandidate
from app.services.route_generator import DIRECTIONS_DEG, RouteGenerator, TracedLoop, candidate_identity
from app.services.route_scorer import RouteScorer

ORIGIN = Coordinates(latitude=35.7597, longitude=139.7387)
SCORING_WEIGHTS = {"distance_weight": 0.30, "elevation_weight": 0.15, "wind_weight": 0.30, "road_weight": 0.25}


def make_geometry():
    return {"type": "LineString", "coordinates": [[139.7387, 35.7597], [139.75, 35.8]]}


class FakeEngine:
    """方位→距離（またはException）の対応を返すフェイクエンジン。

    trace_loopに渡されたwaypoints・evaluate_loopsに渡されたtracedを記録し、
    戦略側の呼び出し内容を検証できるようにする。
    """

    engine_name = "fake"

    def __init__(self, distances_by_bearing: dict[int, float | Exception], prepare_result: object = "ctx"):
        self._distances = distances_by_bearing
        self._prepare_result = prepare_result
        self.prepare_calls: list[tuple[Coordinates, float]] = []
        self.traced_waypoints: dict[int, list[Coordinates]] = {}
        self.evaluated_traced: list[TracedLoop] | None = None

    async def prepare(self, origin, radius_km):
        self.prepare_calls.append((origin, radius_km))
        return self._prepare_result

    async def trace_loop(self, context, waypoints, bearing):
        self.traced_waypoints[bearing] = waypoints
        outcome = self._distances[bearing]
        if isinstance(outcome, Exception):
            raise outcome
        return TracedLoop(bearing=bearing, distance_km=outcome, data=None)

    async def evaluate_loops(self, context, traced, start_time):
        self.evaluated_traced = traced
        return [
            RouteCandidate(
                **candidate_identity(t.bearing),
                distance_km=t.distance_km,
                geometry=make_geometry(),
            )
            for t in traced
        ]


def make_generator(distances_by_bearing, **kwargs) -> tuple[RouteGenerator, FakeEngine]:
    engine = FakeEngine(distances_by_bearing, **kwargs)
    return RouteGenerator(engine, RouteScorer(SCORING_WEIGHTS)), engine


async def test_generates_one_candidate_per_direction_when_all_within_tolerance():
    generator, _ = make_generator({b: 30.0 for b in DIRECTIONS_DEG})

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert len(candidates) == len(DIRECTIONS_DEG)
    assert {c.id for c in candidates} == {f"route-{b:03d}" for b in DIRECTIONS_DEG}


async def test_filters_out_candidates_outside_tolerance():
    distances = {b: 30.0 for b in DIRECTIONS_DEG}
    distances[0] = 50.0
    distances[90] = 10.0
    generator, _ = make_generator(distances)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    ids = [c.id for c in candidates]
    assert "route-000" not in ids
    assert "route-090" not in ids
    assert len(candidates) == len(DIRECTIONS_DEG) - 2


async def test_skips_directions_that_fail_without_raising():
    distances = {b: 30.0 for b in DIRECTIONS_DEG}
    distances[0] = RoutingError("no route")
    distances[135] = RoutingError("no route")
    generator, _ = make_generator(distances)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert len(candidates) == len(DIRECTIONS_DEG) - 2


async def test_returns_empty_list_when_prepare_returns_none():
    generator, engine = make_generator({b: 30.0 for b in DIRECTIONS_DEG}, prepare_result=None)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert candidates == []
    assert engine.evaluated_traced is None  # 評価まで進まない


async def test_evaluate_receives_only_survivors_sorted_by_distance_closeness():
    # 許容範囲外(50.0)は評価に渡らず、渡る候補は目標距離に近い順に並ぶ
    distances = {0: 50.0, 45: 33.0, 90: 30.5, 135: 36.0, 180: 29.0, 225: 30.0, 270: 31.0, 315: 34.0}
    generator, engine = make_generator(distances)

    await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert engine.evaluated_traced is not None
    assert all(t.bearing != 0 for t in engine.evaluated_traced)
    diffs = [abs(t.distance_km - 30.0) for t in engine.evaluated_traced]
    assert diffs == sorted(diffs)


async def test_evaluate_is_skipped_when_no_candidates_survive():
    generator, engine = make_generator({b: 100.0 for b in DIRECTIONS_DEG})

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert candidates == []
    assert engine.evaluated_traced is None


async def test_waypoints_form_a_loop_starting_and_ending_at_origin():
    generator, engine = make_generator({b: 30.0 for b in DIRECTIONS_DEG})

    await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    for bearing in DIRECTIONS_DEG:
        waypoints = engine.traced_waypoints[bearing]
        assert len(waypoints) == 4
        assert waypoints[0] == ORIGIN
        assert waypoints[-1] == ORIGIN
        assert waypoints[1] != ORIGIN and waypoints[2] != ORIGIN


async def test_sorts_final_candidates_by_total_score_descending():
    distances = {0: 33.0, 45: 30.0, 90: 27.0, 135: 34.0, 180: 26.0, 225: 30.0, 270: 30.0, 315: 30.0}
    generator, _ = make_generator(distances)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert all(c.total_score is not None for c in candidates)
    scores = [c.total_score for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_engine_name_is_exposed():
    generator, _ = make_generator({})

    assert generator.engine_name == "fake"
