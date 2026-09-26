"""派生の作り直し（`batch/derive_cli.py`）が、できあがるまで読み手に途中の状態を見せないこと。

段そのものの値の出し方は段ごとのテスト（`test_derive_*.py`）が持つ。ここは入口が負う契約——
作業用のスキーマで作り、1つのトランザクションで入れ替え、世代を進め、その中身から作った道路網を置く——を見る。
段は本物を通し、読み手の目で見るための覗き窓だけを段の後ろに挟む。
"""

import json
import struct
from datetime import UTC, datetime

import asyncpg
import pytest
import pytest_asyncio

from app.batch import derive_cli, derive_topology
from app.batch._common import asyncpg_dsn
from app.batch.ingest import ensure_partition
from app.infrastructure import road_network_store
from tests.conftest import postgis_database_url

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

BASE_LON, BASE_LAT = 139.70, 35.68
STEP = 0.001

#: (道, 参照ノード列, タグ)。道100は一方通行で、作り直すと通行方向が変わる。
WAYS = (
    (100, [1, 2, 3], {"highway": "residential", "oneway": "yes"}),
    (200, [3, 4], {"highway": "residential"}),
)
DERIVED = ("edge_materials", "way_materials", "road_edges", "node_materials")

_STRUCTURE_SQL = """
SELECT 'index' AS kind, tablename AS table_name, indexname AS name, indexdef AS definition
FROM pg_indexes WHERE schemaname = 'public' AND tablename = ANY($1::text[])
UNION ALL
SELECT 'constraint', r.relname, c.conname, pg_get_constraintdef(c.oid)
FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid JOIN pg_namespace n ON n.oid = r.relnamespace
WHERE n.nspname = 'public' AND r.relname = ANY($1::text[])
ORDER BY 1, 2, 3
"""


def _dsn() -> str:
    return asyncpg_dsn(postgis_database_url())


async def _revision(conn: asyncpg.Connection) -> int | None:
    return await conn.fetchval("SELECT revision FROM derived_data_meta WHERE id = 1")


@pytest_asyncio.fixture(loop_scope="module")
async def derived_before(road_graph_engine, monkeypatch, tmp_path):
    """作り直す前の状態: 区間まで作り、道の値は通行方向が既定（両方向）のまま。道路網の置き場は一時ディレクトリ。

    `road_graph_engine`に依存するのはスキーマを作らせるため。
    """
    monkeypatch.setattr(road_network_store, "ROOT", tmp_path / "road_network")
    conn = await asyncpg.connect(_dsn())
    try:
        for source in ("osm_way", "osm_node"):
            await ensure_partition(conn, source)
        await conn.execute("TRUNCATE " + ", ".join(DERIVED) + ", source_features, source_runs, derived_data_meta CASCADE")
        runs = {}
        for source in ("osm_way", "osm_node"):
            runs[source] = await conn.fetchval(
                "INSERT INTO source_runs (source, status, started_at, origin, profile, counts)"
                " VALUES ($1, 'succeeded', $2, $3, $3, $3) RETURNING run_id",
                source, datetime.now(UTC), json.dumps({}))
        for node_id in range(1, 5):
            await conn.execute(
                "INSERT INTO source_features (source, natural_key, run_id, geom, attrs)"
                " VALUES ('osm_node', $1, $2, ST_SetSRID(ST_MakePoint($3, $4), 4326), '{}'::jsonb)",
                str(node_id), runs["osm_node"], BASE_LON + STEP * node_id, BASE_LAT + STEP * (node_id % 2))
        for way_id, node_ids, tags in WAYS:
            wkt = "LINESTRING(" + ", ".join(
                f"{BASE_LON + STEP * n} {BASE_LAT + STEP * (n % 2)}" for n in node_ids) + ")"
            await conn.execute(
                "INSERT INTO source_features (source, natural_key, run_id, geom, attrs, payload)"
                " VALUES ('osm_way', $1, $2, ST_GeomFromText($3, 4326), $4::jsonb, $5)",
                str(way_id), runs["osm_way"], wkt, json.dumps(tags),
                struct.pack(f"<{len(node_ids)}q", *node_ids))
        await derive_topology.derive(conn)
        await conn.execute(
            "INSERT INTO way_materials (osm_way_id, source_run_id) SELECT DISTINCT osm_way_id, $1::bigint FROM road_edges",
            runs["osm_way"])
        await conn.execute("INSERT INTO derived_data_meta (id, revision) VALUES (1, 5)")
        yield conn
    finally:
        await conn.execute("DROP SCHEMA IF EXISTS " + derive_cli.WORK_SCHEMA + " CASCADE")
        await conn.execute("TRUNCATE " + ", ".join(DERIVED) + ", source_features, source_runs, derived_data_meta CASCADE")
        await conn.close()


