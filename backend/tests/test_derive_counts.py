"""区間と道に付く数の値（`batch/derive_counts.py`）が、意図した区間へ数を付けること。"""

import json
import struct
from datetime import UTC, datetime

import asyncpg
import pytest
import pytest_asyncio

from app.batch import derive_counts, derive_topology
from app.batch._common import asyncpg_dsn
from app.batch.ingest import ensure_partition
from app.domain.traffic import POI_COUNT_KINDS, poi_count_column
from tests.conftest import postgis_database_url

# road_graph_session（conftest.py）と同じDBを使うため、docs/conventions/testing.mdのパターン2どおり
# loop_scope="module"・xdist_group="postgis"が必須。
pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

BASE_LON, BASE_LAT = 139.70, 35.68
STEP = 0.001

#: (wayのid, 参照ノードid列)。3本ともノード3で接する。ノード3の上で起きた事故は
#: 3区間のどれからも距離0になる。
WAYS: tuple[tuple[int, list[int]], ...] = (
    (300, [1, 3]),
    (200, [3, 4]),
    (100, [5, 3]),
)
TIED_NODE = 3

TABLES = ("edge_materials", "way_materials", "road_edges", "node_materials",
          "source_features", "source_runs")


def _point(node_id: int) -> tuple[float, float]:
    return (BASE_LON + STEP * node_id, BASE_LAT + STEP * (node_id % 2))


async def _insert_run(conn: asyncpg.Connection, source: str) -> int:
    return await conn.fetchval(
        "INSERT INTO source_runs (source, status, started_at, origin, profile, counts)"
        " VALUES ($1, 'succeeded', $2, $3, $3, $3) RETURNING run_id",
        source, datetime.now(UTC), json.dumps({}))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def counts_conn(road_graph_engine):
    """`road_graph_engine`に依存するのはスキーマを作らせるため（`test_derive_topology.py`と同じ）。"""
    conn = await asyncpg.connect(asyncpg_dsn(postgis_database_url()))
    try:
        for source in ("osm_way", "accident"):
            await ensure_partition(conn, source)
        await conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        way_run = await _insert_run(conn, "osm_way")
        for way_id, node_ids in WAYS:
            wkt = "LINESTRING(" + ", ".join(
                f"{lon} {lat}" for lon, lat in map(_point, node_ids)) + ")"
            await conn.execute(
                "INSERT INTO source_features (source, natural_key, run_id, geom, attrs, payload)"
                " VALUES ('osm_way', $1, $2, ST_GeomFromText($3, 4326), '{}'::jsonb, $4)",
                str(way_id), way_run, wkt, struct.pack(f"<{len(node_ids)}q", *node_ids))
        accident_run = await _insert_run(conn, "accident")
        lon, lat = _point(TIED_NODE)
        await conn.execute(
            "INSERT INTO source_features (source, natural_key, run_id, geom, attrs)"
            " VALUES ('accident', 'tied', $1, ST_SetSRID(ST_MakePoint($2, $3), 4326), '{}'::jsonb)",
            accident_run, lon, lat)
        await derive_topology.derive(conn)
        await derive_counts.derive(conn)
        yield conn
    finally:
        await conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        await conn.close()


async def test_equidistant_accident_goes_to_exactly_one_existing_segment(counts_conn):
    """等距離のタイでも事故は1件のまま、実在する1区間へ付く。区間の鍵が小さい方が取る。

    鍵の2列を別々の探索で取ると、タイのときに片方ずつ別の区間を指し、どの区間にも
    付かない（存在しない組へ集計される）ことがある。
    """
    rows = await counts_conn.fetch(
        "SELECT osm_way_id, segment_index, accident_count FROM edge_materials"
        " WHERE accident_count > 0")
    assert [(r["osm_way_id"], r["segment_index"], r["accident_count"]) for r in rows] == [
        (100, 0, 1.0)]
    distances = await counts_conn.fetch(
        "SELECT DISTINCT e.geom <-> a.geom AS d FROM road_edges e, source_features a"
        " WHERE a.source = 'accident'")
    # 前提: 3区間とも本当に等距離（タイを作れている）。
    assert [r["d"] for r in distances] == [0.0]


