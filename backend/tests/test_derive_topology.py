"""道路網の形の導出（`batch/derive_topology.py`）が、意図した形の派生を作ること。

見るのは、切る位置・閉じた区間の切り直し・枝数・区間の形と、長さと方位の測り方。
長さと方位は値そのものではなく性質を見る——長さは形状の測地線長であること、方位は始点→終点の
方位であること。

ここで見ないもの:
- 区間の端点がノードの行を持つこと——`road_edges`の端点の外部キー（`derived_models.py`）が断る
- 表へ入れられない区間（方位が無い・長さ0）を落とすこと——ここの道はどれも長さと方位を持ち、
  落とす分岐を通さない
"""

import pytest
import pytest_asyncio

from app.batch import derive_topology
from tests.source_ingest import ingest_records, way_record

# road_graph_session（conftest.py）と同じDBを使うため、.claude/rules/testing-backend.mdのパターン2どおり
# loop_scope="module"が必須。
pytestmark = pytest.mark.asyncio(loop_scope="module")

#: 東京都心付近。座標そのものに意味は無く、測地線長が0にならない間隔であればよい。
BASE_LON, BASE_LAT = 139.70, 35.68
STEP = 0.001

#: (wayのid, 参照ノードid列)。ノード3は2本の道が通るので切る位置になる。
#: ノード10で閉じる道は、中間でもう1回切られて自己ループでなくなる。
WAYS: tuple[tuple[int, list[int]], ...] = (
    (100, [1, 2, 3, 4]),
    (200, [3, 5]),
    (300, [10, 11, 12, 10]),
)


#: ノードidから座標を作る。閉じる道の終端だけ始点と同じ位置へ戻す。
def _point(node_id: int, ordinal: int) -> tuple[float, float]:
    index = 0 if node_id == 10 and ordinal == 3 else node_id
    return (BASE_LON + STEP * index, BASE_LAT + STEP * (index % 3))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def topology_conn(derive_conn):
    """道を取り込み、区間まで作った状態。"""
    conn = derive_conn
    await ingest_records("osm_way", [
        way_record(way_id, [_point(n, i) for i, n in enumerate(node_ids)], node_ids)
        for way_id, node_ids in WAYS], conn=conn)
    await derive_topology.derive(conn)
    return conn


async def test_splits_where_two_ways_pass_the_same_node(topology_conn):
    """2本の道が通るノードで切る。1回しか通らない中間のノードでは切らない。"""
    rows = await topology_conn.fetch(
        "SELECT osm_way_id, segment_index, from_node_id, to_node_id FROM road_edges"
        " WHERE osm_way_id IN (100, 200) ORDER BY osm_way_id, segment_index")
    assert [(r["osm_way_id"], r["segment_index"], r["from_node_id"], r["to_node_id"])
            for r in rows] == [
        # ノード2は道100しか通らないので切らない。
        (100, 0, 1, 3),
        (100, 1, 3, 4),
        (200, 0, 3, 5),
    ]


async def test_closed_segment_is_split_again_so_no_self_loop_remains(topology_conn):
    """始点＝終点の区間は中間でもう1回切る（閉じた線に方位が定義できないため）。"""
    rows = await topology_conn.fetch(
        "SELECT segment_index, from_node_id, to_node_id FROM road_edges"
        " WHERE osm_way_id = 300 ORDER BY segment_index")
    assert [(r["from_node_id"], r["to_node_id"]) for r in rows] == [(10, 11), (11, 10)]


async def test_branch_count_is_the_number_of_segment_ends_at_the_node(topology_conn):
    """枝数は「そこに集まる道の本数」＝区間の端点としての出現回数。"""
    rows = await topology_conn.fetch(
        "SELECT osm_node_id, branch_count FROM road_nodes ORDER BY osm_node_id")
    assert {r["osm_node_id"]: r["branch_count"] for r in rows} == {
        1: 1,   # 道100の始端
        3: 3,   # 道100の2区間が接し、道200が出る
        4: 1,
        5: 1,
        10: 2,  # 閉じた道の両端
        11: 2,  # 切り直しで生まれた端点
        # ノード2・12は区間の端にならないので行が無い。
    }


async def test_distance_is_the_geodesic_length_of_the_geometry(topology_conn):
    """長さは形状から導ける値そのもの。測地線（楕円体）で測り、丸めない。

    丸めないのは、4.8 cmの区間が0へ落ちないようにするため。球で近似しないのは、
    費用が変わらないのに近似になるため。
    """
    wrong = await topology_conn.fetchval(
        "SELECT count(*) FROM road_edges"
        " WHERE abs(distance_m - ST_Length(geom::geography)) > 0.001")
    assert wrong == 0


async def test_bearings_are_measured_from_the_shape_ends(topology_conn):
    """順方向は始点→終点、逆向きは終点→始点で測る（+180°の単純反転にしない）。"""
    wrong = await topology_conn.fetchval("""
        SELECT count(*) FROM road_edges WHERE
          abs(bearing_deg - degrees(ST_Azimuth(ST_StartPoint(geom)::geography,
                                               ST_EndPoint(geom)::geography))) > 0.001
          OR abs(reverse_bearing_deg - degrees(ST_Azimuth(ST_EndPoint(geom)::geography,
                                               ST_StartPoint(geom)::geography))) > 0.001""")
    assert wrong == 0


async def test_geometry_follows_the_shape_between_the_cut_points(topology_conn):
    """区間の形状は、切った位置の間の頂点をそのまま並べたもの。"""
    row = await topology_conn.fetchrow(
        "SELECT ST_NumPoints(geom) AS n, ST_AsText(ST_StartPoint(geom)) AS head"
        " FROM road_edges WHERE osm_way_id = 100 AND segment_index = 0")
    # ノード1・2・3の3頂点（中間のノード2は切らないが形状には残る）。
    assert row["n"] == 3
    assert row["head"].startswith("POINT(139.701 ")
