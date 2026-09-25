"""`services/route_generator.py`——ルート生成の戦略層（周回・経由地・目的地・乗り換えの4つの入口）。

ここで見ないもの:
- 折返し点の選定・経路探索・評価の中身 → `RoadGraphEngine`（`test_road_graph_engine.py`）。ここでは代役に置き換える
- 区間から候補への集約の計算（距離加重平均・丸め） → `test_route.py`・`domain/difficulty.py`のテスト
- APIの受け口（ジョブの投稿・202） → `test_routes_generate.py`

エンジンの代役は、各メソッドを`RoadGraphEngine`の同名メソッドの署名へ当ててから呼ぶ（`bound`）。
代役が返す探索結果・候補は本物の型（`TracedLoop`・`LoopTurnaround`・`RouteCandidate`）で作る。
探索の文脈（`context`）は戦略層にとって中身を読まない値で、読むのは`destination_correction`と
`no_candidates_side`の2属性だけのため、その2属性だけを持つ器で渡す。
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.domain.errors import SearchAreaTooLargeError
from app.domain.loop_routing import LoopTurnaround, TracedLoop
from app.domain.route import Coordinates, RouteCandidate, RouteSegmentDetail
from app.services import route_generator
from app.services.road_graph_engine import RoadGraphEngine
from app.services.route_generator import RouteGenerator
from tests.bound_fake import bound

ORIGIN = Coordinates(latitude=35.6789, longitude=139.7712)
ORIGIN_LABEL = "(35.68,139.77)"  # 常時出るログ・利用者向けの理由は座標を小数2桁で出す
WAYPOINT = Coordinates(latitude=35.69, longitude=139.78)
DESTINATION = Coordinates(latitude=35.70, longitude=139.80)
START = datetime(2026, 9, 24, 8, 0, tzinfo=route_generator.JST)
AREA_PHRASE = "候補を生成できませんでした。対応エリア外の可能性があります。"


def _segment(difficulty: float | None, distance_km: float = 1.0, **fields) -> RouteSegmentDetail:
    return RouteSegmentDetail(
        start_latitude=0.0,
        start_longitude=0.0,
        end_latitude=0.0,
        end_longitude=0.0,
        cumulative_distance_km=0.0,
        distance_km=distance_km,
        difficulty=difficulty,
        **fields,
    )


def _candidate(key: str, difficulty: float | None = 10.0, **fields) -> RouteCandidate:
    """区間1本（1km・難易度`difficulty`）を持つ候補。集約後の総合難易度は`difficulty`になる。

    戦略層はidと方位ラベルを付け替えるため、どの候補かは経路（`edge_ids`）で見分ける。
    """
    fields.setdefault("segments", [_segment(difficulty)])
    return RouteCandidate(
        id=f"engine-{key}",
        direction_label=f"方位-{key}",
        distance_km=1.0,
        geometry={"type": "LineString", "coordinates": []},
        edge_ids=[key],
        **fields,
    )


def _keys(candidates: list[RouteCandidate]) -> list[str]:
    return [c.edge_ids[0] for c in candidates]


def _loop(key: str, distance_km: float = 10.0, bearing: int | None = 0) -> TracedLoop:
    return TracedLoop(bearing=bearing, distance_km=distance_km, data=[key], leg_of_edge=[0])


def _turnaround(outcome: TracedLoop | Exception) -> LoopTurnaround:
    """復路探索の結果（または失敗）を`data`に抱えた折返し点。`data`はエンジンだけが読む。"""
    return LoopTurnaround(bearing=0, outbound_difficulty=None, data=outcome)


_UNSET = object()


def _engine_method(fake):
    return bound(getattr(RoadGraphEngine, fake.__name__), fake)


class FakeEngine:
    """`RoadGraphEngine`の代役（層の境目）。呼ばれた引数を`calls`へ名前ごとに残す。"""

    def __init__(
        self,
        *,
        context=_UNSET,
        prepare_error=None,
        turnarounds=(),
        similar=(),
        candidates=None,
        waypoint_loop=None,
        trace_error=None,
        via=(),
        fastest=None,
        build_error=None,
        drop_evaluated=False,
    ):
        self.context = SimpleNamespace() if context is _UNSET else context
        self.prepare_error = prepare_error
        self.turnarounds = list(turnarounds)
        self.similar = set(similar)
        self.candidates = candidates or {}
        self.waypoint_loop = waypoint_loop
        self.trace_error = trace_error
        self.via = list(via)
        self.fastest = fastest
        self.build_error = build_error
        self.drop_evaluated = drop_evaluated
        self.calls: dict[str, list[dict]] = defaultdict(list)

    @_engine_method
    async def prepare(self, origin, radius_km, now=None, waypoints=None):
        self.calls["prepare"].append({"origin": origin, "radius_km": radius_km, "now": now, "waypoints": waypoints})
        if self.prepare_error is not None:
            raise self.prepare_error
        return self.context

    @_engine_method
    async def select_loop_turnarounds(self, context, distance_km, distance_tolerance_km, pool_size):
        self.calls["select_loop_turnarounds"].append(
            {"distance_km": distance_km, "distance_tolerance_km": distance_tolerance_km, "pool_size": pool_size}
        )
        return list(self.turnarounds)

    @_engine_method
    async def trace_loop_from_turnaround(self, context, turnaround):
        self.calls["trace_loop_from_turnaround"].append({"turnaround": turnaround})
        if isinstance(turnaround.data, Exception):
            raise turnaround.data
        return turnaround.data

    @_engine_method
    def is_loop_too_similar(self, context, candidate, accepted):
        self.calls["is_loop_too_similar"].append(
            {"candidate": candidate.data[0], "accepted": [a.data[0] for a in accepted]}
        )
        return candidate.data[0] in self.similar

    @_engine_method
    async def evaluate_loops(self, context, traced, start_time):
        self.calls["evaluate_loops"].append({"traced": [t.data[0] for t in traced], "start_time": start_time})
        if self.drop_evaluated:
            return []
        return [self.candidates[t.data[0]] for t in traced]

    @_engine_method
    async def trace_loop(self, context, waypoints, bearing):
        self.calls["trace_loop"].append({"waypoints": waypoints, "bearing": bearing})
        if self.trace_error is not None:
            raise self.trace_error
        return self.waypoint_loop

    @_engine_method
    def build_traced_from_edge_ids(self, context, edge_ids, destination=None):
        self.calls["build_traced_from_edge_ids"].append({"edge_ids": edge_ids, "destination": destination})
        if self.build_error is not None:
            raise self.build_error
        return TracedLoop(bearing=None, distance_km=3.0, data=list(edge_ids), leg_of_edge=[0] * len(edge_ids))

    @_engine_method
    async def select_via_nodes(self, context, destination, max_routes):
        self.calls["select_via_nodes"].append({"destination": destination, "max_routes": max_routes})
        return list(self.via)

    @_engine_method
    async def select_fastest_route(self, context, destination):
        self.calls["select_fastest_route"].append({"destination": destination})
        return self.fastest


ENTRANCES = {
    "loops": lambda gen, **kw: gen.generate_loops(ORIGIN, 10.0, 1.0, **kw),
    "via_waypoints": lambda gen, **kw: gen.generate_via_waypoints(ORIGIN, [WAYPOINT], 10.0, **kw),
    "destination": lambda gen, **kw: gen.generate_via_waypoints(ORIGIN, [], 10.0, destination=DESTINATION, **kw),
    "spliced": lambda gen, **kw: gen.generate_spliced_route(ORIGIN, DESTINATION, 10.0, ["e1"], **kw),
}


def _warnings(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == route_generator.logger.name and r.levelno >= logging.WARNING]


# ---- 4つの入口に共通すること ----


@pytest.mark.parametrize(
    ("entrance", "phrase"),
    [
        ("loops", AREA_PHRASE),
        ("via_waypoints", AREA_PHRASE),
        ("destination", AREA_PHRASE),
        ("spliced", "ルートを組み立てられませんでした。"),
    ],
)
async def test_missing_road_data_gives_no_candidates_and_says_why(entrance, phrase, caplog):
    engine = FakeEngine(context=None)
    generator = RouteGenerator(engine)

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await ENTRANCES[entrance](generator, start_time=START) == []

    assert generator.last_no_candidates_reason == f"起点{ORIGIN_LABEL}付近の道路データが未整備のため、{phrase}"
    assert _warnings(caplog)
    assert "evaluate_loops" not in engine.calls


@pytest.mark.parametrize("entrance", sorted(ENTRANCES))
async def test_too_large_search_area_gives_no_candidates_and_says_why(entrance, caplog):
    engine = FakeEngine(prepare_error=SearchAreaTooLargeError(edges=1_300_000, limit=1_200_000))
    generator = RouteGenerator(engine)

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await ENTRANCES[entrance](generator, start_time=START) == []

    assert generator.last_no_candidates_reason is not None
    assert "探索範囲の道路が多すぎる" in generator.last_no_candidates_reason
    assert any("edges=1300000" in r.getMessage() for r in _warnings(caplog))
    assert set(engine.calls) == {"prepare"}


@pytest.mark.parametrize("entrance", sorted(ENTRANCES))
async def test_start_time_defaults_to_now_in_japan_time(entrance):
    engine = FakeEngine(context=None)
    before = datetime.now(route_generator.JST)

    await ENTRANCES[entrance](RouteGenerator(engine))

    (prepare,) = engine.calls["prepare"]
    assert prepare["now"].utcoffset() == timedelta(hours=9)
    assert before <= prepare["now"] <= datetime.now(route_generator.JST)


@pytest.mark.parametrize("entrance", sorted(ENTRANCES))
async def test_every_entrance_sizes_the_search_area_by_the_same_ratio_of_the_distance(entrance):
    engine = FakeEngine(context=None)

    await ENTRANCES[entrance](RouteGenerator(engine), start_time=START)

    (prepare,) = engine.calls["prepare"]
    assert prepare["radius_km"] == 10.0 * route_generator.TURNAROUND_RADIUS_RATIO


@pytest.mark.parametrize("entrance", sorted(ENTRANCES))
async def test_given_start_time_reaches_both_preparation_and_evaluation(entrance):
    engine = FakeEngine(
        turnarounds=[_turnaround(_loop("a"))],
        waypoint_loop=_loop("a", bearing=None),
        via=[_loop("a")],
        candidates={"a": _candidate("a"), "e1": _candidate("e1")},
    )
    generator = RouteGenerator(engine)
    generator.last_no_candidates_reason = "前回の理由"

    assert await ENTRANCES[entrance](generator, start_time=START)

    assert [c["now"] for c in engine.calls["prepare"]] == [START]
    assert [c["start_time"] for c in engine.calls["evaluate_loops"]] == [START]
    # 前の呼び出しの理由を持ち越さない
    assert generator.last_no_candidates_reason is None


async def test_candidate_values_are_rebuilt_from_its_segments():
    per_axis = {"a": 10.0}
    stale = {"x": 99.0}
    evaluated = _candidate(
        "e1",
        segments=[
            _segment(
                10.0,
                axis_difficulties=per_axis,
                axis_contributions=per_axis,
                axis_raw_values=per_axis,
                material_values=per_axis,
            ),
            _segment(
                30.0,
                axis_difficulties={"a": 30.0},
                axis_contributions={"a": 30.0},
                axis_raw_values={"a": 30.0},
                material_values={"a": 30.0},
            ),
        ],
        overall_difficulty=99.0,
        difficulty_load=99.0,
        axis_difficulties=stale,
        axis_contributions=stale,
        axis_raw_values=stale,
        material_values=stale,
        material_category_shares={"surface": {"asphalt": 1.0}},
    )
    engine = FakeEngine(candidates={"e1": evaluated})

    (candidate,) = await RouteGenerator(engine).generate_spliced_route(ORIGIN, DESTINATION, 10.0, ["e1"], START)

    assert candidate.overall_difficulty == 20.0
    assert candidate.difficulty_load == 40.0  # 平均20 × 2km
    assert candidate.axis_difficulties == {"a": 20.0}
    assert candidate.axis_contributions == {"a": 20.0}
    assert candidate.axis_raw_values == {"a": 20.0}
    assert candidate.material_values == {"a": 20.0}
    # 延長割合はエンジンがビニングの前に作った値で、畳んだ区間からは作り直さない
    assert candidate.material_category_shares == {"surface": {"asphalt": 1.0}}


@pytest.mark.parametrize("segments", [None, []])
async def test_candidate_without_segments_keeps_the_values_the_engine_gave(segments):
    evaluated = _candidate("e1", segments=segments, overall_difficulty=55.0, axis_difficulties={"a": 1.0})
    engine = FakeEngine(candidates={"e1": evaluated})

    (candidate,) = await RouteGenerator(engine).generate_spliced_route(ORIGIN, DESTINATION, 10.0, ["e1"], START)

    assert candidate.overall_difficulty == 55.0
    assert candidate.axis_difficulties == {"a": 1.0}


async def test_evaluation_that_does_not_answer_every_route_is_an_error():
    engine = FakeEngine(turnarounds=[_turnaround(_loop("a"))], candidates={"a": _candidate("a")}, drop_evaluated=True)

    with pytest.raises(route_generator.RoutingError):
        await RouteGenerator(engine).generate_loops(ORIGIN, 10.0, 1.0, start_time=START)


# ---- 周回 ----


def test_turnaround_pool_can_always_fill_the_requested_routes_and_is_capped():
    for max_routes in range(1, route_generator.MAX_ROUTES + 1):
        pool = route_generator.turnaround_pool_size(max_routes)
        assert max_routes <= pool <= route_generator.TURNAROUND_POOL_MAX


async def test_loops_prepare_around_the_origin_only_and_ask_for_a_pool():
    engine = FakeEngine(turnarounds=[_turnaround(_loop("a"))], candidates={"a": _candidate("a")})

    await RouteGenerator(engine).generate_loops(ORIGIN, 10.0, 1.0, max_routes=3, start_time=START)

    (prepare,) = engine.calls["prepare"]
    assert prepare["origin"] == ORIGIN
    assert prepare["waypoints"] is None
    (select,) = engine.calls["select_loop_turnarounds"]
    assert (select["distance_km"], select["distance_tolerance_km"]) == (10.0, 1.0)
    assert select["pool_size"] >= 3


async def test_loops_without_turnarounds_say_how_far_was_searched(caplog):
    engine = FakeEngine()
    generator = RouteGenerator(engine)

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await generator.generate_loops(ORIGIN, 10.0, 1.0, start_time=START) == []

    assert generator.last_no_candidates_reason == (
        "起点から片道5.0km前後で到達できる折返し地点が見つかりませんでした。"
        "距離や除外する道路の設定を変えてお試しください。"
    )
    assert _warnings(caplog)


async def test_loops_stop_tracing_once_enough_routes_are_accepted():
    keys = ["a", "b", "c", "d"]
    engine = FakeEngine(turnarounds=[_turnaround(_loop(k)) for k in keys], candidates={k: _candidate(k) for k in keys})

    result = await RouteGenerator(engine).generate_loops(ORIGIN, 10.0, 1.0, max_routes=2, start_time=START)

    assert len(result) == 2
    assert len(engine.calls["trace_loop_from_turnaround"]) == 2


async def test_loops_skip_turnarounds_whose_return_trip_fails(caplog):
    engine = FakeEngine(
        turnarounds=[
            _turnaround(route_generator.RoutingError("復路なし")),
            _turnaround(RuntimeError("エンジンの不具合")),
            _turnaround(_loop("a")),
        ],
        candidates={"a": _candidate("a")},
    )

    with caplog.at_level(logging.DEBUG, logger=route_generator.logger.name):
        result = await RouteGenerator(engine).generate_loops(ORIGIN, 10.0, 1.0, start_time=START)

    assert [c.direction_label for c in result] == ["方位-a"]
    # 想定外の例外だけはエンジンの不具合として、スタックトレース付きのERRORで残す
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert errors[0].exc_info is not None
    assert isinstance(errors[0].exc_info[1], RuntimeError)


async def test_loops_keep_only_routes_within_the_distance_tolerance():
    lengths = {"exact_upper": 11.0, "exact_lower": 9.0, "over": 11.5, "under": 8.9}
    engine = FakeEngine(
        turnarounds=[_turnaround(_loop(k, distance_km=d)) for k, d in lengths.items()],
        candidates={k: _candidate(k) for k in lengths},
    )

    result = await RouteGenerator(engine).generate_loops(ORIGIN, 10.0, 1.0, start_time=START)

    # 目標±許容のちょうど端は含む
    assert sorted(c.direction_label for c in result) == ["方位-exact_lower", "方位-exact_upper"]


async def test_loops_drop_a_route_too_similar_to_one_already_accepted():
    keys = ["a", "b", "c"]
    engine = FakeEngine(
        turnarounds=[_turnaround(_loop(k)) for k in keys],
        similar={"b"},
        candidates={k: _candidate(k) for k in keys},
    )

    result = await RouteGenerator(engine).generate_loops(ORIGIN, 10.0, 1.0, start_time=START)

    assert sorted(c.direction_label for c in result) == ["方位-a", "方位-c"]
    # 1本目は比べる相手が無いので問わない。以降は採用済みの候補とだけ比べる
    assert engine.calls["is_loop_too_similar"] == [
        {"candidate": "b", "accepted": ["a"]},
        {"candidate": "c", "accepted": ["a"]},
    ]


async def test_loops_are_ordered_easiest_first_and_ties_by_closeness_to_target():
    loops = {"far": (10.8, 20.0), "near": (10.1, 20.0), "easy": (10.5, 10.0), "unknown": (10.0, None)}
    engine = FakeEngine(
        turnarounds=[_turnaround(_loop(k, distance_km=d)) for k, (d, _) in loops.items()],
        candidates={k: _candidate(k, difficulty) for k, (_, difficulty) in loops.items()},
    )

    result = await RouteGenerator(engine).generate_loops(ORIGIN, 10.0, 1.0, max_routes=4, start_time=START)

    # 総合難易度の昇順。同点は目標距離に近い順、算出できない候補は末尾
    assert [c.direction_label for c in result] == ["方位-easy", "方位-near", "方位-far", "方位-unknown"]
    # idは最終の順位で振り直す（方位ラベルはエンジンが付けたまま）
    assert [c.id for c in result] == ["route-00", "route-01", "route-02", "route-03"]


@pytest.mark.parametrize(
    ("outcomes", "reason"),
    [
        (
            [route_generator.RoutingError("復路なし")],
            "1件の折返し候補で復路の探索に失敗しました（除外設定をご確認ください）。",
        ),
        (
            [_loop("x", distance_km=20.0), _loop("y", distance_km=1.0)],
            "2件の周回候補は指定距離（10.0km±1.0km）から外れました。",
        ),
        (
            [RuntimeError("エンジンの不具合"), _loop("x", distance_km=20.0)],
            "1件の折返し候補で復路の探索に失敗しました（除外設定をご確認ください）、"
            "1件の周回候補は指定距離（10.0km±1.0km）から外れました。",
        ),
    ],
)
async def test_loops_that_all_fall_out_say_why(outcomes, reason, caplog):
    engine = FakeEngine(turnarounds=[_turnaround(o) for o in outcomes])
    generator = RouteGenerator(engine)

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await generator.generate_loops(ORIGIN, 10.0, 1.0, start_time=START) == []

    assert generator.last_no_candidates_reason == reason + "距離や除外する道路の設定を変えてお試しください。"
    assert _warnings(caplog)
    assert "evaluate_loops" not in engine.calls


# ---- 経由地 ----


async def test_waypoints_without_destination_return_to_the_origin():
    engine = FakeEngine(
        waypoint_loop=_loop("w", bearing=None),
        candidates={"w": _candidate("w").model_copy(update={"id": "route-waypoints"})},
    )
    second = Coordinates(latitude=35.695, longitude=139.785)

    result = await RouteGenerator(engine).generate_via_waypoints(
        ORIGIN, [WAYPOINT, second], 10.0, max_routes=5, start_time=START
    )

    assert engine.calls["trace_loop"] == [{"waypoints": [ORIGIN, WAYPOINT, second, ORIGIN], "bearing": None}]
    assert engine.calls["prepare"][0]["waypoints"] == [WAYPOINT, second]
    # 経由地があるときは1本だけで、エンジンが付けたidのまま
    assert [c.id for c in result] == ["route-waypoints"]


async def test_waypoints_with_destination_end_there_and_are_labelled_as_destination_route():
    engine = FakeEngine(waypoint_loop=_loop("w", bearing=None), candidates={"w": _candidate("w")})

    result = await RouteGenerator(engine).generate_via_waypoints(
        ORIGIN, [WAYPOINT], 10.0, destination=DESTINATION, max_routes=5, start_time=START
    )

    assert engine.calls["trace_loop"][0]["waypoints"] == [ORIGIN, WAYPOINT, DESTINATION]
    # 目的地も探索範囲に入れる
    assert engine.calls["prepare"][0]["waypoints"] == [WAYPOINT, DESTINATION]
    assert [(c.id, c.direction_label) for c in result] == [("route-destination", "目的地ルート")]
    assert "select_via_nodes" not in engine.calls


async def test_waypoints_that_cannot_be_connected_give_no_candidates_and_say_why(caplog):
    engine = FakeEngine(trace_error=route_generator.RoutingError("到達不能"))
    generator = RouteGenerator(engine)

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await generator.generate_via_waypoints(ORIGIN, [WAYPOINT], 10.0, start_time=START) == []

    assert generator.last_no_candidates_reason == (
        "指定した経由地・目的地を通る経路が見つかりませんでした。地点や除外する道路の設定を変えてお試しください。"
    )
    assert _warnings(caplog)


# ---- 区間の乗り換え ----


async def test_spliced_route_is_evaluated_as_given_and_labelled():
    engine = FakeEngine(candidates={"e1": _candidate("e1")})
    generator = RouteGenerator(engine)
    generator.last_destination_correction = DESTINATION

    result = await generator.generate_spliced_route(ORIGIN, DESTINATION, 10.0, ["e1", "e2"], START)

    assert engine.calls["prepare"][0]["waypoints"] == [DESTINATION]
    assert engine.calls["build_traced_from_edge_ids"] == [{"edge_ids": ["e1", "e2"], "destination": DESTINATION}]
    assert [(c.id, c.direction_label) for c in result] == [(route_generator.SPLICED_ROUTE_ID, "組み合わせたルート")]
    assert generator.last_destination_correction is None


async def test_spliced_route_that_does_not_connect_says_so_without_internal_ids(caplog):
    engine = FakeEngine(build_error=route_generator.RoutingError("edge_id=osm-123 がつながっていない"))
    generator = RouteGenerator(engine)

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await generator.generate_spliced_route(ORIGIN, DESTINATION, 10.0, ["osm-123"], START) == []

    assert generator.last_no_candidates_reason == (
        "組み合わせた経路がつながっていないため評価できませんでした。区間の選び直しか、ルートの再生成をお試しください。"
    )
    assert "osm-123" not in generator.last_no_candidates_reason
    # 原因（内部の識別子を含む）はログにだけ残す
    assert any("osm-123" in r.getMessage() for r in _warnings(caplog))


# ---- 目的地（経由地なし） ----


async def _destination_routes(engine: FakeEngine, max_routes: int) -> list[RouteCandidate]:
    return await RouteGenerator(engine).generate_via_waypoints(
        ORIGIN, [], 10.0, destination=DESTINATION, max_routes=max_routes, start_time=START
    )


async def test_destination_asks_for_alternatives_up_to_the_requested_count():
    engine = FakeEngine(via=[_loop("a")], candidates={"a": _candidate("a")})

    await _destination_routes(engine, max_routes=4)

    assert engine.calls["prepare"][0]["waypoints"] == [DESTINATION]
    assert engine.calls["select_via_nodes"] == [{"destination": DESTINATION, "max_routes": 4}]
    assert engine.calls["select_fastest_route"] == [{"destination": DESTINATION}]
    assert "trace_loop" not in engine.calls


async def test_destination_pins_the_fastest_route_first_then_easiest_first():
    engine = FakeEngine(
        via=[_loop("hard"), _loop("easy")],
        fastest=_loop("fastest"),
        candidates={
            "hard": _candidate("hard", 30.0),
            "easy": _candidate("easy", 10.0),
            "fastest": _candidate("fastest", 50.0),
        },
    )

    result = await _destination_routes(engine, max_routes=3)

    assert _keys(result) == ["fastest", "easy", "hard"]
    assert [c.is_fastest for c in result] == [True, False, False]
    assert [c.id for c in result] == ["route-destination-00", "route-destination-01", "route-destination-02"]
    assert {c.direction_label for c in result} == {"目的地ルート"}


async def test_destination_marks_an_alternative_that_is_already_the_fastest_instead_of_adding_it():
    engine = FakeEngine(
        via=[_loop("hard"), _loop("easy")],
        fastest=_loop("hard"),
        candidates={"hard": _candidate("hard", 30.0), "easy": _candidate("easy", 10.0)},
    )

    result = await _destination_routes(engine, max_routes=3)

    assert [(c.edge_ids[0], c.is_fastest) for c in result] == [("hard", True), ("easy", False)]


async def test_destination_cuts_the_hardest_when_the_fastest_is_added_beyond_the_count():
    engine = FakeEngine(
        via=[_loop("hard"), _loop("easy")],
        fastest=_loop("fastest"),
        candidates={
            "hard": _candidate("hard", 30.0),
            "easy": _candidate("easy", 10.0),
            "fastest": _candidate("fastest", 50.0),
        },
    )

    result = await _destination_routes(engine, max_routes=2)

    assert _keys(result) == ["fastest", "easy"]


@pytest.mark.parametrize(
    ("fastest_difficulty", "expected"),
    [
        # 1本だけ返すときは基準線を先頭に固定しない——軸の重みが結果に現れなくなる
        (50.0, [("a", False)]),
        (5.0, [("fastest", True)]),
    ],
)
async def test_destination_with_a_single_route_does_not_pin_the_fastest(fastest_difficulty, expected):
    engine = FakeEngine(
        via=[_loop("a")],
        fastest=_loop("fastest"),
        candidates={"a": _candidate("a", 10.0), "fastest": _candidate("fastest", fastest_difficulty)},
    )

    result = await _destination_routes(engine, max_routes=1)

    assert [(c.edge_ids[0], c.is_fastest) for c in result] == expected


async def test_destination_without_a_fastest_route_marks_none_and_puts_unknown_difficulty_last():
    engine = FakeEngine(
        via=[_loop("unknown"), _loop("a")],
        candidates={"unknown": _candidate("unknown", None), "a": _candidate("a", 10.0)},
    )

    result = await _destination_routes(engine, max_routes=3)

    assert [(c.edge_ids[0], c.is_fastest) for c in result] == [("a", False), ("unknown", False)]


@pytest.mark.parametrize(
    ("context", "expected"),
    [
        (
            SimpleNamespace(destination_correction=Coordinates(latitude=35.71, longitude=139.81)),
            Coordinates(latitude=35.71, longitude=139.81),
        ),
        # 補正を持たないエンジンの文脈では、前の値を持ち越さずNone
        (SimpleNamespace(), None),
    ],
)
async def test_destination_passes_on_where_the_destination_was_moved_to(context, expected):
    engine = FakeEngine(context=context, via=[_loop("a")], candidates={"a": _candidate("a")})
    generator = RouteGenerator(engine)
    generator.last_destination_correction = DESTINATION

    await generator.generate_via_waypoints(ORIGIN, [], 10.0, destination=DESTINATION, start_time=START)

    assert generator.last_destination_correction == expected


@pytest.mark.parametrize(
    ("side", "reason"),
    [
        (
            "origin",
            f"起点{ORIGIN_LABEL}から走り出せる道が見つかりませんでした。出発地を道路沿いへ動かしてお試しください。",
        ),
        (
            "destination",
            "指定した目的地までの経路が見つかりませんでした。地点や除外する道路の設定を変えてお試しください。",
        ),
        (None, "指定した目的地までの経路が見つかりませんでした。地点や除外する道路の設定を変えてお試しください。"),
    ],
)
async def test_destination_without_alternatives_says_which_end_is_stuck(side, reason, caplog):
    context = SimpleNamespace() if side is None else SimpleNamespace(no_candidates_side=side)
    engine = FakeEngine(context=context)
    generator = RouteGenerator(engine)

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await generator.generate_via_waypoints(ORIGIN, [], 10.0, destination=DESTINATION, start_time=START) == []

    assert generator.last_no_candidates_reason == reason
    assert _warnings(caplog)
    assert "evaluate_loops" not in engine.calls
