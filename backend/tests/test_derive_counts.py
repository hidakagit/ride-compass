"""区間と道に付く数の値（`batch/derive_counts.py`）が、意図した区間へ数を付けること。

見るもの: 事故を付ける区間（等距離のタイ・地上の距離・帰属の距離の両側・自転車の関わらない事故・死亡の重み）、
道路網に乗らない停止要因、信号の近くの横断歩道を信号として数える呼び出し、流し直しで数が0へ戻ること（区間と道の和）。
見ないもの: 停止要因と交差点の数え方（場所1つを経路の上で1回） → `test_derive_stop_counts.py`。タグから
種別・数える種別への読み替えの両側 → `test_tag_classification.py`。生データから消えた道の行が残らないことは
`derive_topology`が表を空にして入れ直すことで、外すと主キーの重複で作り直しが落ちる。
"""

import asyncpg
import pytest
import pytest_asyncio

from app.batch import derive_counts, derive_node_materials, derive_topology
from app.domain.accident import (
    ACCIDENT_FATAL_WEIGHT,
    ACCIDENT_MATCH_MAX_DISTANCE_M,
    PartyType,
)
from app.domain.geo import KM_PER_DEGREE_LATITUDE, km_per_degree_longitude
from app.domain.traffic import POI_COUNT_KINDS, poi_count_column
from app.domain.tuning import TUNING_PARAMETERS_BY_ID
from app.infrastructure.source_models import ACCIDENTS_SOURCE_SQL, PARTY_TYPE_CODES
from tests.conftest import empty_ingested_tables
from tests.source_ingest import ingest_records, point_record, way_record

# road_graph_session（conftest.py）と同じDBを使うため、.claude/rules/testing.mdのパターン2どおり
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
BICYCLE_PARTY = PARTY_TYPE_CODES[PartyType.BICYCLE]
OTHER_PARTY = "59"
CROSSING = {"highway": "crossing"}


def _point(node_id: int) -> tuple[float, float]:
    return (BASE_LON + STEP * node_id, BASE_LAT + STEP * (node_id % 2))


def _road(way_id: int, node_ids: list[int]):
    return way_record(way_id, [_point(n) for n in node_ids], node_ids)


def _north_of_way(meters: float) -> tuple[float, float]:
    """道300の中ほどから北へ`meters`離れた点。"""
    lon, lat = BESIDE_WAY
    return (lon, lat + meters / (KM_PER_DEGREE_LATITUDE * 1000.0))


def _accident(key: str, position: tuple[float, float], *, bicycle: bool = True, fatal: bool = False):
    """本票の列名で当事者種別と死者数を持つ事故の1件。"""
    return point_record(key, *position, {
        "当事者種別（当事者A）": BICYCLE_PARTY if bicycle else OTHER_PARTY,
        "当事者種別（当事者B）": OTHER_PARTY,
        "死者数": "001" if fatal else "000"})


async def _ingest_accidents(conn: asyncpg.Connection, *accidents) -> None:
    """ノード3の上の事故に`accidents`を加えて、事故を取り込み直す。"""
    await ingest_records("accident", [_accident("tied", _point(TIED_NODE)), *accidents], conn=conn)


async def _accidents(conn: asyncpg.Connection) -> dict[tuple[int, int], float]:
    """事故の付いた区間ごとの数。"""
    rows = await conn.fetch(
        "SELECT osm_way_id, segment_index, accident_count FROM edge_materials"
        " WHERE accident_count > 0")
    return {(r["osm_way_id"], r["segment_index"]): r["accident_count"] for r in rows}


async def _derive_with_nodes(conn: asyncpg.Connection,
                             nodes: dict[int, tuple[tuple[float, float], dict[str, str]]]) -> None:
    """{ノードid: (位置, タグ)} のノードを取り込み、ノードの段から流し直す。"""
    await ingest_records("osm_node", [
        point_record(node_id, lon, lat, tags) for node_id, ((lon, lat), tags) in nodes.items()], conn=conn)
    await derive_node_materials.derive(conn, TUNING_PARAMETERS_BY_ID["signal.match_radius_m"].default)
    await derive_counts.derive(conn)


async def _stop_counts(conn: asyncpg.Connection) -> dict[int, dict[str, float]]:
    """道ごとの、停止要因の集計キーごとの数（0は省く）。"""
    columns = {kind: poi_count_column(kind) for kind in sorted(POI_COUNT_KINDS)}
    rows = await conn.fetch(
        "SELECT osm_way_id, " + ", ".join(columns.values()) + " FROM way_materials")
    return {r["osm_way_id"]: {kind: r[c] for kind, c in columns.items() if r[c]} for r in rows}


