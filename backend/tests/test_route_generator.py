"""`services/route_generator.py`——ルート生成の戦略層（周回・経由地・目的地・乗り換えの4つの入口）。

ここで見ないもの:
- 折返し点の選定・経路探索・評価の中身 → `RoadGraphEngine`（`test_road_graph_engine.py`）。ここでは代役に置き換える
- 区間から候補への集約の計算（距離加重平均・丸め） → `test_route.py`・`domain/difficulty.py`のテスト
- APIの受け口（ジョブの投稿・202） → `test_routes_generate.py`
- エンジンへ渡す引数（探索の範囲・経由地の並び・出発時刻・候補数）と、エンジンを呼んだか・何回か → 読むだけの呼び出しなので
  確かめない。経由地を順に通って起点か目的地で終わることは`test_route_generation_behavior.py`が経路で見る。経由地・目的地を
  探索の範囲に入れることは、範囲の余白が小さな格子を覆って入口の結果に現れないため確かめず、理由は実装のコメントが持つ
- 前の生成の理由・目的地の補正を持ち越さないこと → 本番は生成ごとに`RouteGenerator`を作るので、持ち越す状態が起こらない

エンジンの代役は、各メソッドを`RoadGraphEngine`の同名メソッドの署名へ当ててから呼ぶ（`bound`）。応答を返すだけで、呼ばれ方を記録しない。
代役が返す探索結果・候補は本物の型（`TracedLoop`・`LoopTurnaround`・`RouteCandidate`）で作る。
探索の文脈（`context`）は戦略層にとって中身を読まない値で、読むのは`destination_correction`と
`no_candidates_side`の2属性だけのため、その2属性だけを持つ器で渡す。
"""

import logging
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.domain.difficulty import OverallDifficulty
from app.domain.errors import SearchAreaTooLargeError
from app.domain.loop_routing import LoopTurnaround, TracedLoop
from app.domain.route import Coordinates, RouteCandidate, RouteSegmentDetail
from app.domain.time_zone import JST
from app.services import route_generator
from app.services.road_graph_engine import RoadGraphEngine
from app.services.route_generator import DEFAULT_MAX_ROUTES, RouteGenerator
from tests.bound_fake import bound

ORIGIN = Coordinates(latitude=35.6789, longitude=139.7712)
ORIGIN_LABEL = "(35.68,139.77)"  # 常時出るログ・利用者向けの理由は座標を小数2桁で出す
WAYPOINT = Coordinates(latitude=35.69, longitude=139.78)
DESTINATION = Coordinates(latitude=35.70, longitude=139.80)
START = datetime(2026, 9, 24, 8, 0, tzinfo=JST)
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


def _context(no_candidates_side=None) -> SimpleNamespace:
    return SimpleNamespace(destination_correction=None, no_candidates_side=no_candidates_side)


def _turnaround(outcome: TracedLoop | Exception) -> LoopTurnaround:
    """復路探索の結果（または失敗）を`data`に抱えた折返し点。`data`はエンジンだけが読む。"""
    return LoopTurnaround(bearing=0, outbound_difficulty=None, data=outcome)


_UNSET = object()


def _engine_method(fake):
    return bound(getattr(RoadGraphEngine, fake.__name__), fake)


