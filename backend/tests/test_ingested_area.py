"""取り込んだ範囲（`RoadGraphRepository.get_ingested_area`・`is_covered`）を、取込の記録のどのrunから読むか。

取込はソースのパーティションを入れ替え、派生も成功した最新のrunから作る。手元の道路データの範囲は、その
runが記録した宣言の範囲だけで、古いrun・失敗したrunの範囲ではない。
"""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from app.domain.region import BoundingBox
from app.infrastructure.road_graph_repository import RoadGraphRepository

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

OLD = BoundingBox(min_latitude=35.0, min_longitude=139.0, max_latitude=35.5, max_longitude=139.5)
LATEST = BoundingBox(min_latitude=36.0, min_longitude=140.0, max_latitude=36.5, max_longitude=140.5)
FAILED = BoundingBox(min_latitude=37.0, min_longitude=141.0, max_latitude=37.5, max_longitude=141.5)


async def _record_run(session, source: str, status: str, area: BoundingBox) -> None:
    # 宣言の範囲は (min_lat, min_lon, max_lat, max_lon)（`batch/source_profile.yaml`の`target.bbox`）。
    bbox = [area.min_latitude, area.min_longitude, area.max_latitude, area.max_longitude]
    await session.execute(
        text("INSERT INTO source_runs (source, status, started_at, origin, profile, counts)"
             " VALUES (:source, :status, :at, '{}'::jsonb, CAST(:profile AS jsonb), '{}'::jsonb)"),
        {"source": source, "status": status, "at": datetime.now(UTC),
         "profile": json.dumps({"target": {"bbox": bbox}})},
    )


async def test_the_area_is_the_one_the_latest_succeeded_road_ingest_declared(road_graph_session):
    await _record_run(road_graph_session, "osm_way", "succeeded", OLD)
    await _record_run(road_graph_session, "osm_way", "succeeded", LATEST)
    await _record_run(road_graph_session, "osm_way", "failed", FAILED)
    await _record_run(road_graph_session, "accident", "succeeded", FAILED)
    repository = RoadGraphRepository(road_graph_session)

    assert await repository.get_ingested_area() == LATEST
    assert await repository.is_covered(LATEST)
    assert not await repository.is_covered(OLD)
    assert not await repository.is_covered(FAILED)


async def test_there_is_no_area_before_any_road_ingest_succeeded(road_graph_session):
    await _record_run(road_graph_session, "osm_way", "failed", FAILED)
    repository = RoadGraphRepository(road_graph_session)

    assert await repository.get_ingested_area() is None
    assert not await repository.is_covered(FAILED)
