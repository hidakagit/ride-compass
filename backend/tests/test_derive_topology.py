"""道路網の形の導出（`batch/derive_topology.py`）が、意図した形の派生を作ること。

**このバッチが負う契約をここで押さえる。**移行時に旧実装と突き合わせた関門は一回きりの
道具で、旧実装を消すと何も残らない。読む側のテストは合成フィクスチャを使うため、
ここが落ちなければ誰も気づかない。

値そのものではなく性質を見る——長さは形状の測地線長であること、方位は始点→終点の
方位であること。数値を固定したい相手は自分の合成データで固定する。
"""

import json
import struct
from datetime import UTC, datetime

import asyncpg
import pytest
import pytest_asyncio

from app.batch import derive_topology
from app.batch._common import asyncpg_dsn
from app.batch.ingest import ensure_partition
from tests.conftest import postgis_database_url

# road_graph_session（conftest.py）と同じDBを使うため、docs/conventions/testing.mdのパターン2どおり
# loop_scope="module"・xdist_group="postgis"が必須。
pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

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


TABLES = ("edge_materials", "way_materials", "road_edges", "node_materials",
          "source_features", "source_runs")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def topology_conn():
    conn = await asyncpg.connect(asyncpg_dsn(postgis_database_url()))
    try:
        await ensure_partition(conn, "osm_way")
        await conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        run_id = await conn.fetchval(
            "INSERT INTO source_runs (source, status, started_at, origin, profile, counts)"
            " VALUES ('osm_way', 'succeeded', $1, $2, $2, $2) RETURNING run_id",
            datetime.now(UTC), json.dumps({}))
        for way_id, node_ids in WAYS:
            points = [_point(n, i) for i, n in enumerate(node_ids)]
            wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in points) + ")"
            await conn.execute(
                "INSERT INTO source_features (source, natural_key, run_id, geom, attrs, payload)"
                " VALUES ('osm_way', $1, $2, ST_GeomFromText($3, 4326), '{}'::jsonb, $4)",
                str(way_id), run_id, wkt,
                struct.pack(f"<{len(node_ids)}q", *node_ids))
        await derive_topology.derive(conn)
        yield conn
    finally:
        await conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        await conn.close()


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

    assert await topology_conn.fetchval(
        "SELECT count(*) FROM road_edges WHERE from_node_id = to_node_id") == 0


async def test_branch_count_is_the_number_of_segment_ends_at_the_node(topology_conn):
    """枝数は「そこに集まる道の本数」＝区間の端点としての出現回数。"""
    rows = await topology_conn.fetch(
        "SELECT osm_node_id, branch_count FROM node_materials ORDER BY osm_node_id")
    assert {r["osm_node_id"]: r["branch_count"] for r in rows} == {
        1: 1,   # 道100の始端
        3: 3,   # 道100の2区間が接し、道200が出る
        4: 1,
        5: 1,
        10: 2,  # 閉じた道の両端
        11: 2,  # 切り直しで生まれた端点
        # ノード2・12は区間の端にならないので行が無い。
    }


async def test_every_endpoint_has_a_node_row(topology_conn):
    """端点は必ず`node_materials`にある（外部キーが縛る先を先に作る）。"""
    missing = await topology_conn.fetchval("""
        SELECT count(*) FROM (
            SELECT from_node_id AS id FROM road_edges
            UNION SELECT to_node_id FROM road_edges) e
        LEFT JOIN node_materials nm ON nm.osm_node_id = e.id
        WHERE nm.osm_node_id IS NULL""")
    assert missing == 0


async def test_edge_materials_has_one_empty_row_per_segment(topology_conn):
    """値を出すバッチが埋める器を、区間と同時に作る。未計算はNULLで表す。"""
    counts = await topology_conn.fetchrow(
        "SELECT (SELECT count(*) FROM road_edges) AS edges,"
        " (SELECT count(*) FROM edge_materials) AS materials,"
        " (SELECT count(*) FROM edge_materials"
        "  WHERE accident_count IS NOT NULL OR intersection_count IS NOT NULL) AS filled")
    # 道100が2区間・道200が1区間・道300が切り直して2区間。
    assert counts["edges"] == counts["materials"] == 5
    assert counts["filled"] == 0


async def test_distance_is_the_geodesic_length_of_the_geometry(topology_conn):
    """長さは形状から導ける値そのもの。測地線（楕円体）で測り、丸めない。

    丸めないのは、4.8 cmの区間が0へ落ちないようにするため。球で近似しないのは、
    費用が変わらないのに近似になるため。
    """
    wrong = await topology_conn.fetchval(
        "SELECT count(*) FROM road_edges"
        " WHERE abs(distance_m - ST_Length(geom::geography)) > 0.001")
    assert wrong == 0
    assert await topology_conn.fetchval(
        "SELECT count(*) FROM road_edges WHERE distance_m <= 0") == 0


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