class FakeEngine:
    """`RoadGraphEngine`の代役（層の境目）。"""

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
        self.context = _context() if context is _UNSET else context
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

    @_engine_method
    async def prepare(self, origin, radius_km, now, waypoints=None):
        if self.prepare_error is not None:
            raise self.prepare_error
        return self.context

    @_engine_method
    async def select_loop_turnarounds(self, context, distance_km, distance_tolerance_km, pool_size):
        return list(self.turnarounds)

    @_engine_method
    async def trace_loop_from_turnaround(self, context, turnaround):
        if isinstance(turnaround.data, Exception):
            raise turnaround.data
        return turnaround.data

    @_engine_method
    def is_loop_too_similar(self, context, candidate, accepted):
        return candidate.data[0] in self.similar

    @_engine_method
    async def evaluate_loops(self, context, traced, start_time):
        if self.drop_evaluated:
            return []
        return [self.candidates[t.data[0]] for t in traced]

    @_engine_method
    async def trace_loop(self, context, waypoints, bearing):
        if self.trace_error is not None:
            raise self.trace_error
        return self.waypoint_loop

    @_engine_method
    def build_traced_from_edge_ids(self, context, edge_ids, destination=None):
        if self.build_error is not None:
            raise self.build_error
        return TracedLoop(bearing=None, distance_km=3.0, data=list(edge_ids), leg_of_edge=[0] * len(edge_ids))

    @_engine_method
    async def select_via_nodes(self, context, destination, max_routes):
        return list(self.via)

    @_engine_method
    async def select_fastest_route(self, context, destination):
        return self.fastest


ENTRANCES = {
    "loops": lambda gen, **kw: gen.generate_loops(ORIGIN, 10.0, 1.0, max_routes=DEFAULT_MAX_ROUTES, **kw),
    "via_waypoints": lambda gen, **kw: gen.generate_via_waypoints(
        ORIGIN, [WAYPOINT], 10.0, destination=None, max_routes=1, **kw),
    "destination": lambda gen, **kw: gen.generate_via_waypoints(
        ORIGIN, [], 10.0, destination=DESTINATION, max_routes=1, **kw),
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


async def test_too_large_search_area_gives_no_candidates_and_says_why(caplog):
    """どの入口も上の未整備と同じ所で土台を作るので、もう片方の断り方は1つの入口で見る。"""
    engine = FakeEngine(prepare_error=SearchAreaTooLargeError(edges=1_300_000, limit=1_200_000))
    generator = RouteGenerator(engine)

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await ENTRANCES["loops"](generator, start_time=START) == []

    assert "探索範囲の道路が多すぎる" in generator.last_no_candidates_reason
    assert any("edges=1300000" in r.getMessage() for r in _warnings(caplog))


@pytest.mark.parametrize(
    ("segments", "expected"),
    [
        ([_segment(10.0), _segment(30.0)], OverallDifficulty(average=20.0, load=40.0)),  # 総量は平均20 × 2km
        ([], OverallDifficulty(average=99.0, load=99.0)),  # 区間が無ければ、エンジンの値のまま
    ],
)
async def test_candidate_values_are_rebuilt_from_its_segments(segments, expected):
    evaluated = _candidate("e1", segments=segments, overall_difficulty=OverallDifficulty(average=99.0, load=99.0))
    engine = FakeEngine(candidates={"e1": evaluated})

    (candidate,) = await RouteGenerator(engine).generate_spliced_route(ORIGIN, DESTINATION, 10.0, ["e1"], START)

    assert candidate.overall_difficulty == expected


async def test_evaluation_that_does_not_answer_every_route_is_an_error():
    engine = FakeEngine(turnarounds=[_turnaround(_loop("a"))], candidates={"a": _candidate("a")}, drop_evaluated=True)

    with pytest.raises(route_generator.RoutingError):
        await RouteGenerator(engine).generate_loops(ORIGIN, 10.0, 1.0, start_time=START, max_routes=DEFAULT_MAX_ROUTES)


# ---- 周回 ----


def test_turnaround_pool_can_always_fill_the_requested_routes_and_is_capped():
    for max_routes in range(1, route_generator.MAX_ROUTES + 1):
        pool = route_generator.turnaround_pool_size(max_routes)
        assert max_routes <= pool <= route_generator.TURNAROUND_POOL_MAX


async def test_loops_without_turnarounds_say_how_far_was_searched(caplog):
    engine = FakeEngine()
    generator = RouteGenerator(engine)

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await generator.generate_loops(ORIGIN, 10.0, 1.0, start_time=START, max_routes=DEFAULT_MAX_ROUTES) == []

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
        result = await RouteGenerator(engine).generate_loops(ORIGIN, 10.0, 1.0, start_time=START, max_routes=DEFAULT_MAX_ROUTES)

    assert [c.direction_label for c in result] == ["方位-a"]
    # 想定外の例外だけはエンジンの不具合として、スタックトレース付きのERRORで残す
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert errors[0].exc_info is not None
    assert isinstance(errors[0].exc_info[1], RuntimeError)


async def test_loops_keep_only_routes_within_the_distance_tolerance():
    lengths = {"exact": 11.0, "over": 11.5, "under": 8.9}
    engine = FakeEngine(
        turnarounds=[_turnaround(_loop(k, distance_km=d)) for k, d in lengths.items()],
        candidates={k: _candidate(k) for k in lengths},
    )

    result = await RouteGenerator(engine).generate_loops(ORIGIN, 10.0, 1.0, start_time=START, max_routes=DEFAULT_MAX_ROUTES)

    # 目標±許容のちょうど端は含む。目標より短い側も同じ幅で外す
    assert [c.direction_label for c in result] == ["方位-exact"]


async def test_loops_drop_a_route_too_similar_to_one_already_accepted():
    keys = ["a", "b", "c"]
    engine = FakeEngine(
        turnarounds=[_turnaround(_loop(k)) for k in keys],
        similar={"b"},
        candidates={k: _candidate(k) for k in keys},
    )

    result = await RouteGenerator(engine).generate_loops(ORIGIN, 10.0, 1.0, start_time=START, max_routes=DEFAULT_MAX_ROUTES)

    assert sorted(c.direction_label for c in result) == ["方位-a", "方位-c"]


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
            "1件の折返し候補で復路の探索に失敗しました[除外設定をご確認ください]。",
        ),
        (
            [_loop("x", distance_km=20.0), _loop("y", distance_km=1.0)],
            "2件の周回候補は指定距離[10.0km±1.0km]から外れました。",
        ),
    ],
)
async def test_loops_that_all_fall_out_say_why(outcomes, reason, caplog):
    engine = FakeEngine(turnarounds=[_turnaround(o) for o in outcomes])
    generator = RouteGenerator(engine)

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await generator.generate_loops(ORIGIN, 10.0, 1.0, start_time=START, max_routes=DEFAULT_MAX_ROUTES) == []

    assert generator.last_no_candidates_reason == reason + "距離や除外する道路の設定を変えてお試しください。"
    assert _warnings(caplog)


