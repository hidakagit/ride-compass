"""取込・派生の段がSQLで直接書く列に、宣言の外の値をDBが入れさせないこと。

段はdomainの検査を通らずに書くため、入らないことはDBが断ることでしか確かめられない。
値の母集団（語彙）はdomainの宣言から導かれ、段が実際に付ける値は全部通る。
"""

import json

import asyncpg
import pytest
import pytest_asyncio
import shapely
from shapely.geometry import LineString

from app.batch import derive_topology
from app.batch._common import asyncpg_dsn
from app.batch.ingest import SourceRecord
from app.batch.source_adapters.osm_pbf import way_payload
from app.domain.traffic import DIRECTION_RULES, TAG_KIND_RULES, direction_sql, tag_kind_sql
from tests.conftest import postgis_database_url
from tests.source_ingest import ingest_records, point_record, way_record

# road_graph_session（conftest.py）と同じDBを使うため、docs/conventions/testing.mdのパターン2どおり
# loop_scope="module"・xdist_group="postgis"が必須。
pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

BASE_LON, BASE_LAT = 139.70, 35.68
STEP = 0.001
WAY_ID = 100
NODE_IDS = [1, 2]

TABLES = ("edge_materials", "way_materials", "road_edges", "node_materials",
          "source_features", "source_runs")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def conn(road_graph_engine):
    """道1本を取り込み、区間まで作った状態。`road_graph_engine`に依存するのはスキーマを作らせるため。"""
    connection = await asyncpg.connect(asyncpg_dsn(postgis_database_url()))
    try:
        await connection.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        await ingest_records("osm_node", [
            point_record(n, BASE_LON + STEP * n, BASE_LAT) for n in NODE_IDS], conn=connection)
        await ingest_records("osm_way", [way_record(
            WAY_ID, [(BASE_LON + STEP * n, BASE_LAT) for n in NODE_IDS], NODE_IDS)], conn=connection)
        await derive_topology.derive(connection)
        yield connection
    finally:
        await connection.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        await connection.close()


async def _write(conn: asyncpg.Connection, sql: str, *args) -> None:
    """1文を書いて巻き戻す。断られたらその例外がそのまま出る。"""
    transaction = conn.transaction()
    await transaction.start()
    try:
        await conn.execute(sql, *args)
    finally:
        await transaction.rollback()


@pytest.mark.parametrize("sql", [
    "UPDATE way_materials SET direction = 'sideways'",
    "UPDATE node_materials SET kind = 'not_a_kind'",
])
async def test_value_outside_the_vocabulary_is_refused(conn, sql):
    with pytest.raises(asyncpg.CheckViolationError):
        await _write(conn, sql)


def _tags_relation(tags: list[dict[str, str]]) -> str:
    """段の式が読む形（`id`・`tags`）の関係。"""
    return "SELECT * FROM (VALUES " + ", ".join(
        f"({i}, $${json.dumps(t)}$$::jsonb)" for i, t in enumerate(tags)) + ") AS t(id, tags)"


async def test_every_direction_the_rules_give_is_accepted(conn):
    """規則の全行と、どの規則にも当たらない道の向きを書く。"""
    tags = [{key: value} for key, value, _direction, _priority in DIRECTION_RULES] + [{}]
    directions = {row["direction"] for row in await conn.fetch(direction_sql(_tags_relation(tags)))}
    for direction in sorted(directions):
        await _write(conn, "UPDATE way_materials SET direction = $1", direction)


async def test_every_kind_the_classifier_gives_is_accepted(conn):
    """分類の表の全行と、自販機の判定の結果を書く。"""
    tags = [{key: value} for key, value, _kind, _priority in TAG_KIND_RULES] + [
        {"amenity": "vending_machine", "vending": "drinks"}, {"amenity": "vending_machine"}]
    kinds = {row["kind"] for row in await conn.fetch(tag_kind_sql(_tags_relation(tags)))}
    for kind in sorted(kinds):
        await _write(conn, "UPDATE node_materials SET kind = $1", kind)


async def test_edge_without_its_way_row_is_refused(conn):
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await _write(conn, "DELETE FROM way_materials WHERE osm_way_id = $1", WAY_ID)


async def test_way_without_kind_is_not_ingested(conn):
    record = SourceRecord(
        natural_key="200", attrs={"name": "種別の無い道"}, payload=way_payload(NODE_IDS),
        geom_wkb=shapely.to_wkb(LineString([(BASE_LON + STEP * n, BASE_LAT) for n in NODE_IDS])))
    with pytest.raises(asyncpg.CheckViolationError):
        await ingest_records("osm_way", [record], conn=conn)

    ways = await conn.fetch("SELECT natural_key FROM source_features WHERE source = 'osm_way'")
    assert [row["natural_key"] for row in ways] == [str(WAY_ID)]


async def test_second_derived_data_meta_row_is_refused(conn):
    with pytest.raises(asyncpg.CheckViolationError):
        await _write(conn, "INSERT INTO derived_data_meta (id, revision) VALUES (2, 1)")


async def test_two_axes_with_the_same_sort_order_are_refused(conn):
    insert = ("INSERT INTO axis_definitions (axis_id, sort_order, shape_params, default_weight)"
              " SELECT unnest($1::text[]), coalesce(max(sort_order), 0) + 1, '{}'::jsonb, 1.0"
              " FROM axis_definitions")
    with pytest.raises(asyncpg.UniqueViolationError):
        await _write(conn, insert, ["__test_axis_a", "__test_axis_b"])
