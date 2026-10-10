"""`services/route_generator.py`——ルート生成の戦略層（距離あり・距離なし・乗り換えの入口）。

ここで見ないもの:
- 折返し点の選定・経路探索・評価の中身 → `RoadGraphEngine`（`test_route_generation_behavior.py`と、その判断の部品は`test_route_search.py`）。ここでは代役に置き換える
- 区間から候補への集約の計算（距離加重平均・丸め） → `test_route.py`・`domain/difficulty.py`のテスト
- 距離あり・距離なしのどちらの入口を使うか（要求の検証が選ぶ）とAPIの受け口 → `test_routes_generate.py`
- エンジンへ渡す引数（探索の範囲・経由地の並び・出発時刻・候補数）と、エンジンを呼んだか・何回か → 読むだけの呼び出しなので
  確かめない。経由地を順に通って起点か目的地で終わること・目的地の補正を引き継ぐことは`test_route_generation_behavior.py`が経路で見る
- 算出不能の候補を末尾へ回すことの目的地の側 → 周回と目的地が同じ並びの鍵（`domain/route_search.py: difficulty_order`）を通るので、
  周回の並びのテストが見る
- 前の生成の理由・目的地の補正を持ち越さないこと → 本番は生成ごとに`RouteGenerator`を作るので、持ち越す状態が起こらない

エンジンの代役は、各メソッドを`RoadGraphEngine`の同名メソッドの署名へ当ててから呼ぶ（`bound`）。応答を返すだけで、呼ばれ方を記録しない。
代役が返す探索結果・経路は本物の型（`TracedLoop`・`LoopTurnaround`・`RouteDraft`・`FixedLegs`）で作る。
探索の文脈（`context`）は戦略層にとって中身を読まない値で、読むのは`destination_correction`と
`no_candidates_side`の2属性だけのため、その2属性だけを持つ器で渡す。
"""

import logging
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.domain.difficulty import OverallDifficulty
from app.domain.errors import RoutingError, SearchAreaTooLargeError
from app.domain.loop_routing import LoopTurnaround, TracedLoop
from app.domain.route import Coordinates, RouteCandidate, RouteDraft, RouteSegmentDetail
from app.domain.route_request import DEFAULT_MAX_ROUTES, MAX_ROUTES, FixedPoints
from app.domain.time_zone import JST
from app.services import route_generator
from app.services.road_graph_engine import FixedLegs, RoadGraphEngine
from app.services.route_generator import RouteGenerator
from tests.bound_fake import bound

ORIGIN = Coordinates(latitude=35.6789, longitude=139.7712)
WAYPOINT = Coordinates(latitude=35.69, longitude=139.78)
DESTINATION = Coordinates(latitude=35.70, longitude=139.80)
START = datetime(2026, 9, 24, 8, 0, tzinfo=JST)
AREA_PHRASE = "候補を生成できませんでした。対応エリア外の可能性があります。"
UNREACHABLE = "指定した経由地・目的地を通る経路が見つかりませんでした。地点や除外する道路の設定を変えてお試しください。"
RETRY = "距離や除外する道路の設定を変えてお試しください。"


def _segment(difficulty: float | None, **fields) -> RouteSegmentDetail:
    return RouteSegmentDetail(
        start_latitude=0.0, start_longitude=0.0, end_latitude=0.0, end_longitude=0.0,
        cumulative_distance_km=0.0, distance_km=1.0, difficulty=difficulty, **fields,
    )


def _candidate(key: str, difficulty: float | None = 10.0, **fields) -> RouteDraft:
    """区間1本（1km・難易度`difficulty`）を持つ経路。戦略層は名前を付け替えうるので、どの候補かは`edge_ids`で見分ける。"""
    fields.setdefault("segments", [_segment(difficulty)])
    return RouteDraft(
        direction_label=f"方位-{key}", distance_km=1.0,
        geometry={"type": "LineString", "coordinates": []}, edge_ids=[key], **fields,
    )


def _route(key: str, distance_km: float = 10.0, bearing: int | None = 0) -> TracedLoop:
    return TracedLoop(bearing=bearing, distance_km=distance_km, data=[key], leg_of_edge=[0], reversible=False)


