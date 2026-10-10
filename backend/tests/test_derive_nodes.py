"""ノードの種別と頂点の値（`batch/derive_nodes.py`）の信号の近接判定と、流し直したときの値。

見ないもの: タグから種別・信号への読み替えの両側 → `test_tag_classification.py`。管理画面で変えた半径が
この段へ渡ること → `test_derive_cli.py`。
"""

import asyncpg
import pytest
import pytest_asyncio

from app.batch import derive_nodes, derive_topology
from app.domain.traffic import HIGHWAY_RANK
from app.domain.tuning import TUNING_PARAMETERS_BY_ID
from tests.conftest import empty_ingested_tables
from tests.source_ingest import ingest_records, point_record, way_record

# road_graph_session（conftest.py）と同じDBを使うため、.claude/rules/testing-backend.mdのパターン2どおり
# loop_scope="module"・xdist_group="postgis"が必須。
pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

BASE_LON, BASE_LAT = 139.70, 35.68
#: 信号とみなす半径（較正値の既定）。
RADIUS_M = TUNING_PARAMETERS_BY_ID["signal.match_radius_m"].default
#: 経度0.001度は約90m。信号とみなす半径より十分に遠い。
STEP = 0.001
#: 経度0.0001度は約9m。半径の内側。
NEAR = 0.0001

WAYS: tuple[tuple[int, list[int]], ...] = ((100, [1, 3]), (200, [3, 5]))

#: (ノードid, 経度, 緯度, タグ)。9はどの道にも属さない信号で、ノード5のすぐ隣に立つ。
NODES: tuple[tuple[int, float, float, dict[str, str]], ...] = (
    (1, BASE_LON + STEP * 1, BASE_LAT, {}),
    (3, BASE_LON + STEP * 3, BASE_LAT, {"highway": "traffic_signals"}),
    (5, BASE_LON + STEP * 5, BASE_LAT, {}),
    (9, BASE_LON + STEP * 5 + NEAR, BASE_LAT, {"highway": "traffic_signals"}),
)


async def _ingest(conn: asyncpg.Connection, *, way_tags: dict[int, dict[str, str]] | None = None,
                  node_tags: dict[int, dict[str, str]] | None = None) -> None:
    """`WAYS`と`NODES`を取り込む。`way_tags`・`node_tags`はidごとにタグを差し替える（無ければ宣言のまま）。"""
    way_tags, node_tags = way_tags or {}, node_tags or {}
    position = {node_id: (lon, lat) for node_id, lon, lat, _ in NODES}
    await ingest_records("osm_way", [
        way_record(way_id, [position[n] for n in node_ids], node_ids, way_tags.get(way_id))
        for way_id, node_ids in WAYS], conn=conn)
    await ingest_records("osm_node", [
        point_record(node_id, lon, lat, node_tags.get(node_id, tags))
        for node_id, lon, lat, tags in NODES], conn=conn)


async def _signals(conn: asyncpg.Connection) -> dict[int, bool]:
    rows = await conn.fetch("SELECT osm_node_id, has_traffic_signals FROM node_turns"
                            " UNION SELECT osm_node_id, has_traffic_signals FROM node_kinds")
    return {r["osm_node_id"]: r["has_traffic_signals"] for r in rows}


@pytest_asyncio.fixture(loop_scope="module")
async def node_conn(derive_conn):
    """テストごとに同じ生データから作り直す。生データのタグを書き換えるテストがあるため。"""
    conn = derive_conn
    await empty_ingested_tables(conn)
    await _ingest(conn)
    await derive_topology.derive(conn)
    await derive_nodes.derive(conn, RADIUS_M)
    return conn


async def test_node_near_a_signal_is_flagged_and_far_one_is_not(node_conn):
    """信号の半径内にあるノードだけが信号付きになる。信号ノード自身も含む。"""
    assert await _signals(node_conn) == {1: False, 3: True, 5: True, 9: True}


async def _values(conn: asyncpg.Connection) -> dict[int, tuple[bool, bool, int]]:
    """ノードごとの (種別が付いているか, 信号付きか, 最大階級)。"""
    rows = await conn.fetch(
        "SELECT osm_node_id, k.kind, coalesce(t.has_traffic_signals, k.has_traffic_signals) AS has_traffic_signals,"
        " coalesce(t.max_highway_rank, 0) AS max_highway_rank"
        " FROM node_turns t FULL JOIN node_kinds k USING (osm_node_id)")
    return {r["osm_node_id"]: (r["kind"] is not None, r["has_traffic_signals"],
                               r["max_highway_rank"]) for r in rows}


async def test_rerun_on_changed_input_keeps_no_value_the_input_no_longer_supports(node_conn):
    """入力を変えて流し直すと、今の生データでは値の出ない行に前回の値が残らない。
    タグが消えたノードは種別と信号の印を失い、階級の無い道になれば最大階級は0に戻り、
    種別のためだけにあった行（どの道にも属さないノード）は行ごと消える。"""
    primary = HIGHWAY_RANK["primary"]
    await _ingest(node_conn, way_tags={100: {"highway": "primary"}})
    await derive_nodes.derive(node_conn, RADIUS_M)
    before = await _values(node_conn)
    await _ingest(node_conn, node_tags={3: {}, 9: {}})
    await derive_nodes.derive(node_conn, RADIUS_M)
    after = await _values(node_conn)

    # 前提: 1回目は値が出ている。
    assert before == {1: (False, False, primary), 3: (True, True, primary),
                      5: (False, True, 0), 9: (True, True, 0)}
    assert after == {1: (False, False, 0), 3: (False, False, 0), 5: (False, False, 0)}