def _observe_after(stage_name: str, monkeypatch, observe) -> None:
    """段`stage_name`の後ろに覗き窓を挟む（段そのものは本物を通す）。"""
    real = dict(derive_cli.STAGES)[stage_name]

    async def stage_then_observe(conn):
        await real(conn)
        await observe()

    monkeypatch.setattr(derive_cli, "STAGES", tuple(
        (name, stage_then_observe if name == stage_name else stage) for name, stage in derive_cli.STAGES))


async def test_readers_see_the_previous_tables_until_the_swap_and_the_rebuilt_ones_after(
        derived_before, monkeypatch):
    """段が書き終えても、入れ替えまでは読み手は前の表を読む。入れ替えの後は、前から開いている接続の
    準備済みの文も作り直した表を読み、世代が1つ進み、その世代の道路網は作り直した表から作られている。"""
    structure_before = await derived_before.fetch(_STRUCTURE_SQL, list(DERIVED))
    reader = await asyncpg.connect(_dsn())
    try:
        direction = await reader.prepare("SELECT direction FROM way_materials WHERE osm_way_id = $1")
        seen_while_rebuilding: list[tuple[str, int | None]] = []

        async def observe():
            seen_while_rebuilding.append((await direction.fetchval(100), await _revision(reader)))

        _observe_after("ways", monkeypatch, observe)

        assert await derive_cli.run(postgis_database_url(), "ways") == 0

        assert seen_while_rebuilding == [("both", 5)]
        assert await direction.fetchval(100) == "forward"
        assert await _revision(reader) == 6
    finally:
        await reader.close()

    network = road_network_store.load(road_network_store.latest_directory())
    assert network.revision == 6
    directions = set(zip(network.edge_way_id.tolist(), network.edge_forward.tolist(), strict=True))
    assert (100, False) not in directions
    assert (200, False) in directions
    # 入れ替えた表は、前の表と同じ名前の索引・制約を持つ。
    assert await derived_before.fetch(_STRUCTURE_SQL, list(DERIVED)) == structure_before
    assert await derived_before.fetchval(
        "SELECT count(*) FROM pg_namespace WHERE nspname = $1", derive_cli.WORK_SCHEMA) == 0


async def test_a_failed_rebuild_changes_nothing_readers_see(derived_before, monkeypatch):
    """途中で落ちたら、表も世代も道路網の置き場も前のまま。作業用のスキーマは残らない。"""

    async def fail():
        raise RuntimeError("段の後で落ちた")

    _observe_after("ways", monkeypatch, fail)

    with pytest.raises(RuntimeError, match="段の後で落ちた"):
        await derive_cli.run(postgis_database_url(), "ways")

    assert await derived_before.fetchval(
        "SELECT direction FROM way_materials WHERE osm_way_id = 100") == "both"
    assert await _revision(derived_before) == 5
    assert road_network_store.latest_directory() is None
    assert await derived_before.fetchval(
        "SELECT count(*) FROM pg_namespace WHERE nspname = $1", derive_cli.WORK_SCHEMA) == 0
