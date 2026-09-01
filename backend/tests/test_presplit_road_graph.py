"""app/batch/presplit_road_graph.pyの結合検証（改善計画T539）。

DB接続自体は実DBが要るため、他のbatchスクリプトのテストと同じ切り分け方針で
ridecompass_test（conftest.pyのroad_graph_session/road_graph_repositoryフィクスチャ）への
実接続を前提とする。接続できない環境ではフィクスチャがpytest.skip()する。
"""

import pytest
from sqlalchemy import select, text

from app.batch.presplit_road_graph import _fetch_all_tiles, run
from app.domain.graph import WaySpec
from app.domain.region import tile_bounds_lonlat, tiles_covering_bbox
from app.infrastructure.road_graph_models import RoadEdgeRow
from tests.conftest import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

ZOOM = 12
# test_road_graph_repository.pyのMVT_COVERAGE_TILE（z14 14549,6450の祖先）と同じ
# z12タイル。NODE1/NODE2（35.700/139.700付近）がこのタイル内に収まることは
# 既存テストで確認済みの組み合わせを再利用する。
TILE_X, TILE_Y = 3637, 1612
NODE1 = (35.700, 139.700)
NODE2 = (35.701, 139.701)
OSM_WAY_ID = 500


async def _mark_tile_cached(session, zoom: int, x: int, y: int) -> None:
    await session.execute(
        text(
            "INSERT INTO road_graph_tiles (zoom, x, y, fetched_at) VALUES (:zoom, :x, :y, now()) "
            "ON CONFLICT (zoom, x, y) DO UPDATE SET fetched_at = EXCLUDED.fetched_at"
        ),
        {"zoom": zoom, "x": x, "y": y},
    )


async def test_fetch_all_tiles_returns_marked_tiles(road_graph_session, road_graph_repository):
    await _mark_tile_cached(road_graph_session, ZOOM, TILE_X, TILE_Y)
    await road_graph_session.commit()

    tiles = await _fetch_all_tiles(road_graph_session, ZOOM)

    assert (TILE_X, TILE_Y) in tiles


async def test_run_splits_unsplit_tile_and_is_idempotent(road_graph_repository, road_graph_session):
    way = WaySpec(osm_way_id=OSM_WAY_ID, node_ids=[1, 2], highway="residential")
    await road_graph_repository.save_raw_ways([way], {1: NODE1, 2: NODE2})
    # GraphServiceの_ensure_tiles_cachedはbboxをtiles_covering_bboxで再分解して判定するため
    # （タイル境界の浮動小数点丸めで隣接タイルも対象に入ることがある）、対象タイル1枚だけでなく
    # 実際にカバレッジ判定で使われる集合をすべてマークする。
    bbox = tile_bounds_lonlat(ZOOM, TILE_X, TILE_Y)
    for x, y in tiles_covering_bbox(bbox, ZOOM):
        await _mark_tile_cached(road_graph_session, ZOOM, x, y)
    await road_graph_session.commit()

    # 事前実行前はroad_edgesが空（未split、実行時の遅延構築のみが埋める）。
    before = (
        await road_graph_session.execute(select(RoadEdgeRow).where(RoadEdgeRow.osm_way_id == OSM_WAY_ID))
    ).scalars().all()
    assert before == []

    assert await run(TEST_DATABASE_URL, dry_run=False) == 0

    after = (
        await road_graph_session.execute(select(RoadEdgeRow).where(RoadEdgeRow.osm_way_id == OSM_WAY_ID))
    ).scalars().all()
    assert len(after) >= 1

    # 再実行してもis_split_up_to_date判定によりスキップされ、エラーなく完走する（冪等性）。
    assert await run(TEST_DATABASE_URL, dry_run=False) == 0
    after_second = (
        await road_graph_session.execute(select(RoadEdgeRow).where(RoadEdgeRow.osm_way_id == OSM_WAY_ID))
    ).scalars().all()
    assert len(after_second) == len(after)


async def test_run_dry_run_does_not_write(road_graph_repository, road_graph_session):
    way = WaySpec(osm_way_id=OSM_WAY_ID + 1, node_ids=[3, 4], highway="residential")
    await road_graph_repository.save_raw_ways([way], {3: NODE1, 4: NODE2})
    bbox = tile_bounds_lonlat(ZOOM, TILE_X, TILE_Y)
    for x, y in tiles_covering_bbox(bbox, ZOOM):
        await _mark_tile_cached(road_graph_session, ZOOM, x, y)
    await road_graph_session.commit()

    assert await run(TEST_DATABASE_URL, dry_run=True) == 0

    after = (
        await road_graph_session.execute(select(RoadEdgeRow).where(RoadEdgeRow.osm_way_id == OSM_WAY_ID + 1))
    ).scalars().all()
    assert after == []
