"""土地被覆の派生（`derive_raster_materials.derive`の土地被覆と道への集約）を流し直したときの値。

割合の出し方そのものは`test_landcover.py`が見る。
"""

import json
import struct
from datetime import UTC, datetime

import asyncpg
import pytest
import pytest_asyncio

from app.batch import derive_counts, derive_raster_materials, derive_topology
from app.batch._common import asyncpg_dsn
from app.batch.ingest import ensure_partition
from app.batch.source_adapters._raster_wkb import tile_bbox_wkb, tile_raster_wkb
from app.domain.landcover import PERCENT_CLASSES, landcover_key
from app.domain.region import tile_bounds_lonlat
from tests.conftest import postgis_database_url

# road_graph_session（conftest.py）と同じDBを使うため、docs/conventions/testing.mdのパターン2どおり
# loop_scope="module"・xdist_group="postgis"が必須。
pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

#: 1辺が約2.4kmのタイル。中央に置いた道の帯（中心線から100m）はこの1枚に収まる。
ZOOM, X, Y = 14, 14550, 6451
SIZE = 256
WAY_ID = 100
#: 欠測値。`ST_Clip`がこの画素を外す。
NODATA = 0

TABLES = ("edge_materials", "way_materials", "road_edges", "node_materials",
          "source_features", "source_runs")


async def _insert_run(conn: asyncpg.Connection, source: str) -> int:
    return await conn.fetchval(
        "INSERT INTO source_runs (source, status, started_at, origin, profile, counts)"
        " VALUES ($1, 'succeeded', $2, $3, $3, $3) RETURNING run_id",
        source, datetime.now(UTC), json.dumps({}))


def _raster(value: int) -> bytes:
    return tile_raster_wkb(bytes([value]) * (SIZE * SIZE), zoom=ZOOM, x=X, y=Y,
                           width=SIZE, height=SIZE, dtype="uint8", nodata=NODATA)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def landcover_conn(road_graph_engine):
    """`road_graph_engine`に依存するのはスキーマを作らせるため（`test_derive_topology.py`と同じ）。"""
    conn = await asyncpg.connect(asyncpg_dsn(postgis_database_url()))
    try:
        for source in ("osm_way", "lulc"):
            await ensure_partition(conn, source)
        await conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        bounds = tile_bounds_lonlat(ZOOM, X, Y)
        lon = (bounds.min_longitude + bounds.max_longitude) / 2
        lat = (bounds.min_latitude + bounds.max_latitude) / 2
        await conn.execute(
            "INSERT INTO source_features (source, natural_key, run_id, geom, attrs, payload)"
            " VALUES ('osm_way', $1, $2, ST_MakeLine(ST_SetSRID(ST_MakePoint($3, $4), 4326),"
            " ST_SetSRID(ST_MakePoint($5, $4), 4326)), '{}'::jsonb, $6)",
            str(WAY_ID), await _insert_run(conn, "osm_way"), lon, lat, lon + 0.001,
            struct.pack("<2q", 1, 2))
        await conn.execute(
            "INSERT INTO source_features (source, natural_key, run_id, geom, attrs, rast)"
            " VALUES ('lulc', 'tile', $1, ST_SetSRID(ST_GeomFromWKB($2), 4326), $3::jsonb,"
            " encode($4, 'hex')::raster)",
            await _insert_run(conn, "lulc"), tile_bbox_wkb(ZOOM, X, Y),
            json.dumps({"z": ZOOM, "x": X, "y": Y, "width": SIZE}), _raster(PERCENT_CLASSES[0][1]))
        await derive_topology.derive(conn)
        await derive_counts.derive(conn)
        yield conn
    finally:
        await conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        await conn.close()


async def test_rerun_on_pixels_left_out_keeps_no_share_on_segments_or_ways(landcover_conn):
    """画素が欠測になって流し直すと、区間も道も割合を持たない（有効画素が足りない）。"""
    conn = landcover_conn
    first = landcover_key(PERCENT_CLASSES[0][0])

    async def shares() -> list[tuple[int | None, float | None]]:
        """区間と道それぞれの (有効画素数, 塗ったクラスの割合)。"""
        return [(r["lc_valid_pixels"], r[f"lc_{first}"]) for r in await conn.fetch(
            f"SELECT lc_valid_pixels, lc_{first} FROM edge_materials"
            f" UNION ALL SELECT lc_valid_pixels, lc_{first} FROM way_materials")]

    await derive_raster_materials.derive(conn)
    before = await shares()
    await conn.execute(
        "UPDATE source_features SET rast = encode($1, 'hex')::raster WHERE source = 'lulc'",
        _raster(NODATA))
    await derive_raster_materials.derive(conn)

    # 前提: 1回目は区間にも道にも値が付いている。
    assert len(before) == 2
    assert all(pixels and share == pytest.approx(100) for pixels, share in before)
    assert await shares() == [(None, None), (None, None)]
