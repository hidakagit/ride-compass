"""RouteGenerator（周回生成戦略、エンジン非依存）の単体テスト。

エンジンの中身はtest_road_graph_engine.pyで検証し、ここでは戦略側の責務
（経由地点の計算・距離許容範囲フィルタ・失敗方位のスキップ・評価が生存候補だけに
行われること・overall_difficulty昇順ソート）をFakeエンジンで検証する。
"""

from app.domain.errors import RouteDistanceExceededError, RoutingError
from app.domain.route import Coordinates, RouteCandidate, RouteSegmentDetail
from app.services.route_generator import DIRECTIONS_DEG, RouteGenerator, TracedLoop, candidate_identity

ORIGIN = Coordinates(latitude=35.7597, longitude=139.7387)


def make_geometry():
    return {"type": "LineString", "coordinates": [[139.7387, 35.7597], [139.75, 35.8]]}


class FakeEngine:
    """方位→距離（またはException）の対応を返すフェイクエンジン。

    trace_loopに渡されたwaypoints・evaluate_loopsに渡されたtracedを記録し、
    戦略側の呼び出し内容を検証できるようにする。
    """

    engine_name = "fake"

    def __init__(
        self, distances_by_bearing: dict[int | None, float | Exception], prepare_result: object = "ctx"
    ):
        self._distances = distances_by_bearing
        self._prepare_result = prepare_result
        self.prepare_calls: list[tuple[Coordinates, float]] = []
        self.prepare_waypoints: list[Coordinates] | None = None
        self.traced_waypoints: dict[int | None, list[Coordinates]] = {}
        # 改善計画T540: generate_loopsがtrace_loopへ渡すmax_distance_kmを方位ごとに
        # 記録する（配線の検証用）。
        self.traced_max_distance_km: dict[int | None, float | None] = {}
        self.evaluated_traced: list[TracedLoop] | None = None

    async def prepare(self, origin, radius_km, waypoints=None):
        self.prepare_calls.append((origin, radius_km))
        self.prepare_waypoints = waypoints
        return self._prepare_result

    async def trace_loop(self, context, waypoints, bearing, max_distance_km=None):
        self.traced_waypoints[bearing] = waypoints
        self.traced_max_distance_km[bearing] = max_distance_km
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
    return RouteGenerator(engine), engine


async def test_generates_one_candidate_per_direction_when_all_within_tolerance():
    generator, _ = make_generator({b: 30.0 for b in DIRECTIONS_DEG})

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert len(candidates) == len(DIRECTIONS_DEG)
    assert {c.id for c in candidates} == {f"route-{b:03d}" for b in DIRECTIONS_DEG}
    # 改善計画T441: 候補が得られたときはlast_no_candidates_reasonがNoneのままであること。
    assert generator.last_no_candidates_reason is None


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


async def test_generate_loops_passes_distance_upper_bound_to_trace_loop():
    # 改善計画T540: trace_loopへ渡すmax_distance_kmはdistance_km + distance_tolerance_km
    # （距離フィルタの上限と同じ値）であること。8方位すべてに同じ値が渡る。
    generator, engine = make_generator({b: 30.0 for b in DIRECTIONS_DEG})

    await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert engine.traced_max_distance_km == {b: 35.0 for b in DIRECTIONS_DEG}


async def test_generate_via_waypoints_does_not_pass_distance_upper_bound():
    # 改善計画T540: 経由地指定ルート（bearing=None）は距離フィルタ自体を行わないため、
    # max_distance_kmはNoneのまま渡る（早期打ち切りの対象外）。
    generator, engine = make_generator({None: 12.0})

    await generator.generate_via_waypoints(ORIGIN, waypoints=[WAYPOINT_A], distance_km=10.0)

    assert engine.traced_max_distance_km[None] is None


async def test_early_distance_cutoff_is_treated_same_as_post_hoc_distance_filter():
    # 改善計画T540: engine.trace_loopがRouteDistanceExceededError（早期打ち切り）を
    # raiseした方位は、全レグ完了後の距離フィルタで棄却された場合（RoutingErrorではなく
    # 単純に距離が範囲外のTracedLoopを返すケース）と同じ扱い（filtered_out集計・
    # no_candidates_reasonの文言）になることを確認する。
    distances = {b: 30.0 for b in DIRECTIONS_DEG}
    distances[0] = RouteDistanceExceededError("direction 0: distance exceeds tolerance")
    generator, _ = make_generator(distances)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    ids = [c.id for c in candidates]
    assert "route-000" not in ids
    assert len(candidates) == len(DIRECTIONS_DEG) - 1


