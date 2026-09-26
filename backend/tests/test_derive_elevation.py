"""標高の取込（`gsi_dem_tile`）と派生（`derive_raster_materials.derive_elevation`）。

手元へ写したタイル（置き場は一時ディレクトリ）から取り込み、区間の標高が画素ごとに
配信元の定める順で採られることを見る。配信元の文書:

> 航空レーザ測量（DEM5A）のデータが存在しない箇所では、航空レーザ測量（DEM5A）→
> 写真測量（DEM5B, DEM5C）→1/2.5万地形図等高線（DEM10B）の順で存在する最も計測精度の良い
> 標高タイルの値が参照され（https://maps.gsi.go.jp/development/hyokochi.html ）

z15のタイルTを4つの区画に分け、製品ごとに値のある区画を変えて置く:

| 区画（Tの画素） | dem5a | dem5b | dem（z14） | 採られる値 |
|---|---|---|---|---|
| 上・左 | 10 | 20 | 99 | 10（全部にある） |
| 上・右 | e | 20 | 99 | 20（上位が欠けた画素だけ下位で埋まる） |
| 下・左 | 10 | e | e | 10 |
| 下・右の左寄り | e | e | 30 | 30（ズームの違う製品の画素を引ける） |
| 下・右の右寄り | e | e | e | 無し（どの製品にも無い） |
"""

import json
import struct
from dataclasses import replace
from datetime import UTC, datetime

import asyncpg
import pytest
import pytest_asyncio

from app.batch import dem_tile_store, derive_raster_materials, derive_topology
from app.batch._common import asyncpg_dsn
from app.batch.ingest import ensure_partition, ingest_source
from app.batch.source_profile import Target, load_source_profile
from app.domain.region import tile_bounds_lonlat
from tests.conftest import postgis_database_url

# road_graph_session（conftest.py）と同じDBを使うため、docs/conventions/testing.mdのパターン2どおり
# loop_scope="module"・xdist_group="postgis"が必須。
pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

