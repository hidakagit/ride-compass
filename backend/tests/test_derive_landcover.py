"""土地被覆の派生（`derive_raster_materials.derive`の土地被覆と道への集約）を流し直したときの値。

割合の出し方そのものは`test_landcover.py`が見る。
"""

import json
import math
import struct
from datetime import UTC, datetime

import asyncpg
import pytest
import pytest_asyncio

from app.batch import derive_counts, derive_raster_materials, derive_topology
from app.batch._common import asyncpg_dsn
from app.batch.ingest import ensure_partition
from app.batch.source_adapters._raster_wkb import tile_bbox_wkb, tile_raster_wkb
from app.domain.landcover import (
    LANDCOVER_RING_INNER_M,
    LANDCOVER_RING_OUTER_M,
    PERCENT_CLASSES,
    landcover_key,
)
from app.domain.region import WEB_MERCATOR_HALF_M, tile_bounds_3857, tile_bounds_lonlat
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


def _road() -> tuple[tuple[float, float], tuple[float, float]]:
    """タイルの中央から東へ延びる道の両端 (経度, 緯度)。"""
    bounds = tile_bounds_lonlat(ZOOM, X, Y)
    lon = (bounds.min_longitude + bounds.max_longitude) / 2
    lat = (bounds.min_latitude + bounds.max_latitude) / 2
    return (lon, lat), (lon + 0.001, lat)


ROAD = _road()

#: 帯の境目からこれより近い画素は欠測にする。距離を平面で近似した誤差と、画素が帯に入るかを
#: 中心で決めるか触れるかの違い（画素の対角の半分、約5.5m）を吸収する。
BOUNDARY_MARGIN_M = 6.0


def _ring_raster(inside: int, ring: int, outside: int) -> bytes:
    """中心線からの距離で3つに塗り分けたタイル。帯より内側（路面）・帯・帯より外側。"""
    west, _south, east, north = tile_bounds_3857(ZOOM, X, Y)
    pixel = (east - west) / SIZE
    radius = WEB_MERCATOR_HALF_M / math.pi
    (lon0, lat), (lon1, _) = ROAD
    x0, x1 = radius * math.radians(lon0), radius * math.radians(lon1)
    y0 = radius * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    meters_per_unit = math.cos(math.radians(lat))
    values = bytearray()
    for r in range(SIZE):
        py = north - (r + 0.5) * pixel
        for c in range(SIZE):
            px = west + (c + 0.5) * pixel
            d = math.hypot(max(x0 - px, 0.0, px - x1), py - y0) * meters_per_unit
            if min(abs(d - LANDCOVER_RING_INNER_M),
                   abs(d - LANDCOVER_RING_OUTER_M)) < BOUNDARY_MARGIN_M:
                values.append(NODATA)
            elif d < LANDCOVER_RING_INNER_M:
                values.append(inside)
            elif d < LANDCOVER_RING_OUTER_M:
                values.append(ring)
            else:
                values.append(outside)
    return tile_raster_wkb(bytes(values), zoom=ZOOM, x=X, y=Y,
                           width=SIZE, height=SIZE, dtype="uint8", nodata=NODATA)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def module_conn(road_graph_engine):
    """`road_graph_engine`に依存するのはスキーマを作らせるため（`test_derive_topology.py`と同じ）。"""
    conn = await asyncpg.connect(asyncpg_dsn(postgis_database_url()))
    try:
        for source in ("osm_way", "lulc"):
            await ensure_partition(conn, source)
        await conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        (lon0, lat0), (lon1, lat1) = ROAD
        await conn.execute(
            "INSERT INTO source_features (source, natural_key, run_id, geom, attrs, payload)"
            " VALUES ('osm_way', $1, $2, ST_MakeLine(ST_SetSRID(ST_MakePoint($3, $4), 4326),"
            " ST_SetSRID(ST_MakePoint($5, $6), 4326)), '{}'::jsonb, $7)",
            str(WAY_ID), await _insert_run(conn, "osm_way"), lon0, lat0, lon1, lat1,
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


@pytest_asyncio.fixture(loop_scope="module")
async def landcover_conn(module_conn):
    """テストごとにタイルを1クラス一色へ戻す。画素を書き換えるテストがあるため。"""
    await module_conn.execute(
        "UPDATE source_features SET rast = encode($1, 'hex')::raster WHERE source = 'lulc'",
        _raster(PERCENT_CLASSES[0][1]))
    return module_conn


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


async def test_only_pixels_in_the_band_around_the_road_are_counted(landcover_conn):
    """数えるのは中心線から帯の内径〜外径の画素だけ。路面そのもの（内径より内側）と、
    外径より外側の画素は、区間の割合にも道の割合にも入らない。"""
    conn = landcover_conn
    classes = PERCENT_CLASSES[:3]
    await conn.execute(
        "UPDATE source_features SET rast = encode($1, 'hex')::raster WHERE source = 'lulc'",
        _ring_raster(*(value for _, value in classes)))
    inside, ring, outside = (landcover_key(name) for name, _ in classes)

    await derive_raster_materials.derive(conn)

    rows = await conn.fetch(
        f"SELECT lc_{inside} AS inside, lc_{ring} AS ring, lc_{outside} AS outside"
        " FROM edge_materials UNION ALL"
        f" SELECT lc_{inside}, lc_{ring}, lc_{outside} FROM way_materials")
    assert [(r["inside"], r["ring"], r["outside"]) for r in rows] == [(0, 100, 0), (0, 100, 0)]
