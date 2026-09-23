"""ノードに付く値（`batch/derive_node_materials.py`）のうち、信号の近接判定。"""

import json
import struct
from datetime import UTC, datetime

import asyncpg
import pytest
import pytest_asyncio

from app.batch import derive_node_materials, derive_topology
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

BASE_LON, BASE_LAT = 139.70, 35.68
#: 経度0.001度は約90m。信号とみなす半径（25m）より十分に遠い。
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

TABLES = ("edge_materials", "way_materials", "road_edges", "node_materials",
          "source_features", "source_runs")


async def _insert_run(conn: asyncpg.Connection, source: str) -> int:
    return await conn.fetchval(
        "INSERT INTO source_runs (source, status, started_at, origin, profile, counts)"
        " VALUES ($1, 'succeeded', $2, $3, $3, $3) RETURNING run_id",
        source, datetime.now(UTC), json.dumps({}))


async def _signals(conn: asyncpg.Connection) -> dict[int, bool]:
    rows = await conn.fetch("SELECT osm_node_id, has_traffic_signals FROM node_materials")
    return {r["osm_node_id"]: r["has_traffic_signals"] for r in rows}


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def node_conn(road_graph_engine):
    """`road_graph_engine`に依存するのはスキーマを作らせるため（`test_derive_topology.py`と同じ）。"""
    conn = await asyncpg.connect(asyncpg_dsn(postgis_database_url()))
    try:
        for source in ("osm_way", "osm_node"):
            await ensure_partition(conn, source)
        await conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        way_run = await _insert_run(conn, "osm_way")
        position = {node_id: (lon, lat) for node_id, lon, lat, _ in NODES}
        for way_id, node_ids in WAYS:
            wkt = "LINESTRING(" + ", ".join(
                "{} {}".format(*position[n]) for n in node_ids) + ")"
            await conn.execute(
                "INSERT INTO source_features (source, natural_key, run_id, geom, attrs, payload)"
                " VALUES ('osm_way', $1, $2, ST_GeomFromText($3, 4326), '{}'::jsonb, $4)",
                str(way_id), way_run, wkt, struct.pack(f"<{len(node_ids)}q", *node_ids))
        node_run = await _insert_run(conn, "osm_node")
        for node_id, lon, lat, tags in NODES:
            await conn.execute(
                "INSERT INTO source_features (source, natural_key, run_id, geom, attrs)"
                " VALUES ('osm_node', $1, $2, ST_SetSRID(ST_MakePoint($3, $4), 4326), $5::jsonb)",
                str(node_id), node_run, lon, lat, json.dumps(tags))
        await derive_topology.derive(conn)
        await derive_node_materials.derive(conn)
        yield conn
    finally:
        await conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        await conn.close()


async def test_node_near_a_signal_is_flagged_and_far_one_is_not(node_conn):
    """信号の半径内にあるノードだけが信号付きになる。信号ノード自身も含む。"""
    assert await _signals(node_conn) == {1: False, 3: True, 5: True, 9: True}


async def test_rerun_clears_a_flag_that_no_signal_supports_any_more(node_conn):
    """単独で流し直すと、今の生データでは信号の近くにないノードの印が外れる。"""
    await node_conn.execute(
        "UPDATE node_materials SET has_traffic_signals = true WHERE osm_node_id = 1")
    await derive_node_materials.derive(node_conn)
    assert (await _signals(node_conn))[1] is False