# ---- 経由地 ----


@pytest.mark.parametrize(
    ("destination", "labels"),
    [
        (None, ("engine-w", "方位-w")),  # 起点へ戻る経路は、エンジンが付けたidと方位ラベルのまま
        (DESTINATION, ("route-destination", "目的地ルート")),
    ],
)
async def test_waypoint_route_is_labelled_as_a_destination_route_only_when_it_ends_at_one(destination, labels):
    engine = FakeEngine(waypoint_loop=_loop("w", bearing=None), candidates={"w": _candidate("w")})

    result = await RouteGenerator(engine).generate_via_waypoints(
        ORIGIN, [WAYPOINT], 10.0, destination=destination, max_routes=5, start_time=START
    )

    # 経由地があるときは、候補数の指定によらず1本
    assert [(c.id, c.direction_label) for c in result] == [labels]


async def test_waypoints_that_cannot_be_connected_give_no_candidates_and_say_why(caplog):
    engine = FakeEngine(trace_error=route_generator.RoutingError("到達不能"))
    generator = RouteGenerator(engine)

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await generator.generate_via_waypoints(ORIGIN, [WAYPOINT], 10.0, start_time=START, destination=None, max_routes=1) == []

    assert generator.last_no_candidates_reason == (
        "指定した経由地・目的地を通る経路が見つかりませんでした。地点や除外する道路の設定を変えてお試しください。"
    )
    assert _warnings(caplog)


# ---- 区間の乗り換え ----


