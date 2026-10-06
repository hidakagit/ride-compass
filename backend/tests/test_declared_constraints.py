"""取込・派生の段がSQLで直接書く列に、宣言の外の値をDBが入れさせないこと。語彙の列
（`infrastructure/derived_models.py: vocabulary_check`）と、列の組（土地被覆の割合と有効画素・標高の4列・取込のrunの
状態と終わった時刻）。

段はdomainの検査を通らずに書くため、入らないことはDBが断ることでしか確かめられない。
値の母集団（語彙）はdomainの宣言から導かれ、分類器が実際に付ける値は全部通る。組の制約を通す側は、本物の段が書く行で
段のテスト（`test_derive_landcover.py`・`test_derive_elevation.py`・`test_ingest.py`）が通す。

ここで見ないもの:
- 制約を1つ宣言しただけのもの（区間から道の行への外部キー・種別の無い道・世代の2行目・軸の並び順の一意）
  ——PostgreSQLが宣言どおりに断る
- 通行方向の語彙が規則の出す値を全部通すこと——語彙（`domain/traffic.py: DIRECTIONS`）は規則と既定の値から作る
"""

import json

import asyncpg
import pytest
import pytest_asyncio

from app.batch import derive_topology
from app.batch.common import asyncpg_dsn
from app.domain.landcover import PERCENT_CLASSES, landcover_key
from app.domain.traffic import TAG_KIND_RULES, tag_kind_sql
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


_SHARES = ", ".join(f"lc_{landcover_key(name)} = 0" for name, _ in PERCENT_CLASSES)


@pytest.mark.parametrize("sql", [
    # 有効画素が正なのに割合が空。割合の合計がNULLになり、`IS NULL OR …`の形では通っていた
    "UPDATE edge_materials SET lc_valid_pixels = 100",
    # 有効画素が正で、割合が全部あるのに合計が100でない
    f"UPDATE edge_materials SET lc_valid_pixels = 100, {_SHARES}",
    # 有効画素が無いのに割合がある
    "UPDATE edge_materials SET lc_water = 100",
    # 道も区間と同じ制約を持つ
    "UPDATE way_materials SET lc_valid_pixels = 100",
    "UPDATE edge_materials SET start_elevation_m = 10",
    # 閉じたrunが終わった時刻を持たない・閉じていないrunが終わった時刻を持つ
    "UPDATE source_runs SET finished_at = NULL",
    "UPDATE source_runs SET status = 'running'",
])
async def test_a_row_breaking_a_column_group_is_refused(conn, sql):
    with pytest.raises(asyncpg.CheckViolationError):
        await _write(conn, sql)


def _tags_relation(tags: list[dict[str, str]]) -> str:
    """段の式が読む形（`id`・`tags`）の関係。"""
    return "SELECT * FROM (VALUES " + ", ".join(
        f"({i}, $${json.dumps(t)}$$::jsonb)" for i, t in enumerate(tags)) + ") AS t(id, tags)"


async def test_every_kind_the_classifier_gives_is_accepted(conn):
    """分類の表の全行と、自販機の判定の結果を書く。"""
    tags = [{key: value} for key, value, _kind, _priority in TAG_KIND_RULES] + [
        {"amenity": "vending_machine", "vending": "drinks"}, {"amenity": "vending_machine"}]
    kinds = {row["kind"] for row in await conn.fetch(tag_kind_sql(_tags_relation(tags)))}
    for kind in sorted(kinds):
        await _write(conn, "UPDATE node_materials SET kind = $1", kind)
