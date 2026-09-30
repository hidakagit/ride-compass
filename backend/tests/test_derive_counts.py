"""区間と道に付く数の値（`batch/derive_counts.py`）が、意図した区間へ数を付けること。"""

import json
import struct
from datetime import UTC, datetime

import asyncpg
import pytest
import pytest_asyncio

from app.batch import derive_counts, derive_node_materials, derive_topology
from app.batch._common import asyncpg_dsn
from app.batch.ingest import ensure_partition
from app.domain.accident import (
    ACCIDENT_FATAL_WEIGHT,
    ACCIDENT_MATCH_MAX_DISTANCE_M,
    BICYCLE_PARTY_TYPE_CODES,
)
from app.domain.geo import KM_PER_DEGREE_LATITUDE, km_per_degree_longitude
from app.domain.traffic import POI_COUNT_KINDS, poi_count_column
from app.domain.tuning import TUNING_PARAMETERS_BY_ID
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
#: 道300（ノード1から3へ東西に延びる）の中ほど。ほかの道はここから約90m以上離れる。
BESIDE_WAY = (BASE_LON + STEP * 2, BASE_LAT + STEP)

#: 自転車の当事者種別と、自転車ではない軽車両（その他）の当事者種別。
BICYCLE_PARTY = min(BICYCLE_PARTY_TYPE_CODES)
OTHER_PARTY = "59"

TABLES = ("edge_materials", "way_materials", "road_edges", "node_materials",
          "source_features", "source_runs")


def _point(node_id: int) -> tuple[float, float]:
    return (BASE_LON + STEP * node_id, BASE_LAT + STEP * (node_id % 2))


async def _insert_run(conn: asyncpg.Connection, source: str) -> int:
    return await conn.fetchval(
        "INSERT INTO source_runs (source, status, started_at, origin, profile, counts)"
        " VALUES ($1, 'succeeded', $2, $3, $3, $3) RETURNING run_id",
        source, datetime.now(UTC), json.dumps({}))


def _north_of_way(meters: float) -> tuple[float, float]:
    """道300の中ほどから北へ`meters`離れた点。"""
    lon, lat = BESIDE_WAY
    return (lon, lat + meters / (KM_PER_DEGREE_LATITUDE * 1000.0))


async def _insert_accident(conn: asyncpg.Connection, key: str, position: tuple[float, float], *,
                           bicycle: bool = True, fatal: bool = False) -> None:
    """本票の列名で当事者種別と死者数を持つ事故を1件置く。"""
    run = await conn.fetchval("SELECT max(run_id) FROM source_runs WHERE source = 'accident'")
    attrs = {"当事者種別（当事者A）": BICYCLE_PARTY if bicycle else OTHER_PARTY,
             "当事者種別（当事者B）": OTHER_PARTY,
             "死者数": "001" if fatal else "000"}
    await conn.execute(
        "INSERT INTO source_features (source, natural_key, run_id, geom, attrs)"
        " VALUES ('accident', $1, $2, ST_SetSRID(ST_MakePoint($3, $4), 4326), $5::jsonb)",
        key, run, *position, json.dumps(attrs, ensure_ascii=False))


async def _accidents(conn: asyncpg.Connection) -> dict[tuple[int, int], float]:
    """事故の付いた区間ごとの数。"""
    rows = await conn.fetch(
        "SELECT osm_way_id, segment_index, accident_count FROM edge_materials"
        " WHERE accident_count > 0")
    return {(r["osm_way_id"], r["segment_index"]): r["accident_count"] for r in rows}


async def _derive_with_nodes(conn: asyncpg.Connection,
                             nodes: dict[int, tuple[tuple[float, float], dict[str, str]]]) -> None:
    """{ノードid: (位置, タグ)} のノードを置き、ノードの段から流し直す。"""
    run = await _insert_run(conn, "osm_node")
    for node_id, ((lon, lat), tags) in nodes.items():
        await conn.execute(
            "INSERT INTO source_features (source, natural_key, run_id, geom, attrs)"
            " VALUES ('osm_node', $1, $2, ST_SetSRID(ST_MakePoint($3, $4), 4326), $5::jsonb)",
            str(node_id), run, lon, lat, json.dumps(tags))
    await derive_node_materials.derive(conn, TUNING_PARAMETERS_BY_ID["signal.match_radius_m"].default)
    await derive_counts.derive(conn)


