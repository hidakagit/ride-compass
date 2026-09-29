"""上下線が分かれた道の片側か（`batch/derive_way_materials.py`の`way_materials.divided`）。

判定の3条件（`carriageway`の申告・同じ名前の対向一方通行・寄り添う対向一方通行）それぞれに、
当たる入力と、条件の外にある入力を1組ずつ置く。生データから派生の段を本物のまま通す。
"""

import json
import struct
from datetime import UTC, datetime
from typing import NamedTuple

import asyncpg
import pytest
import pytest_asyncio

from app.batch import derive_counts, derive_topology, derive_way_materials
from app.batch._common import asyncpg_dsn
from app.batch.ingest import ensure_partition
from app.domain.divided_carriageway import GEOMETRIC_GAP_M, NAMED_GAP_M
from app.domain.geo import KM_PER_DEGREE_LATITUDE
from tests.conftest import postgis_database_url

# road_graph_session（conftest.py）と同じDBを使うため、docs/conventions/testing.mdのパターン2どおり
# loop_scope="module"・xdist_group="postgis"が必須。
pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

BASE_LON, BASE_LAT = 139.70, 35.68
#: 道の長さ（経度、約180m）。
LENGTH = 0.002
#: 場面どうしの間隔（緯度、約1.1km）。どの距離のしきい値よりも十分に遠い。
SPACING = 0.01

ONEWAY = {"highway": "primary", "oneway": "yes"}


class Scene(NamedTuple):
    """1つの場面。`partner`はNoneなら道1本だけ、あれば北へ`gap_m`離して並べる2本目のタグ。"""

    tags: dict[str, str]
    partner: dict[str, str] | None
    gap_m: float
    opposite: bool
    divided: bool


SCENES: dict[str, Scene] = {
    "carriageway を申告した一方通行": Scene(
        {**ONEWAY, "carriageway": "dual"}, None, 0.0, False, True),
    "carriageway を申告した両方向の道": Scene(
        {"highway": "primary", "carriageway": "dual"}, None, 0.0, False, False),
    "同じ名前の対向一方通行が名前の距離の内側": Scene(
        {**ONEWAY, "name": "A"}, {**ONEWAY, "name": "A"}, NAMED_GAP_M - 10, True, True),
    "同じ名前の対向一方通行が名前の距離の外側": Scene(
        {**ONEWAY, "name": "A"}, {**ONEWAY, "name": "A"}, NAMED_GAP_M + 10, True, False),
    "無名の対向一方通行が寄り添う": Scene(
        ONEWAY, ONEWAY, GEOMETRIC_GAP_M - 5, True, True),
    "無名の対向一方通行が寄り添う距離の外側": Scene(
        ONEWAY, ONEWAY, GEOMETRIC_GAP_M + 10, True, False),
    "同じ向きの一方通行が寄り添う": Scene(
        ONEWAY, ONEWAY, GEOMETRIC_GAP_M - 5, False, False),
    "種別の違う対向一方通行が寄り添う": Scene(
        ONEWAY, {**ONEWAY, "highway": "secondary"}, GEOMETRIC_GAP_M - 5, True, False),
    "名前の違う対向一方通行が寄り添う": Scene(
        {**ONEWAY, "name": "A"}, {**ONEWAY, "name": "B"}, GEOMETRIC_GAP_M - 5, True, False),
}

TABLES = ("edge_materials", "way_materials", "road_edges", "node_materials",
          "source_features", "source_runs")


def _ways() -> dict[str, list[tuple[int, dict[str, str], list[tuple[float, float]]]]]:
    """場面ごとの (wayのid, タグ, 頂点の(経度, 緯度)列)。"""
    ways = {}
    for i, (name, scene) in enumerate(SCENES.items()):
        lat = BASE_LAT + SPACING * i
        east = [(BASE_LON, lat), (BASE_LON + LENGTH, lat)]
        ways[name] = [(i * 10 + 1, scene.tags, east)]
        if scene.partner is not None:
            partner_lat = lat + scene.gap_m / (KM_PER_DEGREE_LATITUDE * 1000.0)
            line = [(lon, partner_lat) for lon, _ in east]
            ways[name].append(
                (i * 10 + 2, scene.partner, line[::-1] if scene.opposite else line))
    return ways


WAYS = _ways()


async def _insert_run(conn: asyncpg.Connection, source: str) -> int:
    return await conn.fetchval(
        "INSERT INTO source_runs (source, status, started_at, origin, profile, counts)"
        " VALUES ($1, 'succeeded', $2, $3, $3, $3) RETURNING run_id",
        source, datetime.now(UTC), json.dumps({}))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def divided_conn(road_graph_engine):
    """`road_graph_engine`に依存するのはスキーマを作らせるため（`test_derive_topology.py`と同じ）。"""
    conn = await asyncpg.connect(asyncpg_dsn(postgis_database_url()))
    try:
        await ensure_partition(conn, "osm_way")
        await conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        run = await _insert_run(conn, "osm_way")
        for ways in WAYS.values():
            for way_id, tags, points in ways:
                node_ids = [way_id * 10 + k for k in range(len(points))]
                wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in points) + ")"
                await conn.execute(
                    "INSERT INTO source_features (source, natural_key, run_id, geom, attrs, payload)"
                    " VALUES ('osm_way', $1, $2, ST_GeomFromText($3, 4326), $4::jsonb, $5)",
                    str(way_id), run, wkt, json.dumps(tags),
                    struct.pack(f"<{len(node_ids)}q", *node_ids))
        await derive_topology.derive(conn)
        await derive_counts.derive(conn)
        await derive_way_materials.derive(conn)
        yield conn
    finally:
        await conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        await conn.close()


@pytest.mark.parametrize("scene", SCENES)
async def test_a_way_is_one_side_of_a_divided_road_only_under_its_conditions(divided_conn, scene):
    way_ids = [way_id for way_id, _tags, _points in WAYS[scene]]
    rows = await divided_conn.fetch(
        "SELECT osm_way_id, divided FROM way_materials WHERE osm_way_id = ANY($1)", way_ids)
    assert {r["osm_way_id"]: r["divided"] for r in rows} == dict.fromkeys(
        way_ids, SCENES[scene].divided)
