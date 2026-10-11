"""実DBとORMの宣言の差を出す（scripts/schema_gap.py）。

テストDBの表をトランザクションの中で宣言からずらし、ずらした分だけが差として出ることを見る。
差の出方はずらす前の測定と比べる——作業ツリーのテストDBが前の宣言のまま残っていても、
ずらしていない分は前後で同じなので結果に混ざらない。

ここで見ないもの: 接続先を選んで結果を出す実行口（`main`）と、本番で走らせる経路（`run_probe.py`。`test_run_probe.py`）。
"""

import pytest
from sqlalchemy import text

from scripts.schema_gap import collect_gaps

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def test_a_dropped_check_an_extra_check_and_a_loosened_column_are_each_reported(road_graph_engine):
    async with road_graph_engine.connect() as conn:
        await conn.begin()
        try:
            before = set(await conn.run_sync(collect_gaps))
            for ddl in (
                "ALTER TABLE road_edges DROP CONSTRAINT road_edges_distance_m_positive",
                "ALTER TABLE road_edges ADD CONSTRAINT extra CHECK (segment_index < 10000)",
                "ALTER TABLE road_edges ALTER COLUMN reverse_bearing_deg DROP NOT NULL",
                # 名前だけが違う制約は差ではない。
                "ALTER TABLE road_edges RENAME CONSTRAINT road_edges_geom_has_two_points TO renamed",
            ):
                await conn.execute(text(ddl))
            after = set(await conn.run_sync(collect_gaps))
        finally:
            await conn.rollback()

    assert before - after == set()
    added = sorted(after - before)
    assert len(added) == 3, added
    loosened, missing, extra = added
    assert missing.startswith("road_edges: ORMが宣言しているが実DBに無いCHECK") and "distance_m >" in missing
    assert extra.startswith("road_edges: 実DBにあるがORMが宣言していないCHECK") and "segment_index <" in extra
    assert loosened == "road_edges.reverse_bearing_deg: NULL許容が違う（実DB=NULL ORM=NOT NULL）"


async def test_a_missing_and_an_extra_not_null_on_a_source_partition_are_each_reported(road_graph_engine):
    # 標高の区画は画素（rast）を必ず持つと、アダプタが宣言している。
    async with road_graph_engine.connect() as conn:
        await conn.begin()
        try:
            await conn.execute(text("DROP TABLE IF EXISTS source_features_dem"))
            await conn.execute(text(
                "CREATE TABLE source_features_dem PARTITION OF source_features FOR VALUES IN ('dem')"))
            before = set(await conn.run_sync(collect_gaps))
            await conn.execute(text("ALTER TABLE source_features_dem ALTER COLUMN rast SET NOT NULL"))
            await conn.execute(text("ALTER TABLE source_features_dem ALTER COLUMN payload SET NOT NULL"))
            after = set(await conn.run_sync(collect_gaps))
        finally:
            await conn.rollback()

    assert before - after == {"source_features_dem.rast: NULL許容が違う（実DB=NULL 宣言=NOT NULL）"}
    assert after - before == {"source_features_dem.payload: NULL許容が違う（実DB=NOT NULL 宣言=NULL）"}


async def test_measures_while_an_ingest_holds_a_child_partition(road_graph_engine):
    # 取込は子パーティションを空けて入れ直す間、排他ロックを持ち続ける。そのあいだに測ると
    # 待ちきれずに落ち、差が無くてもデプロイが失敗で終わる。
    partition = "source_features_schema_gap_probe"
    async with road_graph_engine.begin() as conn:
        await conn.execute(text(
            f"CREATE TABLE {partition} PARTITION OF source_features FOR VALUES IN ('schema_gap_probe')"))
    try:
        async with road_graph_engine.connect() as ingest, road_graph_engine.connect() as conn:
            await ingest.begin()
            await ingest.execute(text(f"LOCK TABLE {partition} IN ACCESS EXCLUSIVE MODE"))
            try:
                await conn.run_sync(collect_gaps)
            finally:
                await ingest.rollback()
    finally:
        async with road_graph_engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE {partition}"))


async def test_measuring_leaves_no_table_behind(road_graph_engine):
    async with road_graph_engine.connect() as conn:
        await conn.run_sync(collect_gaps)
        temp_tables = await conn.scalar(text(
            "SELECT count(*) FROM pg_class WHERE relnamespace = pg_my_temp_schema()"))
    assert temp_tables == 0
