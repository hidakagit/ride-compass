"""RouteGenerator（周回生成戦略、エンジン非依存）の単体テスト。

エンジンの中身はtest_road_graph_engine.pyで検証し、ここでは戦略側の責務
（折返し候補の逐次処理と早期停止・距離許容範囲フィルタ・失敗候補のスキップ・評価が
生存候補だけに行われること・overall_difficulty昇順ソートと同点時の距離近さ順・
max_routesによるスライスとid再採番）をFakeエンジンで検証する。
"""

import pytest

from app.domain.errors import RoutingError
from app.domain.geo import compass_label
from app.domain.route import Coordinates, RouteCandidate, RouteSegmentDetail
from app.services.route_generator import (
    LoopTurnaround,
    RouteGenerator,
    TracedLoop,
    candidate_identity,
    turnaround_pool_size,
)

ORIGIN = Coordinates(latitude=35.7597, longitude=139.7387)
# テスト用の折返し候補の方位（旧8方位方式の名残ではなく、FakeEngineが返す候補を区別する
# ためのラベル。方位は生成機構ではなく表示ラベルにしか使わない、改善計画T531）。
BEARINGS = [0, 45, 90, 135, 180, 225, 270, 315]


def make_geometry():
    return {"type": "LineString", "coordinates": [[139.7387, 35.7597], [139.75, 35.8]]}


class FakeEngine:
    """方位→距離（またはException）の対応から折返し候補・周回を返すフェイクエンジン。

    select_loop_turnarounds/trace_loop_from_turnaround/trace_loop/evaluate_loopsへ渡された
    引数を記録し、戦略側の呼び出し内容を検証できるようにする。
    """

    engine_name = "fake"

    def __init__(
        self,
        distances_by_bearing: dict[int | None, float | Exception],
        prepare_result: object = "ctx",
        too_similar_bearings: set[int | None] = frozenset(),
    ):
        self._distances = distances_by_bearing
        self._prepare_result = prepare_result
        # 改善計画T553: is_loop_too_similarがTrueを返すべき候補のbearing集合
        # （テストが明示的に指定した場合のみ。既定は空＝常にFalse）。
        self._too_similar_bearings = too_similar_bearings
        self.prepare_calls: list[tuple[Coordinates, float]] = []
        self.prepare_waypoints: list[Coordinates] | None = None
        self.select_calls: list[tuple[float, float, int]] = []
        self.traced_bearings: list[int] = []
        self.traced_waypoints: dict[int | None, list[Coordinates]] = {}
        self.evaluated_traced: list[TracedLoop] | None = None
        # 改善計画T553: is_loop_too_similar呼び出しを記録する
        # （candidate.bearing, [acceptedのbearing一覧]）のタプル列。
        self.similarity_calls: list[tuple[int | None, list[int | None]]] = []

    async def prepare(self, origin, radius_km, waypoints=None):
        self.prepare_calls.append((origin, radius_km))
        self.prepare_waypoints = waypoints
        return self._prepare_result

    async def select_loop_turnarounds(self, context, distance_km, distance_tolerance_km, pool_size):
        self.select_calls.append((distance_km, distance_tolerance_km, pool_size))
        bearings = [b for b in self._distances if b is not None]
        return [
            LoopTurnaround(bearing=b, outbound_difficulty=None, data=None)
            for b in bearings
        ][:pool_size]

    async def trace_loop_from_turnaround(self, context, turnaround):
        self.traced_bearings.append(turnaround.bearing)
        outcome = self._distances[turnaround.bearing]
        if isinstance(outcome, Exception):
            raise outcome
        return TracedLoop(bearing=turnaround.bearing, distance_km=outcome, data=None)

    async def trace_loop(self, context, waypoints, bearing):
        self.traced_waypoints[bearing] = waypoints
        outcome = self._distances[bearing]
        if isinstance(outcome, Exception):
            raise outcome
        return TracedLoop(bearing=bearing, distance_km=outcome, data=None)

    def is_loop_too_similar(self, context, candidate, accepted):
        self.similarity_calls.append((candidate.bearing, [t.bearing for t in accepted]))
        return candidate.bearing in self._too_similar_bearings

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


def _labels(candidates: list[RouteCandidate]) -> list[str]:
    return [c.direction_label for c in candidates]


async def test_generates_one_candidate_per_turnaround_when_all_within_tolerance():
    generator, _ = make_generator({b: 30.0 for b in BEARINGS})

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert len(candidates) == len(BEARINGS)
    # 改善計画T531: idは最終順位で振り直す（方位由来のidではない）。方位ラベルはエンジンの値のまま。
    assert [c.id for c in candidates] == [f"route-{i:02d}" for i in range(len(BEARINGS))]
    assert set(_labels(candidates)) == {compass_label(b) for b in BEARINGS}
    # 改善計画T441: 候補が得られたときはlast_no_candidates_reasonがNoneのままであること。
    assert generator.last_no_candidates_reason is None


