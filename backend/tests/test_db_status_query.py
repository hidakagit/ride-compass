"""`infrastructure/db_status.py`の数の読み出し——表ごとの行数をテスト用DBで数える。

ここで見ないもの: 注意が要るかの判断 → `test_db_status_service.py`、応答への受け渡し → `test_db_status_routes.py`
"""

import pytest

from app.batch.dem_tile_store import PRODUCT_PRIORITY
from app.batch.ingest import partition_table_name
from app.domain.region import BoundingBox
from app.infrastructure.db_status import DbStatusQuery
from tests.source_ingest import dem_tile_records, ingest_records, way_record


@pytest.mark.asyncio(loop_scope="module")
async def test_each_table_shows_its_rows_and_a_partitioned_one_the_rows_of_all_its_partitions(road_graph_session):
    # 分割の親や分割しない表の行数を取り違えると、管理画面で「取り込んだのに入っていない」を見誤る。
    await ingest_records("osm_way", [
        way_record(way_id, [(139.70, 35.68 + 0.001 * way_id), (139.701, 35.68 + 0.001 * way_id)],
                   [way_id * 10, way_id * 10 + 1], {})
        for way_id in (1, 2, 3)])
    area = BoundingBox(min_latitude=35.68, min_longitude=139.70, max_latitude=35.681, max_longitude=139.701)
    dem_records = dem_tile_records(PRODUCT_PRIORITY[0], 15, area, lambda lon, lat: 50.0)
    await ingest_records("dem", dem_records)

    counts = await DbStatusQuery(road_graph_session).fetch_counts()
    rows = {table.table_name: table.row_count for table in counts.tables}

    # 取込1回につき`source_runs`へ1行。
    assert [rows[partition_table_name("osm_way")], rows[partition_table_name("dem")], rows["source_features"],
            rows["source_runs"]] == [3, len(dem_records), 3 + len(dem_records), 2]