#: タイルT。x・yとも偶数なので、z14の親タイルの左上の4分の1に当たる。
ZOOM, X, Y = 15, 29100, 12902
PARENT = (14, X // 2, Y // 2)
SIZE = 256

TABLES = ("edge_materials", "way_materials", "road_edges", "node_materials",
          "source_features", "source_runs")

#: 区画ごとの (wayのid, 頂点を置くTの画素(行, 列)の組, 採られるはずの標高)。
CASES = (
    (1, ((40, 40), (40, 44)), 10.0),
    (2, ((40, 200), (40, 204)), 20.0),
    (3, ((200, 40), (200, 44)), 10.0),
    (4, ((200, 150), (200, 154)), 30.0),
    (5, ((200, 230), (200, 234)), None),
)


def _tile_text(value) -> str:
    """`value(行, 列)`が返す値（Noneは欠測）で埋めた、配信元と同じ形の本文。"""
    return "\n".join(
        ",".join("e" if (v := value(r, c)) is None else f"{v:.2f}" for c in range(SIZE))
        for r in range(SIZE)) + "\n"


def _dem5a(r, c):
    return 10.0 if c < 128 else None


def _dem5b(r, c):
    return 20.0 if r < 128 else None


def _dem10b(pr, pc):
    """親タイルの画素 (pr, pc) は、Tの画素 (2pr, 2pc) からの2×2を覆う。"""
    if pr < 64 and pc < 128:
        return 99.0
    if 64 <= pr < 128 and 64 <= pc < 96:
        return 30.0
    return None


def _pixel_center(r: int, c: int) -> tuple[float, float]:
    """Tの画素 (r, c) の中心の (経度, 緯度)。z23のタイル1枚がちょうどz15の1画素に当たる。"""
    b = tile_bounds_lonlat(ZOOM + 8, X * SIZE + c, Y * SIZE + r)
    return ((b.min_longitude + b.max_longitude) / 2, (b.min_latitude + b.max_latitude) / 2)


def _profile():
    bounds = tile_bounds_lonlat(ZOOM, X, Y)
    inset = 1e-6
    bbox = (bounds.min_latitude + inset, bounds.min_longitude + inset,
            bounds.max_latitude - inset, bounds.max_longitude - inset)
    return replace(load_source_profile(), target=Target(bbox=bbox))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def elevation_conn(road_graph_engine, tmp_path_factory):
    """`road_graph_engine`に依存するのはスキーマを作らせるため（`test_derive_topology.py`と同じ）。"""
    root = tmp_path_factory.mktemp("dem")
    dem_tile_store.write_tile(root, "dem5a", ZOOM, X, Y, _tile_text(_dem5a))
    dem_tile_store.write_tile(root, "dem5b", ZOOM, X, Y, _tile_text(_dem5b))
    dem_tile_store.write_tile(root, "dem", *PARENT, _tile_text(_dem10b))
    dem_tile_store.mark_absent(root, "dem5c", ZOOM, X, Y)

    conn = await asyncpg.connect(asyncpg_dsn(postgis_database_url()))
    try:
        await ensure_partition(conn, "osm_way")
        await conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(dem_tile_store, "TILE_ROOT", root)
            async with conn.transaction():
                await ingest_source(conn, _profile(), "dem")

        run = await conn.fetchval(
            "INSERT INTO source_runs (source, status, started_at, origin, profile, counts)"
            " VALUES ('osm_way', 'succeeded', $1, $2, $2, $2) RETURNING run_id",
            datetime.now(UTC), json.dumps({}))
        for way_id, pixels, _expected in CASES:
            node_ids = [way_id * 10 + i for i in range(len(pixels))]
            wkt = "LINESTRING(" + ", ".join(
                "{} {}".format(*_pixel_center(r, c)) for r, c in pixels) + ")"
            await conn.execute(
                "INSERT INTO source_features (source, natural_key, run_id, geom, attrs, payload)"
                " VALUES ('osm_way', $1, $2, ST_GeomFromText($3, 4326), '{}'::jsonb, $4)",
                str(way_id), run, wkt, struct.pack(f"<{len(node_ids)}q", *node_ids))
        async with conn.transaction():
            await derive_topology.derive(conn)
            await derive_raster_materials.derive_elevation(conn)
        yield conn
    finally:
        await conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        await conn.close()


async def test_each_product_the_origin_returned_becomes_its_own_row(elevation_conn):
    """同じ地点に値を持つ製品は、1つに絞らずにそれぞれ1行になる。区域外の製品は行を持たない。"""
    keys = await elevation_conn.fetch(
        "SELECT natural_key FROM source_features WHERE source = 'dem' ORDER BY natural_key")
    assert [r["natural_key"] for r in keys] == sorted([
        f"dem5a/{ZOOM}/{X}/{Y}", f"dem5b/{ZOOM}/{X}/{Y}", "dem/{}/{}/{}".format(*PARENT)])


async def test_each_pixel_takes_the_most_accurate_product_that_has_a_value(elevation_conn):
    rows = await elevation_conn.fetch(
        "SELECT osm_way_id, start_elevation_m, end_elevation_m FROM edge_materials"
        " ORDER BY osm_way_id")
    got = {r["osm_way_id"]: (r["start_elevation_m"], r["end_elevation_m"]) for r in rows}
    assert got == {way_id: (expected, expected) for way_id, _pixels, expected in CASES}


async def test_rerun_without_a_product_keeps_no_value_only_that_product_gave(elevation_conn):
    """製品を抜いて流し直すと、その製品だけが値を持っていた区間は値を失い、ほかは変わらない。
    製品が1つも無くなれば、どの区間も値を持たない。"""
    conn = elevation_conn

    async def elevations() -> dict[int, float | None]:
        rows = await conn.fetch("SELECT osm_way_id, start_elevation_m, max_grade FROM edge_materials")
        assert all((r["start_elevation_m"] is None) == (r["max_grade"] is None) for r in rows)
        return {r["osm_way_id"]: r["start_elevation_m"] for r in rows}

    async def rerun() -> dict[int, float | None]:
        async with conn.transaction():
            await derive_raster_materials.derive_elevation(conn)
        return await elevations()

    await conn.execute(
        "CREATE TEMP TABLE _dem AS SELECT * FROM source_features WHERE source = 'dem'")
    try:
        await conn.execute(
            "DELETE FROM source_features WHERE source = 'dem' AND attrs->>'product' = 'dem'")
        without_dem = await rerun()
        await conn.execute("DELETE FROM source_features WHERE source = 'dem'")
        without_any = await rerun()
    finally:
        await conn.execute("DELETE FROM source_features WHERE source = 'dem'")
        await conn.execute("INSERT INTO source_features SELECT * FROM _dem")
        await conn.execute("DROP TABLE _dem")
        await rerun()

    assert without_dem == {way_id: None if way_id == 4 else expected
                           for way_id, _pixels, expected in CASES}
    assert without_any == dict.fromkeys(without_dem)