def _turnaround(outcome: TracedLoop | Exception) -> LoopTurnaround:
    """復路探索の結果（または失敗）を`data`に抱えた折返し点。`data`はエンジンだけが読む。"""
    return LoopTurnaround(bearing=0, data=outcome)


def _keys(candidates: list[RouteCandidate]) -> list[str]:
    return [c.edge_ids[0] for c in candidates]


def _identities(candidates: list[RouteCandidate]) -> list[tuple[str, str, str, bool]]:
    """候補ごとの（id・種類・名前・乗り換えの元にできるか）。"""
    return [(c.id, c.kind, c.direction_label, c.spliceable) for c in candidates]


def _fastest(candidates: list[RouteCandidate]) -> list[str]:
    return [c.edge_ids[0] for c in candidates if c.is_fastest]


def _as_engine(fake):
    return bound(getattr(RoadGraphEngine, fake.__name__), fake)


class FakeEngine:
    """`RoadGraphEngine`の代役（層の境目）。`routes`は評価の答え（経路の鍵 → 候補）。"""

    def __init__(self, *, routes=None, context=..., prepare_error=None, turnarounds=(), similar=(),
                 fixed_error=None, via=(), fastest=None, build_error=None, drop_evaluated=False):
        self.routes = routes or {}
        self.context = SimpleNamespace(destination_correction=None, no_candidates_side=None) if context is ... else context
        self.prepare_error = prepare_error
        self.turnarounds = list(turnarounds)
        self.similar = set(similar)
        self.fixed_error = fixed_error
        self.via = list(via)
        self.fastest = fastest
        self.build_error = build_error
        self.drop_evaluated = drop_evaluated

    @_as_engine
    async def prepare(self, origin, radius_km, now, waypoints=None):
        if self.prepare_error is not None:
            raise self.prepare_error
        return self.context

    @_as_engine
    async def trace_fixed_points(self, context, waypoints):
        if self.fixed_error is not None:
            raise self.fixed_error
        return FixedLegs(segments=[[0]] * len(waypoints), nodes=[0] * (len(waypoints) + 1), length_m=0.0)

    @_as_engine
    async def select_loop_turnarounds(self, context, fixed, destination, distance_km, distance_tolerance_km, pool_size):
        return list(self.turnarounds)

    @_as_engine
    async def trace_loop_from_turnaround(self, context, fixed, turnaround):
        if isinstance(turnaround.data, Exception):
            raise turnaround.data
        return turnaround.data

    @_as_engine
    def is_loop_too_similar(self, context, fixed, candidate, accepted):
        return candidate.data[0] in self.similar

    @_as_engine
    async def select_via_nodes(self, context, fixed, destination, max_routes):
        return list(self.via)

    @_as_engine
    async def select_fastest_route(self, context, fixed, destination):
        return self.fastest

    @_as_engine
    def build_traced_from_edge_ids(self, context, edge_ids, destination):
        if self.build_error is not None:
            raise self.build_error
        return TracedLoop(
            bearing=None, distance_km=3.0, data=list(edge_ids), leg_of_edge=[0] * len(edge_ids), reversible=False)

    @_as_engine
    def repeated_shares(self, context, traced):
        return [0.0] * len(traced)

    @_as_engine
    async def evaluate_loops(self, context, traced, start_time):
        return [] if self.drop_evaluated else [self.routes[t.data[0]] for t in traced]


async def _loops(
    engine: FakeEngine | RouteGenerator, max_routes: int = DEFAULT_MAX_ROUTES, points: FixedPoints | None = None,
) -> list[RouteCandidate]:
    """目標10km±1kmの距離ありの生成（`points`を省けば周回）。理由を読むテストは、作った`RouteGenerator`を渡す。"""
    generator = engine if isinstance(engine, RouteGenerator) else RouteGenerator(engine)
    return await generator.generate_loops(ORIGIN, 10.0, 1.0, max_routes, START, points=points)


async def _no_distance(engine: FakeEngine | RouteGenerator, waypoints, destination, max_routes: int = 3):
    generator = engine if isinstance(engine, RouteGenerator) else RouteGenerator(engine)
    return await generator.generate_via_waypoints(ORIGIN, waypoints, 10.0, destination, max_routes, START)


