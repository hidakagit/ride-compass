"""実DBとORMの宣言の差を出す（scripts/schema_gap.py）。

テストDBの表をトランザクションの中で宣言からずらし、ずらした分だけが差として出ることを見る。
差の出方はずらす前の測定と比べる——作業ツリーのテストDBが前の宣言のまま残っていても、
ずらしていない分は前後で同じなので結果に混ざらない。
"""

import pytest
from sqlalchemy import text

from scripts.schema_gap import collect_gaps

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]


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


async def test_measuring_leaves_no_table_behind(road_graph_engine):
    async with road_graph_engine.connect() as conn:
        await conn.run_sync(collect_gaps)
        temp_tables = await conn.scalar(text(
            "SELECT count(*) FROM pg_class WHERE relnamespace = pg_my_temp_schema()"))
    assert temp_tables == 0