@pytest_asyncio.fixture(loop_scope="module")
async def counts_conn(derive_conn):
    """テストごとに同じ生データから作り直す。どのテストも生データと派生の表を書き換えるため。"""
    conn = derive_conn
    await empty_ingested_tables(conn)
    await ingest_records("osm_way", [_road(*way) for way in WAYS], conn=conn)
    await _ingest_accidents(conn)
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
        f"SELECT DISTINCT e.geom <-> a.geom AS d FROM road_edges e, {ACCIDENTS_SOURCE_SQL} a")
    # 前提: 3区間とも本当に等距離（タイを作れている）。
    assert [r["d"] for r in distances] == [0.0]


async def test_a_crossing_near_a_signal_is_counted_as_a_signal(counts_conn):
    """近くに信号がある横断歩道は、横断歩道ではなく信号として数える。

    地図も同じ読み替えで信号の点を出す（`test_point_tiles.py`）。信号のノード9は道から北へ約10mで、
    どの区間にも乗らない。
    """
    lon, lat = _point(TIED_NODE)
    await _derive_with_nodes(counts_conn, {
        TIED_NODE: ((lon, lat), CROSSING), 9: ((lon, lat + 0.0001), {"highway": "traffic_signals"})})

    rows = await counts_conn.fetch(
        "SELECT DISTINCT m.poi_signal, m.poi_crossing FROM edge_materials m JOIN road_edges e"
        "  ON e.osm_way_id = m.osm_way_id AND e.segment_index = m.segment_index"
        " WHERE $1 IN (e.from_node_id, e.to_node_id)", TIED_NODE)
    assert [(r["poi_signal"] > 0, r["poi_crossing"]) for r in rows] == [(True, 0)]


async def test_rerun_on_changed_input_keeps_no_count_the_input_no_longer_supports(counts_conn):
    """入力を変えて流し直すと、停止要因も事故も無くなった区間・道の数は0へ戻る。道の数は区間の和。"""
    columns = ("accident_count", *(poi_count_column(k) for k in sorted(POI_COUNT_KINDS)))
    total = " + ".join(f"sum({c})" for c in columns)

    async def counted() -> tuple[float, float]:
        """(区間の数の総和, 道の数の総和)。"""
        return (await counts_conn.fetchval(f"SELECT {total} FROM edge_materials"),
                await counts_conn.fetchval(f"SELECT {total} FROM way_materials"))

    await _derive_with_nodes(counts_conn, {TIED_NODE: (_point(TIED_NODE), CROSSING)})
    before = await counted()
    await ingest_records("accident", [], conn=counts_conn)
    await _derive_with_nodes(counts_conn, {TIED_NODE: (_point(TIED_NODE), {})})
    after = await counted()

    assert before[0] > 0 and before[1] == before[0]
    assert after == (0, 0)


async def test_an_accident_without_a_bicycle_is_not_counted(counts_conn):
    """自転車の関わらない事故は数えない（自転車の事故はノード3の事故）。"""
    await _ingest_accidents(counts_conn, _accident("car", _north_of_way(5.0), bicycle=False))

    await derive_counts.derive(counts_conn)

    assert await _accidents(counts_conn) == {(100, 0): 1.0}


async def test_an_accident_farther_than_the_match_distance_is_not_counted(counts_conn):
    """道から帰属の距離より遠い事故は、最も近い道にも付けない。距離の内側の事故は付ける。"""
    await _ingest_accidents(counts_conn,
                            _accident("near", _north_of_way(ACCIDENT_MATCH_MAX_DISTANCE_M - 10)),
                            _accident("far", _north_of_way(ACCIDENT_MATCH_MAX_DISTANCE_M + 10)))

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
    await ingest_records("osm_way", [*(_road(*way) for way in WAYS),
                                     way_record(400, [(east, south), (east, north)], [7, 8])], conn=counts_conn)
    await _ingest_accidents(counts_conn, _accident("between", (lon, lat)))

    await derive_topology.derive(counts_conn)
    await derive_counts.derive(counts_conn)

    assert await _accidents(counts_conn) == {(100, 0): 1.0, (400, 0): 1.0}


async def test_only_a_fatal_accident_is_weighted(counts_conn):
    """死亡事故は重みの件数分、死亡以外の事故（ノード3の事故）は1件と数える。"""
    await _ingest_accidents(counts_conn, _accident("fatal", _north_of_way(5.0), fatal=True))

    await derive_counts.derive(counts_conn)

    assert await _accidents(counts_conn) == {(100, 0): 1.0, (300, 0): ACCIDENT_FATAL_WEIGHT}


async def test_a_stop_point_on_no_segment_is_not_counted(counts_conn):
    """どの区間にも乗らない停止要因の点（取り込んでいない道の上の点等）は、すぐ隣の道にも数えない。"""
    await _derive_with_nodes(counts_conn, {9: (_north_of_way(5.0), {"highway": "stop"})})

    assert await _stop_counts(counts_conn) == {100: {}, 200: {}, 300: {}}