async def test_early_distance_cutoff_reason_mentions_distance_not_trace_failure():
    # 改善計画T540: 全方位が早期打ち切りされた場合のno_candidates_reasonは、従来の
    # 距離フィルタ全滅時と同じ「距離」を含む文言になり、「経路探索に失敗」（RoutingErrorの
    # 文言）にはならない。
    distances = {
        b: RouteDistanceExceededError(f"direction {b}: distance exceeds tolerance") for b in DIRECTIONS_DEG
    }
    generator, _ = make_generator(distances)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert candidates == []
    assert generator.last_no_candidates_reason is not None
    assert "距離" in generator.last_no_candidates_reason
    assert "経路探索に失敗" not in generator.last_no_candidates_reason


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
    # 改善計画T441: 候補0件の原因がRouteGenerateResponse.no_candidates_reason経由でGUIへ
    # 届くよう、人間可読な理由をlast_no_candidates_reasonへ残す。
    assert generator.last_no_candidates_reason is not None
    assert "道路データ" in generator.last_no_candidates_reason


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
    # 改善計画T441: 全方位が距離フィルタで落ちたケースの理由を確認する
    # （trace自体は成功しているため「経路探索に失敗」ではなく距離条件の文言になること）。
    assert generator.last_no_candidates_reason is not None
    assert "距離" in generator.last_no_candidates_reason
    assert "経路探索に失敗" not in generator.last_no_candidates_reason


async def test_no_candidates_reason_mentions_trace_failures_when_all_directions_fail():
    generator, _ = make_generator({b: RoutingError("no route") for b in DIRECTIONS_DEG})

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert candidates == []
    assert generator.last_no_candidates_reason is not None
    assert "経路探索に失敗" in generator.last_no_candidates_reason


async def test_waypoints_form_a_loop_starting_and_ending_at_origin():
    generator, engine = make_generator({b: 30.0 for b in DIRECTIONS_DEG})

    await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    for bearing in DIRECTIONS_DEG:
        waypoints = engine.traced_waypoints[bearing]
        assert len(waypoints) == 4
        assert waypoints[0] == ORIGIN
        assert waypoints[-1] == ORIGIN
        assert waypoints[1] != ORIGIN and waypoints[2] != ORIGIN


