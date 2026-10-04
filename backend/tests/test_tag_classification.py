"""`domain/traffic.py`のうち、点の種別を決めるSQL——タグからの引き当て（`tag_kind_sql`）・信号の判定
（`TRAFFIC_SIGNAL_SQL`）・地図へ出す種別と数える種別への読み替え（`stop_kind_sql`・`count_kind_sql`・`kind_map_sql`）。

式はどれも派生の段がDBで実行するので、ここでもDBで実行して答えを見る。入力は`VALUES`で与え、表は使わない。

ここで見ないもの:
- 道の通行方向を決めるSQL → `test_resolve_direction.py`
- 派生の段が引き当てた種別を表へ書き、近い点をまとめて数えること → `test_derive_node_materials.py`・`test_derive_counts.py`
"""

import json

import pytest
from sqlalchemy import text

from app.domain import traffic

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]


async def _kinds(engine, tags_by_id: dict[int, dict[str, str]]) -> dict[int, str]:
    """点（id → タグ）を`tag_kind_sql`へ通し、id → 種別を返す。当たらない点はキーを持たない。"""
    rows = ", ".join(f"(CAST(:id{i} AS bigint), CAST(:tags{i} AS jsonb))" for i in range(len(tags_by_id)))
    params = {}
    for i, (node_id, tags) in enumerate(tags_by_id.items()):
        params[f"id{i}"] = node_id
        params[f"tags{i}"] = json.dumps(tags)
    source = f"SELECT * FROM (VALUES {rows}) AS t(id, tags)"
    async with engine.connect() as conn:
        result = (await conn.execute(text(traffic.tag_kind_sql(source)), params)).all()
    kinds = {row.id: row.kind for row in result}
    assert len(kinds) == len(result), "1つの点に種別が2つ付いた"
    return kinds


async def _kind(engine, tags: dict[str, str]) -> str | None:
    return (await _kinds(engine, {1: tags})).get(1)


async def test_a_tag_in_the_rules_gives_its_kind(road_graph_engine):
    """種別は値で決まる。同じ`crossing`でも、線路の上なら踏切として数える側の種別になる。"""
    assert await _kinds(road_graph_engine, {
        1: {"highway": "crossing"},
        2: {"railway": "crossing"},
    }) == {1: "crossing", 2: "railway_crossing"}


async def test_values_are_matched_ignoring_case_and_surrounding_spaces(road_graph_engine):
    assert await _kind(road_graph_engine, {"highway": " Give_Way "}) == "give_way"


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        # 道路の横断歩道でもあり線路の踏切でもある点は、線路を渡る点として数える。
        ({"highway": "crossing", "railway": "crossing"}, "railway_crossing"),
        # 停止要因は補給・休憩より先に当たる。信号のあるコンビニの角は信号として数える。
        ({"highway": "traffic_signals", "shop": "convenience"}, "traffic_signals"),
        ({"traffic_calming": "hump", "amenity": "vending_machine", "vending": "drinks"}, "traffic_calming"),
    ],
)
async def test_a_point_with_two_meanings_gets_the_one_that_stops_the_rider(road_graph_engine, tags, expected):
    assert await _kind(road_graph_engine, tags) == expected


async def test_points_that_neither_stop_nor_supply_are_not_returned(road_graph_engine):
    assert await _kinds(road_graph_engine, {
        1: {},
        2: {"amenity": "vending_machine", "vending": "cigarettes"},
    }) == {}


@pytest.mark.parametrize(
    ("vending", "expected"),
    [
        # `;`で連なる値は、要素のどれかが飲食物なら飲料の自販機。
        ("cigarettes;coffee", "vending_drinks"),
        (" Coffee ", "vending_drinks"),
        # 何を売るか書かれていない自販機は、飲めるかどうか分からない自販機として残す。
        (None, "vending_unknown"),
        (" ; ", "vending_unknown"),
    ],
)
async def test_a_vending_machine_is_told_apart_by_what_it_sells(road_graph_engine, vending, expected):
    tags = {"amenity": " Vending_Machine "} | ({} if vending is None else {"vending": vending})

    assert await _kind(road_graph_engine, tags) == expected


async def _is_signal(engine, tags: dict[str, str]) -> bool:
    """派生の段と同じく、点を絞り込む条件として使って選ばれるか。"""
    async with engine.connect() as conn:
        return (await conn.execute(
            text(f"SELECT count(*) FROM (VALUES (CAST(:tags AS jsonb))) AS s(tags) WHERE {traffic.TRAFFIC_SIGNAL_SQL}"),
            {"tags": json.dumps(tags)},
        )).scalar_one() == 1


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"highway": "traffic_signals"}, True),
        # 横断歩道の位置に描かれた信号。`crossing`の値に`signals`を含むものを信号とする。
        ({"highway": "crossing", "crossing": "traffic_signals"}, True),
        ({"highway": "crossing", "crossing": "uncontrolled"}, False),
        # `crossing`の値だけでは、道路の横断歩道とは限らない。
        ({"railway": "crossing", "crossing": "traffic_signals"}, False),
    ],
)
async def test_a_signal_is_a_signal_node_or_a_crossing_controlled_by_signals(road_graph_engine, tags, expected):
    assert await _is_signal(road_graph_engine, tags) is expected


async def _read_kinds(engine, expression, kind: str, has_traffic_signals: bool):
    async with engine.connect() as conn:
        return (await conn.execute(
            text(f"SELECT {expression('nm')} FROM (VALUES (CAST(:kind AS text), CAST(:signals AS boolean)))"
                 " AS nm(kind, has_traffic_signals)"),
            {"kind": kind, "signals": has_traffic_signals},
        )).scalar_one()


@pytest.mark.parametrize(
    ("kind", "has_traffic_signals", "on_map", "counted_as"),
    [
        # 信号のある交差点の横断歩道は、利用者から見れば信号で、信号として1回数える。
        ("crossing", True, "traffic_signals", "signal"),
        ("crossing", False, "crossing", "crossing"),
        # 読み替えるのは信号と横断歩道だけ。近くに信号があっても一時停止は一時停止。
        ("stop", True, "stop", "stop"),
        # 補給・休憩は地図には出るが、停止の回数には入らない。
        ("convenience", True, "convenience", None),
    ],
)
async def test_the_map_and_the_count_read_the_same_signal(road_graph_engine, kind, has_traffic_signals, on_map, counted_as):
    """地図へ出す種別と数える種別は同じ読み替えから導く。別々だと、見えている信号の数と停止の回数が合わない。"""
    assert await _read_kinds(road_graph_engine, traffic.stop_kind_sql, kind, has_traffic_signals) == on_map
    assert await _read_kinds(road_graph_engine, traffic.count_kind_sql, kind, has_traffic_signals) == counted_as


async def test_a_kind_missing_from_the_map_falls_back_to_the_given_expression(road_graph_engine):
    expression = traffic.kind_map_sql("'barrier'", {"crossing": "横断"}, otherwise="'その他'")

    async with road_graph_engine.connect() as conn:
        assert (await conn.execute(text(f"SELECT {expression}"))).scalar_one() == "その他"
