"""タグ→種別の引き当て（`domain/traffic.py: tag_kind_sql`）。

停止要因（信号・横断歩道・踏切・車止め）と補給休憩（コンビニ・自販機・トイレ等）を、
1つの表で引き当てる。結果は`node_materials.kind`に入り、停止回数の数え上げと
補給POIレイヤーの母集団になる。

**判定はDB側で行うため、DBへ通して確かめる。**表の中身だけを見るテストは
`test_traffic.py`にあり、こちらは表が実際にどう引き当てられるか（優先順位・値の
正規化・`;`連結の扱い）を押さえる。
"""

import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.traffic import tag_kind_sql

# road_graph_session（conftest.py）はファイル単位でエンジン・イベントループを共有する設計
# のため、docs/conventions/testing.mdのパターン2どおりloop_scope="module"・xdist_group="postgis"が必須。
pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]


async def classify(session: AsyncSession, tags: dict) -> str | None:
    literal = "'" + json.dumps(tags, ensure_ascii=False).replace("'", "''") + "'"
    sql = tag_kind_sql(f"SELECT 1 AS id, {literal}::jsonb AS tags")
    row = (await session.execute(text(sql))).first()
    return None if row is None else row.kind


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"highway": "traffic_signals"}, "traffic_signals"),
        ({"highway": "crossing"}, "crossing"),
        ({"highway": "stop"}, "stop"),
        ({"highway": "give_way"}, "give_way"),
        ({"railway": "level_crossing"}, "level_crossing"),
        # 前後の空白と大文字小文字は正規化する。
        ({"highway": " Traffic_Signals "}, "traffic_signals"),
        ({}, None),
        ({"highway": "residential"}, None),
    ],
)
async def test_stop_factors(road_graph_session, tags, expected):
    assert await classify(road_graph_session, tags) == expected


@pytest.mark.parametrize(
    "value", ["cycle_barrier", "bollard", "gate", "lift_gate", "stile", "block", "chain"])
async def test_barrier_values_are_classified(road_graph_session, value):
    assert await classify(road_graph_session, {"barrier": value}) == "barrier"


@pytest.mark.parametrize(
    "value", ["hump", "bump", "table", "cushion", "chicane", "rumble_strip"])
async def test_traffic_calming_values_are_classified(road_graph_session, value):
    assert await classify(road_graph_session, {"traffic_calming": value}) == "traffic_calming"


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        # 踏切と横断歩道タグが同一nodeに同居する場合、踏切側を優先する（一時停止義務が強い）。
        ({"highway": "crossing", "railway": "level_crossing"}, "level_crossing"),
        # 踏切に車止めが併設されている点。止まる理由としては踏切の方が強い。
        ({"railway": "level_crossing", "barrier": "gate"}, "level_crossing"),
        # 停止要因と補給が同居しても、停止要因が先に当たる。
        ({"highway": "traffic_signals", "shop": "convenience"}, "traffic_signals"),
    ],
)
async def test_priority_between_tags(road_graph_session, tags, expected):
    assert await classify(road_graph_session, tags) == expected


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"shop": "convenience"}, "convenience"),
        ({"amenity": "toilets"}, "toilets"),
        ({"amenity": "drinking_water"}, "drinking_water"),
        ({"amenity": "bicycle_parking"}, "bicycle_parking"),
        ({"shop": " Convenience "}, "convenience"),
        ({"shop": "supermarket"}, None),
        ({"amenity": "restaurant"}, None),
    ],
)
async def test_supply_points(road_graph_session, tags, expected):
    assert await classify(road_graph_session, tags) == expected


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"amenity": "vending_machine", "vending": "drinks"}, "vending_drinks"),
        # 複数の値は`;`で連結される。1つでも飲食物があれば飲料自販機として扱う。
        ({"amenity": "vending_machine", "vending": "cigarettes;drinks"}, "vending_drinks"),
        # タグが無いものを「買えない」側へ寄せない（日本では飲料でも付けない慣習がある）。
        ({"amenity": "vending_machine"}, "vending_unknown"),
        ({"amenity": "vending_machine", "vending": " "}, "vending_unknown"),
        # たばこ・切符・パーキング券の機械は取り込まない（当てにされると買えない）。
        ({"amenity": "vending_machine", "vending": "cigarettes"}, None),
        ({"amenity": "vending_machine", "vending": "parking_tickets"}, None),
        ({"amenity": "vending_machine", "vending": "public_transport_tickets"}, None),
        ({"amenity": "vending_machine", "vending": "condoms"}, None),
    ],
)
async def test_vending_machines(road_graph_session, tags, expected):
    assert await classify(road_graph_session, tags) == expected


async def test_many_nodes_at_once_keep_one_kind_each(road_graph_session):
    """本番の使われ方（多数の行を一度に引き当てる）でも、1行につき種別は1つになる。"""
    rows = ", ".join(
        f"({i}, '{json.dumps(tags)}'::jsonb)" for i, tags in enumerate([
            {"highway": "traffic_signals"},
            {"highway": "crossing", "railway": "level_crossing"},
            {"shop": "convenience"},
            {"amenity": "vending_machine", "vending": "drinks"},
            {"highway": "residential"},
        ]))
    sql = tag_kind_sql(f"SELECT * FROM (VALUES {rows}) AS v(id, tags)")
    got = {r.id: r.kind for r in (await road_graph_session.execute(text(sql))).all()}
    assert got == {0: "traffic_signals", 1: "level_crossing", 2: "convenience",
                   3: "vending_drinks"}