async def test_sorts_final_candidates_by_overall_difficulty_ascending():
    # 改善計画T548: 候補タブの並び順はoverall_difficulty（絶対基準0-100の総合難易度）
    # 昇順（易しい候補が先頭）。
    engine = SegmentedFakeEngine(
        {0: 33.0, 45: 30.0, 90: 27.0},
        {
            0: [make_segment(1.0, 80.0)],
            45: [make_segment(1.0, 20.0)],
            90: [make_segment(1.0, 50.0)],
        },
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    difficulties = [c.overall_difficulty for c in candidates]
    assert all(d is not None for d in difficulties)
    assert difficulties == sorted(difficulties)
    assert difficulties[0] == 20.0


async def test_candidates_with_none_overall_difficulty_sort_last():
    # 改善計画T548: overall_difficultyがNone（算出不能）の候補は末尾へ回す。
    engine = SegmentedFakeEngine(
        {0: 33.0, 45: 30.0},
        {45: [make_segment(1.0, 20.0)]},  # bearing=0はsegments無し→overall_difficulty=None
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert candidates[-1].overall_difficulty is None


def test_engine_name_is_exposed():
    generator, _ = make_generator({})

    assert generator.engine_name == "fake"


def make_segment(
    distance_km: float,
    difficulty: float | None,
    axis_difficulties: dict[str, float] | None = None,
) -> RouteSegmentDetail:
    return RouteSegmentDetail(
        start_latitude=35.0,
        start_longitude=139.0,
        end_latitude=35.01,
        end_longitude=139.01,
        cumulative_distance_km=distance_km,
        distance_km=distance_km,
        difficulty=difficulty,
        axis_difficulties=axis_difficulties or {},
    )


class SegmentedFakeEngine(FakeEngine):
    """evaluate_loopsがsegments付きのRouteCandidateを返すフェイクエンジン
    （overall_difficultyの配線をエンジン非依存側で検証するため）。"""

    def __init__(self, distances_by_bearing, segments_by_bearing, **kwargs):
        super().__init__(distances_by_bearing, **kwargs)
        self._segments_by_bearing = segments_by_bearing

    async def evaluate_loops(self, context, traced, start_time):
        self.evaluated_traced = traced
        return [
            RouteCandidate(
                **candidate_identity(t.bearing),
                distance_km=t.distance_km,
                geometry=make_geometry(),
                segments=self._segments_by_bearing.get(t.bearing),
            )
            for t in traced
        ]


async def test_overall_difficulty_is_distance_weighted_average_of_segments():
    engine = SegmentedFakeEngine(
        {0: 30.0},
        {0: [make_segment(1.0, 0.0), make_segment(3.0, 100.0)]},
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert candidates[0].overall_difficulty == 75.0


async def test_overall_difficulty_is_none_when_segments_missing():
    generator, _ = make_generator({b: 30.0 for b in DIRECTIONS_DEG})

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert all(c.overall_difficulty is None for c in candidates)


async def test_axis_difficulties_is_distance_weighted_average_of_segments():
    # 改善計画T402: RouteCandidate.axis_difficultiesはoverall_difficultyと対の
    # ルート全体集約値。merge_axis_difficultiesを候補の全区間へ1回適用するだけで
    # 得られることを、エンジン非依存側（RouteGenerator）の配線として検証する。
    engine = SegmentedFakeEngine(
        {0: 30.0},
        {
            0: [
                make_segment(1.0, 0.0, axis_difficulties={"wind": 80.0, "car_stress": 10.0}),
                make_segment(3.0, 100.0, axis_difficulties={"wind": 20.0}),
            ]
        },
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    # wind: (80*1.0 + 20*3.0) / 4.0 = 35.0
    assert candidates[0].axis_difficulties["wind"] == 35.0
    # car_stressは片方の区間にしか無いため、持つ区間だけで平均され10.0のまま
    assert candidates[0].axis_difficulties["car_stress"] == 10.0


async def test_axis_difficulties_is_empty_dict_when_segments_missing():
    generator, _ = make_generator({b: 30.0 for b in DIRECTIONS_DEG})

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert all(c.axis_difficulties == {} for c in candidates)


WAYPOINT_A = Coordinates(latitude=35.80, longitude=139.75)
WAYPOINT_B = Coordinates(latitude=35.82, longitude=139.77)


async def test_generate_via_waypoints_traces_full_loop_in_order():
    generator, engine = make_generator({None: 12.0})

    candidates = await generator.generate_via_waypoints(
        ORIGIN, waypoints=[WAYPOINT_A, WAYPOINT_B], distance_km=10.0
    )

    assert engine.traced_waypoints[None] == [ORIGIN, WAYPOINT_A, WAYPOINT_B, ORIGIN]
    assert engine.prepare_waypoints == [WAYPOINT_A, WAYPOINT_B]
    assert len(candidates) == 1
    assert candidates[0].id == "route-waypoints"


async def test_generate_via_waypoints_returns_empty_when_prepare_returns_none():
    generator, engine = make_generator({None: 12.0}, prepare_result=None)

    candidates = await generator.generate_via_waypoints(ORIGIN, waypoints=[WAYPOINT_A], distance_km=10.0)

    assert candidates == []
    assert engine.evaluated_traced is None
    # 改善計画T441
    assert generator.last_no_candidates_reason is not None
    assert "道路データ" in generator.last_no_candidates_reason


async def test_generate_via_waypoints_returns_empty_when_trace_fails():
    generator, _ = make_generator({None: RoutingError("no route")})

    candidates = await generator.generate_via_waypoints(ORIGIN, waypoints=[WAYPOINT_A], distance_km=10.0)

    assert candidates == []
    # 改善計画T441
    assert generator.last_no_candidates_reason is not None
    assert "経由地" in generator.last_no_candidates_reason


DESTINATION = Coordinates(latitude=35.90, longitude=139.80)


async def test_generate_via_waypoints_with_destination_ends_at_destination_not_origin():
    generator, engine = make_generator({None: 20.0})

    candidates = await generator.generate_via_waypoints(
        ORIGIN, waypoints=[WAYPOINT_A], distance_km=10.0, destination=DESTINATION
    )

    # 改善計画T365: 終点は起点ではなく指定した目的地になる（末尾に起点を足し戻さない）。
    assert engine.traced_waypoints[None] == [ORIGIN, WAYPOINT_A, DESTINATION]
    # bboxがdestinationも覆うよう、prepareへ渡す点集合にdestinationを含める。
    assert engine.prepare_waypoints == [WAYPOINT_A, DESTINATION]
    assert len(candidates) == 1
    assert candidates[0].id == "route-destination"
    assert candidates[0].direction_label == "目的地ルート"


async def test_generate_via_waypoints_destination_only_without_intermediate_waypoints():
    generator, engine = make_generator({None: 20.0})

    candidates = await generator.generate_via_waypoints(
        ORIGIN, waypoints=[], distance_km=10.0, destination=DESTINATION
    )

    assert engine.traced_waypoints[None] == [ORIGIN, DESTINATION]
    assert len(candidates) == 1
    assert candidates[0].id == "route-destination"


async def test_generate_via_waypoints_without_destination_still_loops_back_to_origin():
    generator, engine = make_generator({None: 12.0})

    candidates = await generator.generate_via_waypoints(ORIGIN, waypoints=[WAYPOINT_A], distance_km=10.0)

    assert engine.traced_waypoints[None][-1] == ORIGIN
    assert candidates[0].id == "route-waypoints"


async def test_generate_via_waypoints_also_aggregates_axis_difficulties():
    # 改善計画T402: axis_difficultiesの集約はgenerate_loopsだけでなく
    # generate_via_waypoints側でも同じく行われる（両呼び出し元で_with_axis_difficultiesを
    # 呼ぶ配線の検証）。
    engine = SegmentedFakeEngine(
        {None: 12.0},
        {None: [make_segment(2.0, 0.0, axis_difficulties={"wind": 40.0})]},
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_via_waypoints(ORIGIN, waypoints=[WAYPOINT_A], distance_km=10.0)

    assert candidates[0].axis_difficulties == {"wind": 40.0}