async def test_spliced_route_is_labelled():
    engine = FakeEngine(candidates={"e1": _candidate("e1")})

    result = await RouteGenerator(engine).generate_spliced_route(ORIGIN, DESTINATION, 10.0, ["e1", "e2"], START)

    assert [(c.id, c.direction_label) for c in result] == [(route_generator.SPLICED_ROUTE_ID, "組み合わせたルート")]


async def test_spliced_route_that_does_not_connect_says_so_without_internal_ids(caplog):
    engine = FakeEngine(build_error=route_generator.RoutingError("edge_id=osm-123 がつながっていない"))
    generator = RouteGenerator(engine)

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await generator.generate_spliced_route(ORIGIN, DESTINATION, 10.0, ["osm-123"], START) == []

    assert generator.last_no_candidates_reason == (
        "組み合わせた経路がつながっていないため評価できませんでした。区間の選び直しか、ルートの再生成をお試しください。"
    )
    # 原因（内部の識別子を含む）はログにだけ残す
    assert any("osm-123" in r.getMessage() for r in _warnings(caplog))


# ---- 目的地（経由地なし） ----


async def _destination_routes(engine: FakeEngine, max_routes: int) -> list[RouteCandidate]:
    return await RouteGenerator(engine).generate_via_waypoints(
        ORIGIN, [], 10.0, destination=DESTINATION, max_routes=max_routes, start_time=START
    )


async def test_destination_adds_the_fastest_route_and_orders_all_easiest_first():
    engine = FakeEngine(
        via=[_loop("hard"), _loop("easy")],
        fastest=_loop("fastest"),
        candidates={
            "hard": _candidate("hard", 30.0),
            "easy": _candidate("easy", 10.0),
            "fastest": _candidate("fastest", 20.0),
        },
    )

    result = await _destination_routes(engine, max_routes=3)

    assert _keys(result) == ["easy", "fastest", "hard"]
    assert [c.id for c in result] == ["route-destination-00", "route-destination-01", "route-destination-02"]
    assert {c.direction_label for c in result} == {"目的地ルート"}


async def test_destination_does_not_add_the_fastest_twice_when_an_alternative_is_already_it():
    engine = FakeEngine(
        via=[_loop("hard"), _loop("easy")],
        fastest=_loop("hard"),
        candidates={"hard": _candidate("hard", 30.0), "easy": _candidate("easy", 10.0)},
    )

    result = await _destination_routes(engine, max_routes=3)

    assert _keys(result) == ["easy", "hard"]


@pytest.mark.parametrize(
    ("max_routes", "expected"),
    [
        (2, ["easy", "fastest"]),  # 難易度で最下位の基準線を残し、その次に難しい候補を切る
        (1, ["easy"]),  # 1本だけ返すときは基準線を残さない——軸の重みが結果に現れなくなる
    ],
)
async def test_destination_cuts_the_hardest_routes_but_keeps_the_fastest_unless_returning_one(max_routes, expected):
    engine = FakeEngine(
        via=[_loop("hard"), _loop("easy")],
        fastest=_loop("fastest"),
        candidates={
            "hard": _candidate("hard", 30.0),
            "easy": _candidate("easy", 10.0),
            "fastest": _candidate("fastest", 50.0),
        },
    )

    result = await _destination_routes(engine, max_routes=max_routes)

    assert _keys(result) == expected


async def test_destination_without_a_fastest_route_returns_the_alternatives():
    engine = FakeEngine(via=[_loop("a")], candidates={"a": _candidate("a")})

    assert _keys(await _destination_routes(engine, max_routes=3)) == ["a"]


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
    ],
)
async def test_destination_without_alternatives_says_which_end_is_stuck(side, reason, caplog):
    context = _context(no_candidates_side=side)
    engine = FakeEngine(context=context)
    generator = RouteGenerator(engine)

    with caplog.at_level(logging.WARNING, logger=route_generator.logger.name):
        assert await generator.generate_via_waypoints(ORIGIN, [], 10.0, destination=DESTINATION, start_time=START, max_routes=1) == []

    assert generator.last_no_candidates_reason == reason
    assert _warnings(caplog)
