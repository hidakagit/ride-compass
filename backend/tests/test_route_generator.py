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
from app.domain.loop_routing import LoopTurnaround, TracedLoop, candidate_identity
from app.services.route_generator import RouteGenerator

ORIGIN = Coordinates(latitude=35.7597, longitude=139.7387)
# テスト用の折返し候補の方位（旧8方位方式の名残ではなく、FakeEngineが返す候補を区別する
# ためのラベル。方位は生成機構ではなく表示ラベルにしか使わない）。
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
        via_node_distances: list[float] | None = None,
        destination_correction: Coordinates | None = None,
        fastest_distance_km: float | None = None,
        build_traced_error: Exception | None = None,
    ):
        self._distances = distances_by_bearing
        self._prepare_result = prepare_result
        # select_via_nodesが目的地を補正した体を取るテスト用（prepareが返す
        # contextは既定で不変のstr "ctx" のため、補正を検証するテストは可変なオブジェクトを
        # prepare_resultへ渡す必要がある）。
        self._destination_correction = destination_correction
        # is_loop_too_similarがTrueを返すべき候補のbearing集合
        # （テストが明示的に指定した場合のみ。既定は空＝常にFalse）。
        self._too_similar_bearings = too_similar_bearings
        # select_via_nodesが返す候補の距離列。省略時はdistances_by_bearing[None]
        # （bearing=None、Exceptionでなければ）を1件だけ返す後方互換の既定値にする——
        # 経由地・目的地指定ルートの既存テストの大半はこの1件だけを見ているため。
        self._via_node_distances = via_node_distances
        # 基準線（所要時間が最短の経路）の距離。Noneは「基準線を求められなかった」を表す
        # （既定。既存テストの候補数・並び順を変えないため）。
        self._fastest_distance_km = fastest_distance_km
        # build_traced_from_edge_idsが送られた列を成立しないと判定した体を取るテスト用。
        self._build_traced_error = build_traced_error
        self.build_traced_calls: list[list[str]] = []
        self.build_traced_destinations: list[object] = []
        self.prepare_calls: list[tuple[Coordinates, float]] = []
        self.prepare_waypoints: list[Coordinates] | None = None
        self.select_calls: list[tuple[float, float, int]] = []
        self.select_via_nodes_calls: list[tuple[Coordinates, int]] = []
        self.traced_bearings: list[int] = []
        self.traced_waypoints: dict[int | None, list[Coordinates]] = {}
        self.evaluated_traced: list[TracedLoop] | None = None
        # is_loop_too_similar呼び出しを記録する
        # （candidate.bearing, [acceptedのbearing一覧]）のタプル列。
        self.similarity_calls: list[tuple[int | None, list[int | None]]] = []

    async def prepare(self, origin, radius_km, waypoints=None, now=None):
        self.prepare_calls.append((origin, radius_km))
        self.prepare_waypoints = waypoints
        return self._prepare_result

    async def select_via_nodes(self, context, destination, max_routes):
        self.select_via_nodes_calls.append((destination, max_routes))
        if self._destination_correction is not None:
            context.destination_correction = self._destination_correction
        distances = self._via_node_distances
        if distances is None:
            outcome = self._distances.get(None)
            distances = [] if outcome is None or isinstance(outcome, Exception) else [outcome]
        return [TracedLoop(bearing=None, distance_km=d, data=[f"e{d}"], leg_of_edge=[0]) for d in distances[:max_routes]]

    async def select_fastest_route(self, context, destination):
        if self._fastest_distance_km is None:
            return None
        d = self._fastest_distance_km
        return TracedLoop(bearing=None, distance_km=d, data=[f"e{d}"], leg_of_edge=[0])

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
        return TracedLoop(bearing=turnaround.bearing, distance_km=outcome, data=None, leg_of_edge=[0])

    async def trace_loop(self, context, waypoints, bearing):
        self.traced_waypoints[bearing] = waypoints
        outcome = self._distances[bearing]
        if isinstance(outcome, Exception):
            raise outcome
        return TracedLoop(bearing=bearing, distance_km=outcome, data=None, leg_of_edge=[0])

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

    def build_traced_from_edge_ids(self, context, edge_ids, destination=None):
        self.build_traced_calls.append(edge_ids)
        self.build_traced_destinations.append(destination)
        if self._build_traced_error is not None:
            raise self._build_traced_error
        return TracedLoop(
            bearing=None, distance_km=len(edge_ids) * 1.0, data=list(edge_ids),
            leg_of_edge=[0] * len(edge_ids),
        )