async def _stop_counts(conn: asyncpg.Connection) -> dict[int, dict[str, float]]:
    """道ごとの、停止要因の集計キーごとの数（0は省く）。"""
    columns = {kind: poi_count_column(kind) for kind in sorted(POI_COUNT_KINDS)}
    rows = await conn.fetch(
        "SELECT osm_way_id, " + ", ".join(columns.values()) + " FROM way_materials")
    return {r["osm_way_id"]: {kind: r[c] for kind, c in columns.items() if r[c]} for r in rows}


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def module_conn(road_graph_engine):
    """`road_graph_engine`に依存するのはスキーマを作らせるため（`test_derive_topology.py`と同じ）。"""
    conn = await asyncpg.connect(asyncpg_dsn(postgis_database_url()))
    try:
        for source in ("osm_way", "accident", "osm_node"):
            await ensure_partition(conn, source)
        yield conn
    finally:
        await conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        await conn.close()


@pytest_asyncio.fixture(loop_scope="module")
async def counts_conn(module_conn):
    """テストごとに同じ生データから作り直す。どのテストも生データと派生の表を書き換えるため。"""
    conn = module_conn
    await conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
    way_run = await _insert_run(conn, "osm_way")
    for way_id, node_ids in WAYS:
        wkt = "LINESTRING(" + ", ".join(
            f"{lon} {lat}" for lon, lat in map(_point, node_ids)) + ")"
        await conn.execute(
            "INSERT INTO source_features (source, natural_key, run_id, geom, attrs, payload)"
            " VALUES ('osm_way', $1, $2, ST_GeomFromText($3, 4326), '{}'::jsonb, $4)",
            str(way_id), way_run, wkt, struct.pack(f"<{len(node_ids)}q", *node_ids))
    await _insert_run(conn, "accident")
    await _insert_accident(conn, "tied", _point(TIED_NODE))
    await derive_topology.derive(conn)
    await derive_counts.derive(conn)
    return conn


async def test_equidistant_accident_goes_to_exactly_one_existing_segment(counts_conn):
    """等距離のタイでも事故は1件のまま、実在する1区間へ付く。区間の鍵が小さい方が取る。

    鍵の2列を別々の探索で取ると、タイのときに片方ずつ別の区間を指し、どの区間にも
    付かない（存在しない組へ集計される）ことがある。
    """
    assert await _accidents(counts_conn) == {(100, 0): 1.0}
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
        "DELETE FROM source_features WHERE source = 'osm_way' AND natural_key = '200'")
    new_run = await _insert_run(counts_conn, "osm_way")
    await counts_conn.execute(
        "UPDATE source_features SET run_id = $1 WHERE source = 'osm_way'", new_run)

    await derive_topology.derive(counts_conn)
    await derive_counts.derive(counts_conn)

    rows = await counts_conn.fetch(
        "SELECT osm_way_id, direction, source_run_id FROM way_materials ORDER BY osm_way_id")
    assert [(r["osm_way_id"], r["direction"], r["source_run_id"]) for r in rows] == [
        (100, "forward", new_run), (300, "both", new_run)]


async def test_a_crossing_near_a_signal_is_counted_as_a_signal(counts_conn):
    """近くに信号がある横断歩道は、横断歩道ではなく信号として数える。

    地図も同じ読み替えで信号の点を出す（`test_poi_tile.py`）。
    """
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
    run = await _insert_run(counts_conn, "osm_node")
    lon, lat = _point(TIED_NODE)
    await counts_conn.execute(
        "INSERT INTO source_features (source, natural_key, run_id, geom, attrs)"
        " VALUES ('osm_node', $1, $2, ST_SetSRID(ST_MakePoint($3, $4), 4326), '{}'::jsonb)",
        str(TIED_NODE), run, lon, lat)
    columns = ("accident_count", *(poi_count_column(k) for k in sorted(POI_COUNT_KINDS)))
    total = " + ".join(f"sum({c})" for c in columns)

    async def counted() -> tuple[float, float]:
        """(区間の数の総和, 道の数の総和)。"""
        return (await counts_conn.fetchval(f"SELECT {total} FROM edge_materials"),
                await counts_conn.fetchval(f"SELECT {total} FROM way_materials"))

    await counts_conn.execute(
        "UPDATE node_materials SET kind = 'crossing', has_traffic_signals = false"
        " WHERE osm_node_id = $1", TIED_NODE)
    await derive_counts.derive(counts_conn)
    before = await counted()
    await counts_conn.execute(
        "UPDATE node_materials SET kind = NULL WHERE osm_node_id = $1", TIED_NODE)
    await counts_conn.execute("DELETE FROM source_features WHERE source = 'accident'")
    await derive_counts.derive(counts_conn)
    after = await counted()

    # 前提: 1回目は数が付いている。
    assert all(n > 0 for n in before)
    assert after == (0, 0)