async def test_filters_out_candidates_outside_tolerance():
    distances = {b: 30.0 for b in BEARINGS}
    distances[0] = 50.0
    distances[90] = 10.0
    generator, _ = make_generator(distances)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    labels = _labels(candidates)
    assert compass_label(0) not in labels
    assert compass_label(90) not in labels
    assert len(candidates) == len(BEARINGS) - 2


async def test_generate_loops_requests_turnaround_pool_sized_from_max_routes():
    # 改善計画T531: 折返し候補のプール件数はmax_routesから導出し（turnaround_pool_size）、
    # 距離・許容差とともにエンジンへ渡す。
    generator, engine = make_generator({b: 30.0 for b in BEARINGS})

    await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0, max_routes=4)

    assert engine.select_calls == [(30.0, 5.0, turnaround_pool_size(4))]


async def test_generate_loops_stops_tracing_once_max_routes_are_accepted():
    # 改善計画T531: 候補はランク順に逐次処理し、距離フィルタ合格がmax_routes件に達した
    # 時点で残りの候補の復路探索を行わない。
    generator, engine = make_generator({b: 30.0 for b in BEARINGS})

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0, max_routes=3)

    assert len(candidates) == 3
    assert engine.traced_bearings == BEARINGS[:3]
    assert [c.id for c in candidates] == ["route-00", "route-01", "route-02"]


async def test_generate_loops_keeps_tracing_past_rejected_candidates_until_max_routes():
    # 距離フィルタで落ちた候補・失敗した候補は合格数に数えず、次の候補へ進む。
    distances = {0: 60.0, 45: RoutingError("no return"), 90: 30.0, 135: 31.0, 180: 30.0, 225: 30.0}
    generator, engine = make_generator(distances)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0, max_routes=2)

    assert engine.traced_bearings == [0, 45, 90, 135]
    assert set(_labels(candidates)) == {compass_label(90), compass_label(135)}


async def test_generate_loops_skips_candidates_engine_reports_as_too_similar():
    # 改善計画T553: 距離フィルタ合格後、is_loop_too_similarがTrueを返す候補は採用せず
    # 次の候補へ進む。早期停止のmax_routesカウントもこのチェックを通過した候補数で数える
    # （棄却された候補ぶん、より多くの折返し候補が復路探索される）。
    generator, engine = make_generator({b: 30.0 for b in BEARINGS}, too_similar_bearings={45, 90})

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0, max_routes=3)

    assert len(candidates) == 3
    # 45・90は重複棄却されるため、代わりに135・180まで復路探索が進む。
    assert engine.traced_bearings == [0, 45, 90, 135, 180]
    assert set(_labels(candidates)) == {compass_label(0), compass_label(135), compass_label(180)}


async def test_generate_loops_checks_similarity_only_against_already_accepted_candidates():
    # is_loop_too_similarは「これまでに採用済みの候補」とだけ比較する（棄却された候補や
    # 未処理の候補とは比較しない）。最初の候補は比較対象が無いため呼ばれない。
    generator, engine = make_generator({b: 30.0 for b in BEARINGS[:3]})

    await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0, max_routes=3)

    assert engine.similarity_calls == [
        (45, [0]),
        (90, [0, 45]),
    ]


async def test_generate_loops_returns_empty_with_reason_when_no_turnaround_candidates():
    generator, engine = make_generator({})

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert candidates == []
    assert engine.evaluated_traced is None
    assert generator.last_no_candidates_reason is not None
    assert "折返し" in generator.last_no_candidates_reason


async def test_generate_via_waypoints_does_not_select_turnarounds():
    # 経由地指定ルートは折返し候補の選定・距離フィルタを通らない（指定地点列を結ぶだけ）。
    generator, engine = make_generator({None: 12.0})

    await generator.generate_via_waypoints(ORIGIN, waypoints=[WAYPOINT_A], distance_km=10.0)

    assert engine.select_calls == []
    assert engine.traced_bearings == []


async def test_skips_turnarounds_that_fail_without_raising():
    distances = {b: 30.0 for b in BEARINGS}
    distances[0] = RoutingError("no route")
    distances[135] = RoutingError("no route")
    generator, _ = make_generator(distances)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert len(candidates) == len(BEARINGS) - 2