def make_generator(distances_by_bearing, **kwargs) -> tuple[RouteGenerator, FakeEngine]:
    engine = FakeEngine(distances_by_bearing, **kwargs)
    return RouteGenerator(engine), engine


def _labels(candidates: list[RouteCandidate]) -> list[str]:
    return [c.direction_label for c in candidates]


async def test_sorts_final_candidates_by_overall_difficulty_ascending():
    # 候補タブの並び順はoverall_difficulty（絶対基準0-100の総合難易度）
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
    # overall_difficultyが同点（小数1桁）の候補は目標距離に近い順に並ぶ
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
    # overall_difficultyがNone（算出不能）の候補は末尾へ回す。
    engine = SegmentedFakeEngine(
        {0: 33.0, 45: 30.0},
        {45: [make_segment(1.0, 20.0)]},  # bearing=0はsegments無し→overall_difficulty=None
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert candidates[-1].overall_difficulty is None


def make_segment(
    distance_km: float,
    difficulty: float | None,
    axis_difficulties: dict[str, float] | None = None,
    axis_contributions: dict[str, float] | None = None,
    axis_raw_values: dict[str, float] | None = None,
    material_values: dict[str, float] | None = None,
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
        axis_raw_values=axis_raw_values or {},
        material_values=material_values or {},
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


async def test_axis_difficulties_is_distance_weighted_average_of_segments():
    # RouteCandidate.axis_difficultiesはoverall_difficultyと対の
    # ルート全体集約値。merge_axis_difficultiesを候補の全区間へ1回適用するだけで
    # 得られることを、エンジン非依存側（RouteGenerator）の配線として検証する。
    engine = SegmentedFakeEngine(
        {0: 30.0},
        {
            0: [
                make_segment(1.0, 0.0, axis_difficulties={"wind": 80.0, "axis_b": 10.0}),
                make_segment(3.0, 100.0, axis_difficulties={"wind": 20.0}),
            ]
        },
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    # wind: (80*1.0 + 20*3.0) / 4.0 = 35.0
    assert candidates[0].axis_difficulties["wind"] == 35.0
    # axis_bは片方の区間にしか無いため、持つ区間だけで平均され10.0のまま
    assert candidates[0].axis_difficulties["axis_b"] == 10.0


async def test_axis_raw_values_is_distance_weighted_average_of_segments():
    # 生値もaxis_difficultiesと同じ集約でルート全体へ載る。得点と違い上限が無く、
    # 「◯◯/km」なら走行距離を掛けて経路全体の実数にできる。
    engine = SegmentedFakeEngine(
        {0: 30.0},
        {
            0: [
                make_segment(1.0, 0.0, axis_raw_values={"stop_density": 4.0}),
                make_segment(3.0, 100.0, axis_raw_values={"stop_density": 0.0}),
            ]
        },
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    # (4.0*1.0 + 0.0*3.0) / 4.0 = 1.0回/km
    assert candidates[0].axis_raw_values["stop_density"] == 1.0


async def test_axis_raw_values_keep_precision_for_small_scale_axes():
    """ルート全体へ載せる段でも、桁の小さい軸の値が潰れないこと。

    区間の集約（`aggregate_segments_into_bins`）側は`tests/test_route.py`が押さえているが、
    ここは候補1本ぶんへまとめる別の経路（`merge_axis_raw_values`）。有効域が0〜0.5の
    `accident`（件/(km・年)）は、小数1桁へ丸めると0.05未満が全部0.0になり
    「事故ゼロの道」と見分けが付かなくなる。
    """
    engine = SegmentedFakeEngine(
        {0: 30.0},
        {
            0: [
                make_segment(1.0, 0.0, axis_raw_values={"accident": 0.042}),
                make_segment(3.0, 100.0, axis_raw_values={"accident": 0.018}),
            ]
        },
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    # (0.042*1.0 + 0.018*3.0) / 4.0 = 0.024
    assert candidates[0].axis_raw_values["accident"] == pytest.approx(0.024)


async def test_axis_contributions_is_distance_weighted_average_of_segments():
    # RouteCandidate.axis_contributionsはaxis_difficultiesと同じ集約方法
    # （merge_axis_contributions、distance_weighted_difficulty）で候補全区間へ集約される。
    engine = SegmentedFakeEngine(
        {0: 30.0},
        {
            0: [
                make_segment(1.0, 0.0, axis_contributions={"wind": 80.0, "axis_b": 10.0}),
                make_segment(3.0, 100.0, axis_contributions={"wind": 20.0}),
            ]
        },
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    # wind: (80*1.0 + 20*3.0) / 4.0 = 35.0
    assert candidates[0].axis_contributions["wind"] == 35.0
    # axis_bは片方の区間にしか無いため、持つ区間だけで平均され10.0のまま
    assert candidates[0].axis_contributions["axis_b"] == 10.0


async def test_material_values_is_distance_weighted_average_of_segments():
    # RouteCandidate.material_valuesはaxis_difficulties/axis_contributionsと
    # 同じ集約方法（merge_material_values、distance_weighted_difficulty）で候補全区間へ
    # 集約される。
    engine = SegmentedFakeEngine(
        {0: 30.0},
        {
            0: [
                make_segment(1.0, 0.0, material_values={"wind_drag_ratio": 8.0}),
                make_segment(3.0, 100.0, material_values={"wind_drag_ratio": 4.0}),
            ]
        },
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    # wind_drag_ratio: (8*1.0 + 4*3.0) / 4.0 = 5.0
    assert candidates[0].material_values["wind_drag_ratio"] == 5.0


async def test_axis_contributions_sum_matches_overall_difficulty():
    # sum(axis_contributions.values())は丸め誤差を除いて
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
                    axis_contributions={"wind": 40.0, "axis_b": 20.0},
                ),
                make_segment(
                    3.0, 30.0,
                    axis_contributions={"wind": 10.0, "axis_b": 20.0},
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


DESTINATION = Coordinates(latitude=35.90, longitude=139.80)


class DestinationSegmentedFakeEngine(FakeEngine):
    """destinationルート（bearingが常にNone）向けのsegments注入フェイク。SegmentedFakeEngine
    はsegmentsをbearingキーで引くため、bearingが常にNoneになる目的地ルート候補同士を
    区別できない——代わりにTracedLoop.dataの値をキーにする。"""

    def __init__(
        self,
        via_node_traced: list[TracedLoop],
        segments_by_data: dict,
        fastest_traced: TracedLoop | None = None,
        **kwargs,
    ):
        super().__init__({}, **kwargs)
        self._via_node_traced = via_node_traced
        self._segments_by_data = segments_by_data
        # 基準線（所要時間が最短の経路）。Noneは「求められなかった」（既定）。
        self._fastest_traced = fastest_traced

    async def select_via_nodes(self, context, destination, max_routes):
        self.select_via_nodes_calls.append((destination, max_routes))
        return self._via_node_traced[:max_routes]

    async def select_fastest_route(self, context, destination):
        return self._fastest_traced

    async def evaluate_loops(self, context, traced, start_time):
        self.evaluated_traced = traced
        return [
            RouteCandidate(
                **candidate_identity(t.bearing),
                distance_km=t.distance_km,
                geometry=make_geometry(),
                segments=self._segments_by_data.get(t.data),
            )
            for t in traced
        ]


async def test_generate_destination_routes_sorts_by_overall_difficulty():
    # 最終順位（id採番の順）がoverall_difficulty昇順になることを検証する
    # （generate_loopsのT548ソート規約と同じロジックを共有している）。
    engine = DestinationSegmentedFakeEngine(
        via_node_traced=[
            TracedLoop(bearing=None, distance_km=20.0, data="hard", leg_of_edge=[0]),
            TracedLoop(bearing=None, distance_km=19.0, data="easy", leg_of_edge=[0]),
        ],
        segments_by_data={
            "hard": [make_segment(20.0, 80.0)],
            "easy": [make_segment(19.0, 10.0)],
        },
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_via_waypoints(
        ORIGIN, waypoints=[], distance_km=10.0, destination=DESTINATION, max_routes=2
    )

    assert [c.distance_km for c in candidates] == [19.0, 20.0]
    assert [c.id for c in candidates] == ["route-destination-00", "route-destination-01"]


async def test_generate_via_waypoints_also_aggregates_axis_difficulties():
    # axis_difficultiesの集約はgenerate_loopsだけでなく
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
    # axis_contributionsの集約もaxis_difficultiesと同じく
    # generate_via_waypoints側で行われる（両呼び出し元で_with_axis_contributionsを
    # 呼ぶ配線の検証）。
    engine = SegmentedFakeEngine(
        {None: 12.0},
        {None: [make_segment(2.0, 0.0, axis_contributions={"wind": 40.0})]},
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_via_waypoints(ORIGIN, waypoints=[WAYPOINT_A], distance_km=10.0)

    assert candidates[0].axis_contributions == {"wind": 40.0}


# 基準線ルート（好みの重みをすべて0にしたときの経路＝所要時間が最短の経路）。


async def test_generate_destination_routes_puts_fastest_route_first():
    # 基準線は難易度が高くても先頭に固定する——他の候補が何分余計にかかるかを読むための
    # 基準であり、難易度順に沈むと基準として使えない。
    engine = DestinationSegmentedFakeEngine(
        via_node_traced=[TracedLoop(bearing=None, distance_km=22.0, data="easy", leg_of_edge=[0])],
        fastest_traced=TracedLoop(bearing=None, distance_km=18.0, data="fastest", leg_of_edge=[0]),
        segments_by_data={
            "easy": [make_segment(22.0, 10.0)],
            "fastest": [make_segment(18.0, 90.0)],
        },
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_via_waypoints(
        ORIGIN, waypoints=[], distance_km=10.0, destination=DESTINATION, max_routes=3
    )

    assert [c.distance_km for c in candidates] == [18.0, 22.0]
    assert [c.is_fastest for c in candidates] == [True, False]


async def test_generate_destination_routes_marks_existing_candidate_when_fastest_is_the_same_route():
    # 軸設定に沿った候補と基準線が同じ経路になることはある。そのとき候補を1本増やすと
    # 同じ経路のタブが2枚並ぶため、既存の1本へ印を付けるだけにする。
    same = TracedLoop(bearing=None, distance_km=18.0, data="same", leg_of_edge=[0])
    engine = DestinationSegmentedFakeEngine(
        via_node_traced=[same, TracedLoop(bearing=None, distance_km=22.0, data="long", leg_of_edge=[0])],
        fastest_traced=TracedLoop(bearing=None, distance_km=18.0, data="same", leg_of_edge=[0]),
        segments_by_data={
            "same": [make_segment(18.0, 30.0)],
            "long": [make_segment(22.0, 10.0)],
        },
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_via_waypoints(
        ORIGIN, waypoints=[], distance_km=10.0, destination=DESTINATION, max_routes=3
    )

    assert len(candidates) == 2
    assert [c.is_fastest for c in candidates] == [True, False]
    assert candidates[0].distance_km == 18.0


async def test_generate_destination_routes_keeps_max_routes_when_fastest_is_added():
    # 基準線を足してもmax_routesは超えない。切るのは末尾（最も難易度の高い候補）で、
    # 先頭に固定した基準線は必ず残る。
    engine = DestinationSegmentedFakeEngine(
        via_node_traced=[
            TracedLoop(bearing=None, distance_km=22.0, data="easy", leg_of_edge=[0]),
            TracedLoop(bearing=None, distance_km=25.0, data="hard", leg_of_edge=[0]),
        ],
        fastest_traced=TracedLoop(bearing=None, distance_km=18.0, data="fastest", leg_of_edge=[0]),
        segments_by_data={
            "easy": [make_segment(22.0, 10.0)],
            "hard": [make_segment(25.0, 70.0)],
            "fastest": [make_segment(18.0, 90.0)],
        },
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_via_waypoints(
        ORIGIN, waypoints=[], distance_km=10.0, destination=DESTINATION, max_routes=2
    )

    assert len(candidates) == 2
    assert [c.distance_km for c in candidates] == [18.0, 22.0]
    assert candidates[0].is_fastest is True


async def test_generate_destination_routes_without_fastest_route_marks_nothing():
    # 基準線を求められなかった場合でも候補は返す（基準線が無いだけ）。
    engine = DestinationSegmentedFakeEngine(
        via_node_traced=[TracedLoop(bearing=None, distance_km=22.0, data="easy", leg_of_edge=[0])],
        segments_by_data={"easy": [make_segment(22.0, 10.0)]},
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_via_waypoints(
        ORIGIN, waypoints=[], distance_km=10.0, destination=DESTINATION, max_routes=3
    )

    assert len(candidates) == 1
    assert candidates[0].is_fastest is False


async def test_material_category_shares_survive_the_post_processing_steps():
    """categorical材料の延長割合は、エンジンがビニング前に計算して候補へ載せる。

    戦略層が集約後の`segments`から計算し直すと、区間側の`material_categories`は畳むときに
    落としてあるため必ず空になる。ここで見るのは「後段が上書きしない」ことそのもの。
    """
    engine = DestinationSegmentedFakeEngine(
        via_node_traced=[TracedLoop(bearing=None, distance_km=20.0, data="a", leg_of_edge=[0])],
        segments_by_data={"a": [make_segment(20.0, 50.0)]},
    )
    shares = {"highway": {"residential": 0.62, "secondary": 0.38}}
    original = engine.evaluate_loops

    async def evaluate_with_shares(context, traced, start_time):
        return [c.model_copy(update={"material_category_shares": shares}) for c in await original(context, traced, start_time)]

    engine.evaluate_loops = evaluate_with_shares
    generator = RouteGenerator(engine)

    candidates = await generator.generate_via_waypoints(
        ORIGIN, waypoints=[], distance_km=10.0, destination=DESTINATION, max_routes=1
    )

    assert candidates[0].material_category_shares == shares


async def test_generate_destination_routes_follows_axis_weights_when_only_one_route_is_requested():
    # 基準線は比べる相手があって初めて基準になる。1本だけ返すときに基準線を先頭へ
    # 固定すると、返る唯一の候補が常に時間最短になり軸の重みが結果に現れない。
    engine = DestinationSegmentedFakeEngine(
        via_node_traced=[TracedLoop(bearing=None, distance_km=22.0, data="easy", leg_of_edge=[0])],
        fastest_traced=TracedLoop(bearing=None, distance_km=18.0, data="fastest", leg_of_edge=[0]),
        segments_by_data={
            "easy": [make_segment(22.0, 10.0)],
            "fastest": [make_segment(18.0, 90.0)],
        },
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_via_waypoints(
        ORIGIN, waypoints=[], distance_km=10.0, destination=DESTINATION, max_routes=1
    )

    assert len(candidates) == 1
    # 難易度10.0の候補（22km）が返る。90.0の基準線（18km）ではない。
    assert candidates[0].distance_km == 22.0
    assert candidates[0].is_fastest is False


async def test_generate_destination_routes_still_pins_the_fastest_when_two_are_requested():
    # 2本以上なら基準線として意味を持つので先頭固定は維持する（上のテストとの境界）。
    engine = DestinationSegmentedFakeEngine(
        via_node_traced=[TracedLoop(bearing=None, distance_km=22.0, data="easy", leg_of_edge=[0])],
        fastest_traced=TracedLoop(bearing=None, distance_km=18.0, data="fastest", leg_of_edge=[0]),
        segments_by_data={
            "easy": [make_segment(22.0, 10.0)],
            "fastest": [make_segment(18.0, 90.0)],
        },
    )
    generator = RouteGenerator(engine)

    candidates = await generator.generate_via_waypoints(
        ORIGIN, waypoints=[], distance_km=10.0, destination=DESTINATION, max_routes=2
    )

    assert [c.distance_km for c in candidates] == [18.0, 22.0]
    assert candidates[0].is_fastest is True


async def test_evaluate_loops_returning_a_different_count_is_rejected():
    # 戦略層は`TracedLoop.data`の中身を知らないため、候補とtracedを位置で対応づける。
    # 件数がずれると位置指定が別の候補を指し、基準線の印が静かに入れ替わる。
    class MiscountingEngine(DestinationSegmentedFakeEngine):
        async def evaluate_loops(self, context, traced, start_time):
            candidates = await super().evaluate_loops(context, traced, start_time)
            return candidates[:-1]  # 1本落とす

    engine = MiscountingEngine(
        via_node_traced=[
            TracedLoop(bearing=None, distance_km=22.0, data="easy", leg_of_edge=[0]),
            TracedLoop(bearing=None, distance_km=25.0, data="hard", leg_of_edge=[0]),
        ],
        segments_by_data={"easy": [make_segment(22.0, 10.0)], "hard": [make_segment(25.0, 70.0)]},
    )
    generator = RouteGenerator(engine)

    with pytest.raises(RoutingError, match="evaluate_loopsの戻り値が入力と対応していません"):
        await generator.generate_via_waypoints(
            ORIGIN, waypoints=[], distance_km=10.0, destination=DESTINATION, max_routes=3
        )


async def test_generate_spliced_route_runs_the_same_aggregation_as_other_candidates():
    # 構造仕様10: 合成結果も既存候補と同じ評価経路を通す（前半・後半の値を混ぜない）。
    engine = SegmentedFakeEngine({}, {None: [
        make_segment(12.0, 40.0, axis_difficulties={"gradient": 30.0}),
        make_segment(8.0, 60.0, axis_difficulties={"gradient": 80.0}),
    ]})
    generator = RouteGenerator(engine)

    candidates = await generator.generate_spliced_route(
        ORIGIN, DESTINATION, distance_km=10.0, edge_ids=["e1", "e2"]
    )

    # 距離加重平均: 総合 (40*12+60*8)/20、軸別 (30*12+80*8)/20
    assert candidates[0].overall_difficulty == pytest.approx(48.0)
    assert candidates[0].axis_difficulties["gradient"] == pytest.approx(50.0)