ENTRANCES = {
    "loops": lambda generator: generator.generate_loops(ORIGIN, 10.0, 1.0, DEFAULT_MAX_ROUTES, START),
    "waypoints": lambda generator: generator.generate_via_waypoints(ORIGIN, [WAYPOINT], 10.0, None, 1, START),
    "destination": lambda generator: generator.generate_via_waypoints(ORIGIN, [], 10.0, DESTINATION, 1, START),
    "spliced": lambda generator: generator.generate_spliced_route(ORIGIN, DESTINATION, 10.0, ("e1",), START),
}


def _warned(caplog) -> bool:
    return any(r.name == route_generator.logger.name and r.levelno >= logging.WARNING for r in caplog.records)


# ---- どの入口にも共通すること ----


@pytest.mark.parametrize(
    ("entrance", "phrase"),
    [("loops", AREA_PHRASE), ("waypoints", AREA_PHRASE), ("destination", AREA_PHRASE),
     ("spliced", "ルートを組み立てられませんでした。")],
)
async def test_no_road_data_gives_no_candidates_and_says_why(entrance, phrase, caplog):
    generator = RouteGenerator(FakeEngine(context=None))

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await ENTRANCES[entrance](generator) == []

    assert generator.last_no_candidates_reason == f"起点付近の道路データが未整備のため、{phrase}"
    assert _warned(caplog)


async def test_too_large_search_area_gives_no_candidates_and_says_why(caplog):
    """どの入口も上の未整備と同じ所で土台を作るので、もう片方の断り方は1つの入口で見る。"""
    generator = RouteGenerator(FakeEngine(prepare_error=SearchAreaTooLargeError(edges=1_300_000, limit=1_200_000)))

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await ENTRANCES["destination"](generator) == []

    assert generator.last_no_candidates_reason.startswith("探索範囲の道路が多すぎるため")
    assert any("edges=1300000" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    ("segments", "expected"),
    [
        ([_segment(10.0), _segment(30.0)], OverallDifficulty(average=20.0, load=40.0)),  # 総量は平均20 × 2km
        ([], OverallDifficulty(average=99.0, load=99.0)),  # 区間が無ければ、エンジンの値のまま
    ],
)
async def test_route_values_are_rebuilt_from_its_segments(segments, expected):
    evaluated = _candidate("w", segments=segments, overall_difficulty=OverallDifficulty(average=99.0, load=99.0))
    engine = FakeEngine(via=[_route("w", bearing=None)], routes={"w": evaluated})

    (candidate,) = await _no_distance(engine, [WAYPOINT], None)

    assert candidate.overall_difficulty == expected


async def test_per_axis_values_are_rebuilt_but_category_shares_and_raw_values_are_kept():
    """延長割合と軸の生の値は、エンジンが区間を約500mへ畳む前の値から作ったもので、区間からは作れない。"""
    stale = {"x": 99.0}
    segments = [
        _segment(10.0, axis_difficulties={"a": 10.0}, axis_contributions={"a": 10.0}, material_values={"a": 10.0}),
        _segment(30.0, axis_difficulties={"a": 30.0}, axis_contributions={"a": 30.0}, material_values={"a": 30.0}),
    ]
    evaluated = _candidate("e1", segments=segments, axis_difficulties=stale, axis_contributions=stale,
                           axis_raw_values={"a": 5.0}, material_values=stale,
                           material_category_shares={"surface": {"asphalt": 1.0}})

    (candidate,) = await ENTRANCES["spliced"](RouteGenerator(FakeEngine(routes={"e1": evaluated})))

    assert (candidate.axis_difficulties, candidate.axis_contributions, candidate.material_values) == (
        {"a": 20.0}, {"a": 20.0}, {"a": 20.0})
    assert candidate.axis_raw_values == {"a": 5.0}
    assert candidate.material_category_shares == {"surface": {"asphalt": 1.0}}


async def test_evaluation_that_does_not_answer_every_route_is_an_error():
    """位置で突き合わせるので、件数がずれると印やラベルが別の候補へ付く。"""
    engine = FakeEngine(turnarounds=[_turnaround(_route("a"))], routes={"a": _candidate("a")}, drop_evaluated=True)

    with pytest.raises(RoutingError):
        await _loops(engine)