async def test_returns_empty_list_when_prepare_returns_none():
    generator, engine = make_generator({b: 30.0 for b in BEARINGS}, prepare_result=None)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert candidates == []
    assert engine.evaluated_traced is None  # 評価まで進まない
    assert engine.select_calls == []
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
    generator, engine = make_generator({b: 100.0 for b in BEARINGS})

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert candidates == []
    assert engine.evaluated_traced is None
    # 改善計画T441: 全候補が距離フィルタで落ちたケースの理由を確認する
    # （trace自体は成功しているため「探索に失敗」ではなく距離条件の文言になること）。
    assert generator.last_no_candidates_reason is not None
    assert "距離" in generator.last_no_candidates_reason
    assert "探索に失敗" not in generator.last_no_candidates_reason


async def test_no_candidates_reason_mentions_trace_failures_when_all_turnarounds_fail():
    generator, _ = make_generator({b: RoutingError("no route") for b in BEARINGS})

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert candidates == []
    assert generator.last_no_candidates_reason is not None
    assert "探索に失敗" in generator.last_no_candidates_reason


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
    assert [c.id for c in candidates] == ["route-00", "route-01", "route-02"]


async def test_candidates_with_equal_difficulty_are_ordered_by_distance_closeness():
    # 改善計画T531: overall_difficultyが同点（小数1桁）の候補は目標距離に近い順に並ぶ
    # （周囲に重みを振った軸のデータが無く全候補が同じdifficultyになる状況で、結果が
    # 実質的に目標距離に近い順になる）。
    engine = SegmentedFakeEngine(
        {0: 34.0, 45: 30.5, 90: 27.0},
        {b: [make_segment(1.0, 100.0)] for b in (0, 45, 90)},
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert _labels(candidates) == [compass_label(45), compass_label(90), compass_label(0)]


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
    axis_contributions: dict[str, float] | None = None,
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
        axis_contributions=axis_contributions or {},
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
    generator, _ = make_generator({b: 30.0 for b in BEARINGS})

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
    generator, _ = make_generator({b: 30.0 for b in BEARINGS})

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert all(c.axis_difficulties == {} for c in candidates)


async def test_axis_contributions_is_distance_weighted_average_of_segments():
    # 改善計画T550: RouteCandidate.axis_contributionsはaxis_difficultiesと同じ集約方法
    # （merge_axis_contributions、distance_weighted_difficulty）で候補全区間へ集約される。
    engine = SegmentedFakeEngine(
        {0: 30.0},
        {
            0: [
                make_segment(1.0, 0.0, axis_contributions={"wind": 80.0, "car_stress": 10.0}),
                make_segment(3.0, 100.0, axis_contributions={"wind": 20.0}),
            ]
        },
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    # wind: (80*1.0 + 20*3.0) / 4.0 = 35.0
    assert candidates[0].axis_contributions["wind"] == 35.0
    # car_stressは片方の区間にしか無いため、持つ区間だけで平均され10.0のまま
    assert candidates[0].axis_contributions["car_stress"] == 10.0


async def test_axis_contributions_is_empty_dict_when_segments_missing():
    generator, _ = make_generator({b: 30.0 for b in BEARINGS})

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert all(c.axis_contributions == {} for c in candidates)


async def test_axis_contributions_sum_matches_overall_difficulty():
    # 改善計画T550の不変条件: sum(axis_contributions.values())は丸め誤差を除いて
    # overall_difficultyと一致する（domain/evaluation.py:
    # compose_costs_from_axis_matrixのdocstring参照）。各区間のaxis_contributionsの
    # 合計をその区間のdifficultyと一致させて用意し（compose_costs_from_axis_matrixが
    # 満たす関係と同じ）、ルート単位に集約した後もこの関係が保たれることを確認する。
    engine = SegmentedFakeEngine(
        {0: 30.0},
        {
            0: [
                make_segment(
                    1.0, 60.0,
                    axis_contributions={"wind": 40.0, "car_stress": 20.0},
                ),
                make_segment(
                    3.0, 30.0,
                    axis_contributions={"wind": 10.0, "car_stress": 20.0},
                ),
            ]
        },
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    candidate = candidates[0]
    assert candidate.overall_difficulty == pytest.approx(37.5)
    assert sum(candidate.axis_contributions.values()) == pytest.approx(
        candidate.overall_difficulty, abs=0.1
    )


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


async def test_generate_via_waypoints_also_aggregates_axis_contributions():
    # 改善計画T550: axis_contributionsの集約もaxis_difficultiesと同じく
    # generate_via_waypoints側で行われる（両呼び出し元で_with_axis_contributionsを
    # 呼ぶ配線の検証）。
    engine = SegmentedFakeEngine(
        {None: 12.0},
        {None: [make_segment(2.0, 0.0, axis_contributions={"wind": 40.0})]},
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_via_waypoints(ORIGIN, waypoints=[WAYPOINT_A], distance_km=10.0)

    assert candidates[0].axis_contributions == {"wind": 40.0}