async def test_an_accident_without_a_bicycle_is_not_counted(counts_conn):
    """自転車の関わらない事故は数えない。同じ場所の自転車の事故は数える。"""
    await _insert_accident(counts_conn, "car", _north_of_way(5.0), bicycle=False)
    await _insert_accident(counts_conn, "bicycle", _north_of_way(5.0))

    await derive_counts.derive(counts_conn)

    assert await _accidents(counts_conn) == {(100, 0): 1.0, (300, 0): 1.0}


async def test_an_accident_farther_than_the_match_distance_is_not_counted(counts_conn):
    """道から帰属の距離より遠い事故は、最も近い道にも付けない。距離の内側の事故は付ける。"""
    await _insert_accident(counts_conn, "near", _north_of_way(ACCIDENT_MATCH_MAX_DISTANCE_M - 10))
    await _insert_accident(counts_conn, "far", _north_of_way(ACCIDENT_MATCH_MAX_DISTANCE_M + 10))

    await derive_counts.derive(counts_conn)

    assert await _accidents(counts_conn) == {(100, 0): 1.0, (300, 0): 1.0}


async def test_an_accident_goes_to_the_segment_nearest_on_the_ground(counts_conn):
    """事故は地上の距離（m）で最も近い区間へ付く。

    道300から北へ11.5m・南北に延びる道400から西へ10mの点は、道400の方が近い。緯度経度の度の
    まま比べると、東西の10mは南北の11.5mより大きな度になる（経度1度が緯度1度より短い）。
    """
    lon, lat = _north_of_way(11.5)
    east = lon + 10.0 / (km_per_degree_longitude(lat) * 1000.0)
    south, north = _north_of_way(6.5)[1], _north_of_way(40.0)[1]
    await counts_conn.execute(
        "INSERT INTO source_features (source, natural_key, run_id, geom, attrs, payload)"
        " SELECT 'osm_way', '400', run_id, ST_GeomFromText($1, 4326), '{}'::jsonb, $2"
        " FROM source_runs WHERE source = 'osm_way'",
        f"LINESTRING({east} {south}, {east} {north})", struct.pack("<2q", 7, 8))
    await _insert_accident(counts_conn, "between", (lon, lat))

    await derive_topology.derive(counts_conn)
    await derive_counts.derive(counts_conn)

    assert await _accidents(counts_conn) == {(100, 0): 1.0, (400, 0): 1.0}


async def test_only_a_fatal_accident_is_weighted(counts_conn):
    """死亡事故は重みの件数分、死亡以外の事故（ノード3の事故）は1件と数える。"""
    await _insert_accident(counts_conn, "fatal", _north_of_way(5.0), fatal=True)

    await derive_counts.derive(counts_conn)

    assert await _accidents(counts_conn) == {(100, 0): 1.0, (300, 0): ACCIDENT_FATAL_WEIGHT}


async def test_a_stop_point_on_no_segment_is_not_counted(counts_conn):
    """どの区間にも乗らない停止要因の点（取り込んでいない道の上の点等）は、すぐ隣の道にも
    数えない。区間の端に乗る点は数える（行き止まりなので入る区間の0.5）。"""
    stop = {"highway": "stop"}
    await _derive_with_nodes(counts_conn, {9: (_north_of_way(5.0), stop), 4: (_point(4), stop)})

    assert await _stop_counts(counts_conn) == {100: {}, 200: {"stop": 0.5}, 300: {}}


async def test_a_point_that_is_not_a_stop_is_not_counted(counts_conn):
    """停止要因の種別でない点（補給の店等）は、区間の上にあっても停止の数に入らない。"""
    await _derive_with_nodes(counts_conn, {
        TIED_NODE: (_point(TIED_NODE), {"shop": "convenience"}),
        4: (_point(4), {"highway": "stop"}),
    })

    assert await _stop_counts(counts_conn) == {100: {}, 200: {"stop": 0.5}, 300: {}}
