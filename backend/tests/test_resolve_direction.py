"""`domain/traffic.py: direction_sql`——道のタグから、自転車が通れる向き（forward・backward・both）を決めるSQL。

式は派生の段がDBで実行するので、ここでもDBで実行して答えを見る。入力は`VALUES`で与え、表は使わない。

ここで見ないもの:
- 決めた向きを道の通行方向の表へ書くこと → 派生の段（`batch/derive_way_directions.py`）の責務
"""

import json

import pytest
from sqlalchemy import text

from app.domain import traffic

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def _directions(engine, tags_by_id: dict[int, dict[str, str]]) -> dict[int, str]:
    rows = ", ".join(f"(CAST(:id{i} AS bigint), CAST(:tags{i} AS jsonb))" for i in range(len(tags_by_id)))
    params = {}
    for i, (way_id, tags) in enumerate(tags_by_id.items()):
        params[f"id{i}"] = way_id
        params[f"tags{i}"] = json.dumps(tags)
    source = f"SELECT * FROM (VALUES {rows}) AS t(id, tags)"
    async with engine.connect() as conn:
        result = (await conn.execute(text(traffic.direction_sql(source)), params)).all()
    directions = {row.id: row.direction for row in result}
    assert len(directions) == len(result), "1本の道に向きが2つ付いた"
    return directions


async def _direction(engine, tags: dict[str, str]) -> str:
    return (await _directions(engine, {1: tags}))[1]


async def test_every_way_gets_a_direction_and_untagged_ways_are_two_way(road_graph_engine):
    """道は必ずどちらかに通れる。当たる規則が無い道も、結果から落ちずに両方向になる。"""
    assert await _directions(road_graph_engine, {
        1: {},
        2: {"oneway": "yes"},
    }) == {1: "both", 2: "forward"}


@pytest.mark.parametrize(
    ("oneway", "expected"),
    [
        (" TRUE ", "forward"),
        ("-1", "backward"),
        # 時間帯で向きが変わる等、向きを言い切れない値は一方通行にしない。
        ("alternating", "both"),
    ],
)
async def test_the_oneway_tag_decides_the_direction(road_graph_engine, oneway, expected):
    assert await _direction(road_graph_engine, {"oneway": oneway}) == expected


async def test_a_roundabout_is_one_way_without_a_oneway_tag(road_graph_engine):
    assert await _direction(road_graph_engine, {"junction": "roundabout"}) == "forward"


async def test_an_explicit_two_way_tag_overrides_the_roundabout(road_graph_engine):
    assert await _direction(road_graph_engine, {"junction": "roundabout", "oneway": "no"}) == "both"


async def test_a_oneway_value_that_says_nothing_leaves_the_roundabout_one_way(road_graph_engine):
    assert await _direction(road_graph_engine, {"junction": "roundabout", "oneway": "alternating"}) == "forward"


async def test_the_bicycle_exception_overrides_the_oneway_tag(road_graph_engine):
    """自転車は一方通行の規制の対象外（逆走できる）。"""
    assert await _direction(road_graph_engine, {"oneway": "yes", "oneway:bicycle": "no"}) == "both"