async def test_way_values_of_a_way_gone_from_the_raw_data_do_not_survive(counts_conn):
    """生データから道が消えたら、作り直した後にその道の値は残らない。残る道の値は
    後ろの段が埋めたものを保ったまま、世代だけ新しくなる。"""
    await counts_conn.execute(
        "UPDATE way_materials SET direction = 'forward' WHERE osm_way_id = 100")
    await counts_conn.execute(
        "CREATE TEMP TABLE _removed AS SELECT * FROM source_features"
        " WHERE source = 'osm_way' AND natural_key = '200'")
    await counts_conn.execute(
        "DELETE FROM source_features WHERE source = 'osm_way' AND natural_key = '200'")
    new_run = await _insert_run(counts_conn, "osm_way")
    await counts_conn.execute(
        "UPDATE source_features SET run_id = $1 WHERE source = 'osm_way'", new_run)
    try:
        await derive_topology.derive(counts_conn)
        await derive_counts.derive(counts_conn)
        rows = await counts_conn.fetch(
            "SELECT osm_way_id, direction, source_run_id FROM way_materials ORDER BY osm_way_id")
        assert [(r["osm_way_id"], r["direction"], r["source_run_id"]) for r in rows] == [
            (100, "forward", new_run), (300, "both", new_run)]
    finally:
        await counts_conn.execute("INSERT INTO source_features SELECT * FROM _removed")
        await counts_conn.execute("DROP TABLE _removed")


async def test_a_crossing_near_a_signal_is_counted_as_a_signal(counts_conn):
    """近くに信号がある横断歩道は、横断歩道ではなく信号として数える。

    地図も同じ読み替えで信号の点を出す（`test_poi_tile.py`）。
    """
    await ensure_partition(counts_conn, "osm_node")
    run = await _insert_run(counts_conn, "osm_node")
    lon, lat = _point(TIED_NODE)
    await counts_conn.execute(
        "INSERT INTO source_features (source, natural_key, run_id, geom, attrs)"
        " VALUES ('osm_node', $1, $2, ST_SetSRID(ST_MakePoint($3, $4), 4326), '{}'::jsonb)",
        str(TIED_NODE), run, lon, lat)
    await counts_conn.execute(
        "UPDATE node_materials SET kind = 'crossing', has_traffic_signals = true"
        " WHERE osm_node_id = $1", TIED_NODE)

    await derive_counts.derive(counts_conn)

    rows = await counts_conn.fetch(
        "SELECT DISTINCT m.poi_signal, m.poi_crossing FROM edge_materials m JOIN road_edges e"
        "  ON e.osm_way_id = m.osm_way_id AND e.segment_index = m.segment_index"
        " WHERE $1 IN (e.from_node_id, e.to_node_id)", TIED_NODE)
    assert [(r["poi_signal"] > 0, r["poi_crossing"]) for r in rows] == [(True, 0)]


async def test_rerun_on_changed_input_keeps_no_count_the_input_no_longer_supports(counts_conn):
    """入力を変えて流し直すと、停止要因も事故も無くなった区間・道の数は0へ戻る。"""
    await ensure_partition(counts_conn, "osm_node")
    run = await _insert_run(counts_conn, "osm_node")
    lon, lat = _point(TIED_NODE)
    await counts_conn.execute(
        "INSERT INTO source_features (source, natural_key, run_id, geom, attrs)"
        " VALUES ('osm_node', $1, $2, ST_SetSRID(ST_MakePoint($3, $4), 4326), '{}'::jsonb)"
        " ON CONFLICT DO NOTHING", str(TIED_NODE), run, lon, lat)
    columns = ("accident_count", *(poi_count_column(k) for k in sorted(POI_COUNT_KINDS)))
    total = " + ".join(f"sum({c})" for c in columns)

    async def counted() -> tuple[float, float]:
        """(区間の数の総和, 道の数の総和)。"""
        return (await counts_conn.fetchval(f"SELECT {total} FROM edge_materials"),
                await counts_conn.fetchval(f"SELECT {total} FROM way_materials"))

    await counts_conn.execute(
        "UPDATE node_materials SET kind = 'crossing', has_traffic_signals = false"
        " WHERE osm_node_id = $1", TIED_NODE)
    await counts_conn.execute(
        "CREATE TEMP TABLE _accidents AS SELECT * FROM source_features WHERE source = 'accident'")
    try:
        await derive_counts.derive(counts_conn)
        before = await counted()
        await counts_conn.execute(
            "UPDATE node_materials SET kind = NULL WHERE osm_node_id = $1", TIED_NODE)
        await counts_conn.execute("DELETE FROM source_features WHERE source = 'accident'")
        await derive_counts.derive(counts_conn)
        after = await counted()
    finally:
        await counts_conn.execute("INSERT INTO source_features SELECT * FROM _accidents")
        await counts_conn.execute("DROP TABLE _accidents")

    # 前提: 1回目は数が付いている。
    assert all(n > 0 for n in before)
    assert after == (0, 0)