# ---- 距離あり（周回） ----


def test_turnaround_pool_covers_the_requested_routes_within_what_the_diverse_selection_can_take():
    """多様な選定（`domain/routing.py: select_diverse_by_overlap`）は採用済みを64bitのマスクで持つため、64件まで。"""
    for max_routes in range(1, MAX_ROUTES + 1):
        assert max_routes <= route_generator.turnaround_pool_size(max_routes) <= 64


async def test_loops_without_turnarounds_say_how_far_out_was_searched(caplog):
    generator = RouteGenerator(FakeEngine())

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await _loops(generator) == []

    assert generator.last_no_candidates_reason == f"起点から片道5.0km前後で到達できる折返し地点が見つかりませんでした。{RETRY}"
    assert _warned(caplog)


async def test_loops_stop_once_enough_routes_are_accepted():
    keys = ["a", "b", "c", "d"]
    engine = FakeEngine(turnarounds=[_turnaround(_route(k)) for k in keys], routes={k: _candidate(k) for k in keys})

    assert len(await _loops(engine, max_routes=2)) == 2


async def test_loops_pass_over_turnarounds_whose_return_trip_fails(caplog):
    engine = FakeEngine(
        turnarounds=[_turnaround(RoutingError("復路なし")), _turnaround(RuntimeError("不具合")), _turnaround(_route("a"))],
        routes={"a": _candidate("a")},
    )

    with caplog.at_level(logging.DEBUG, logger=route_generator.logger.name):
        assert _keys(await _loops(engine)) == ["a"]

    # 想定外の例外だけは、エンジンの不具合としてスタックトレース付きのERRORで残す
    (error,) = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert isinstance(error.exc_info[1], RuntimeError)


async def test_loops_keep_only_routes_within_the_distance_tolerance():
    lengths = {"edge": 11.0, "over": 11.5, "under": 8.9}
    engine = FakeEngine(turnarounds=[_turnaround(_route(k, distance_km=d)) for k, d in lengths.items()],
                        routes={k: _candidate(k) for k in lengths})

    # 目標±許容のちょうど端は含む。目標より短い側も同じ幅で外す
    assert _keys(await _loops(engine)) == ["edge"]


async def test_loops_drop_a_route_too_similar_to_one_already_accepted():
    keys = ["a", "b", "c"]
    engine = FakeEngine(turnarounds=[_turnaround(_route(k)) for k in keys], similar={"b"},
                        routes={k: _candidate(k) for k in keys})

    assert sorted(_keys(await _loops(engine))) == ["a", "c"]


async def test_loops_are_ordered_easiest_first_ties_closest_to_target_first_and_unknown_last():
    loops = {"far": (10.8, 20.0), "near": (10.1, 20.0), "easy": (10.5, 10.0), "unknown": (10.0, None)}
    engine = FakeEngine(turnarounds=[_turnaround(_route(k, distance_km=d)) for k, (d, _) in loops.items()],
                        routes={k: _candidate(k, difficulty) for k, (_, difficulty) in loops.items()})

    result = await _loops(engine, max_routes=4)

    # idは最終の並びから作り、名前はエンジンが方位から付けたまま。周回は最速の印を持たず、乗り換えの元にできない
    # （途中で別の候補へ乗り換えると、起点へ戻れる保証が無くなる）
    assert _identities(result) == [
        ("loop-00", "loop", "方位-easy", False),
        ("loop-01", "loop", "方位-near", False),
        ("loop-02", "loop", "方位-far", False),
        ("loop-03", "loop", "方位-unknown", False),
    ]
    assert _fastest(result) == []


@pytest.mark.parametrize(
    ("outcomes", "reason"),
    [
        ([RoutingError("復路なし")], "1件の折返し候補で復路の探索に失敗しました[除外設定をご確認ください]。"),
        ([_route("x", distance_km=20.0), _route("y", distance_km=1.0)], "2件の周回候補は指定距離[10.0km±1.0km]から外れました。"),
        ([RoutingError("復路なし"), _route("x", distance_km=20.0)],
         "1件の折返し候補で復路の探索に失敗しました[除外設定をご確認ください]、1件の周回候補は指定距離[10.0km±1.0km]から外れました。"),
    ],
)
async def test_loops_that_all_fall_out_say_why(outcomes, reason, caplog):
    generator = RouteGenerator(FakeEngine(turnarounds=[_turnaround(o) for o in outcomes]))

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await _loops(generator) == []

    assert generator.last_no_candidates_reason == reason + RETRY
    assert _warned(caplog)


# ---- 距離あり・置いた点あり ----


@pytest.mark.parametrize(
    ("points", "identities"),
    [
        # 出発地へ戻るなら周回と同じく方位の名前
        (FixedPoints(waypoints=[WAYPOINT], destination=None),
         [("loop-00", "loop", "方位-easy", False), ("loop-01", "loop", "方位-hard", False)]),
        # 目的地で終わるなら目的地ルートで、乗り換えの元にできる
        (FixedPoints(waypoints=[], destination=DESTINATION),
         [("destination-00", "destination", "目的地ルート", True), ("destination-01", "destination", "目的地ルート", True)]),
    ],
)
async def test_distance_routes_through_placed_points_are_named_by_where_they_end(points, identities):
    engine = FakeEngine(turnarounds=[_turnaround(_route(k)) for k in ("hard", "easy")],
                        routes={"hard": _candidate("hard", 30.0), "easy": _candidate("easy", 10.0)})

    result = await _loops(engine, points=points)

    # 距離を決めた生成は、所要時間が最短の1本を足さない（目標の距離と噛み合わない）
    assert (_identities(result), _fastest(result)) == (identities, [])


async def test_distance_routes_through_placed_points_without_a_relay_say_so(caplog):
    generator = RouteGenerator(FakeEngine())

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await _loops(generator, points=FixedPoints(waypoints=[WAYPOINT], destination=None)) == []

    assert generator.last_no_candidates_reason == (
        "置いた地点を通って全長10.0km前後になる経路が見つかりませんでした。距離や地点、除外する道路の設定を変えてお試しください。")
    assert _warned(caplog)


# ---- 距離なし・経由地あり ----


async def test_waypoint_routes_back_to_the_origin_come_in_several_without_the_fastest():
    engine = FakeEngine(via=[_route(k, bearing=None) for k in ("hard", "easy", "mid")],
                        fastest=_route("fastest", bearing=None),
                        routes={"hard": _candidate("hard", 30.0), "easy": _candidate("easy", 10.0),
                                "mid": _candidate("mid", 20.0), "fastest": _candidate("fastest", 5.0)})

    result = await _no_distance(engine, [WAYPOINT], None, max_routes=2)

    # 難易度の高い側から切る。出発地へ戻る経路は乗り換えの元にできない
    assert _identities(result) == [("loop-00", "loop", "経由地ルート", False), ("loop-01", "loop", "経由地ルート", False)]
    assert (_keys(result), _fastest(result)) == (["easy", "mid"], [])


async def test_waypoint_routes_to_a_destination_add_the_fastest():
    result = await _no_distance(_destination_engine("fastest", hard=30.0, easy=10.0, fastest=20.0), [WAYPOINT], DESTINATION)

    assert _identities(result) == [(f"destination-0{i}", "destination", "目的地ルート", True) for i in range(3)]
    assert _fastest(result) == ["fastest"]


@pytest.mark.parametrize("failing", ["fixed_error", "via"])  # 置いた点どうし・最後の点から終点まで
@pytest.mark.parametrize("side", [None, "origin"])  # 最後の点から走り出せなくても、起点のせいにしない
async def test_waypoints_that_cannot_be_connected_give_no_candidates_and_say_why(failing, side, caplog):
    generator = RouteGenerator(FakeEngine(
        context=SimpleNamespace(destination_correction=None, no_candidates_side=side),
        **({"fixed_error": RoutingError("到達不能")} if failing == "fixed_error" else {"via": []}),
    ))

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await _no_distance(generator, [WAYPOINT], None) == []

    assert generator.last_no_candidates_reason == UNREACHABLE
    assert _warned(caplog)


# ---- 距離なし・経由地なし（目的地ルート） ----


def _destination_engine(fastest: str | None, /, **difficulties: float) -> FakeEngine:
    """代替経路は`difficulties`の順に返り、`fastest`は所要時間が最短の1本（代替経路と同じ鍵ならその経路）。"""
    routes = {k: _candidate(k, d) for k, d in difficulties.items()}
    return FakeEngine(via=[_route(k) for k in difficulties if k != "fastest"],
                      fastest=None if fastest is None else _route(fastest), routes=routes)


async def test_destination_routes_add_the_fastest_and_are_ordered_easiest_first():
    engine = _destination_engine("fastest", hard=30.0, easy=10.0, fastest=20.0)

    result = await _no_distance(engine, [], DESTINATION)

    assert _keys(result) == ["easy", "fastest", "hard"]
    assert _identities(result) == [(f"destination-0{i}", "destination", "目的地ルート", True) for i in range(3)]
    assert _fastest(result) == ["fastest"]


async def test_destination_routes_do_not_add_the_fastest_twice_when_an_alternative_is_it():
    result = await _no_distance(_destination_engine("hard", hard=30.0, easy=10.0), [], DESTINATION)

    assert _keys(result) == ["easy", "hard"]
    assert _fastest(result) == ["hard"]


@pytest.mark.parametrize(
    ("max_routes", "expected", "fastest"),
    [
        (2, ["easy", "fastest"], ["fastest"]),  # 難易度で最下位の基準線を残し、その次に難しい候補を切る
        (1, ["easy"], []),  # 1本だけ返すときは基準線を残さない——軸の重みが結果に現れなくなる
    ],
)
async def test_destination_routes_cut_the_hardest_but_keep_the_fastest_unless_returning_one(max_routes, expected, fastest):
    engine = _destination_engine("fastest", hard=30.0, easy=10.0, fastest=50.0)

    result = await _no_distance(engine, [], DESTINATION, max_routes=max_routes)

    assert (_keys(result), _fastest(result)) == (expected, fastest)


@pytest.mark.parametrize(
    ("fastest", "difficulties", "expected"),
    [
        ("a", {"a": 10.0}, ["a"]),  # 比べる相手が無いので、基準として印を付けない
        (None, {"a": 10.0, "b": 10.0}, ["a", "b"]),  # 最速の経路が引けなければ、代替経路だけを返す
    ],
)
async def test_destination_routes_without_another_route_to_compare_mark_no_fastest(fastest, difficulties, expected):
    result = await _no_distance(_destination_engine(fastest, **difficulties), [], DESTINATION)

    assert (_keys(result), _fastest(result)) == (expected, [])


@pytest.mark.parametrize(
    ("side", "reason"),
    [
        ("origin", "起点から走り出せる道が見つかりませんでした。出発地を道路沿いへ動かしてお試しください。"),
        ("destination", "指定した目的地までの経路が見つかりませんでした。地点や除外する道路の設定を変えてお試しください。"),
    ],
)
async def test_destination_without_alternatives_says_which_end_is_stuck(side, reason, caplog):
    generator = RouteGenerator(FakeEngine(context=SimpleNamespace(destination_correction=None, no_candidates_side=side)))

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await _no_distance(generator, [], DESTINATION) == []

    assert generator.last_no_candidates_reason == reason
    assert _warned(caplog)


# ---- 区間の乗り換え ----


async def test_spliced_route_is_labelled_as_one_combined_route():
    result = await ENTRANCES["spliced"](RouteGenerator(FakeEngine(routes={"e1": _candidate("e1")})))

    assert _identities(result) == [("spliced-00", "spliced", "組み合わせたルート", True)]


async def test_spliced_route_that_does_not_connect_says_so_without_internal_ids(caplog):
    generator = RouteGenerator(FakeEngine(build_error=RoutingError("edge_id=osm-123 がつながっていない")))

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await generator.generate_spliced_route(ORIGIN, DESTINATION, 10.0, ("osm-123",), START) == []

    assert generator.last_no_candidates_reason == (
        "組み合わせた経路がつながっていないため評価できませんでした。区間の選び直しか、ルートの再生成をお試しください。")
    # 原因（内部の識別子を含む）はログにだけ残す
    assert any("osm-123" in r.getMessage() for r in caplog.records)
