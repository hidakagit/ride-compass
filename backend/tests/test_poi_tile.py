"""停止要因・補給休憩のPOIタイル（`RoadGraphRepository.get_poi_tile_mvt`）が、近い点をどの単位で1点にまとめるか。

地図の点は凡例の行ごとにまとめる。数える側（`batch/derive_counts.py`）が1回と数える組でも、凡例で
分けて見せている種別は別の点のまま出る（数える側の読み替えは`test_derive_counts.py`）。
"""

import json
from datetime import UTC, datetime

import mapbox_vector_tile
import pytest
from sqlalchemy import text

from app.batch.ingest import ensure_partition
from app.domain.region import BoundingBox, tile_bounds_lonlat, tiles_covering_bbox
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.infrastructure.vector_tile import STOP_POI_LAYER_NAME

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

ZOOM = 14
BASE_LON, BASE_LAT = 139.70, 35.68
#: 経度方向に約9m。まとめる距離より十分近い。
NEAR = 0.0001
#: 緯度方向に約220m。まとめる距離より十分遠い。
FAR = 0.002

#: (osm_node_id, 経度, 緯度, 種別, 近くに信号があるか)。
NODES = (
    # 車道用と歩道・自転車道用の踏切は凡例で同じ「踏切」
    (1, BASE_LON, BASE_LAT, "level_crossing", False),
    (2, BASE_LON + NEAR, BASE_LAT, "railway_crossing", False),
    # 車止めとハンプ・狭さくは、数える側では同じ種別だが凡例では別の行
    (3, BASE_LON, BASE_LAT + FAR, "barrier", False),
    (4, BASE_LON + NEAR, BASE_LAT + FAR, "traffic_calming", False),
    # 信号のそばの横断歩道は信号
    (5, BASE_LON, BASE_LAT + 2 * FAR, "crossing", True),
    (6, BASE_LON + NEAR, BASE_LAT + 2 * FAR, "traffic_signals", True),
    # 補給休憩は別々の実体
    (7, BASE_LON, BASE_LAT + 3 * FAR, "convenience", False),
    (8, BASE_LON + NEAR, BASE_LAT + 3 * FAR, "convenience", False),
)


async def _insert_scene(session) -> None:
    connection = await session.connection()
    raw = await connection.get_raw_connection()
    await ensure_partition(raw.driver_connection, "osm_node")
    lons = [lon for _, lon, _, _, _ in NODES]
    lats = [lat for _, _, lat, _, _ in NODES]
    # 取込範囲の宣言（緯度・経度の順）。タイルはこの範囲に入るときだけ焼く。
    profile = {"target": {"bbox": [min(lats), min(lons), max(lats), max(lons)]}}
    run_id = (await session.execute(
        text("INSERT INTO source_runs (source, status, started_at, origin, profile, counts)"
             " VALUES ('osm_way', 'succeeded', :at, '{}'::jsonb, CAST(:profile AS jsonb), '{}'::jsonb)"
             " RETURNING run_id"),
        {"at": datetime.now(UTC), "profile": json.dumps(profile)},
    )).scalar_one()
    for node_id, lon, lat, kind, signals in NODES:
        await session.execute(
            text("INSERT INTO source_features (source, natural_key, run_id, geom, attrs)"
                 " VALUES ('osm_node', :key, :run, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), '{}'::jsonb)"),
            {"key": str(node_id), "run": run_id, "lon": lon, "lat": lat})
        await session.execute(
            text("INSERT INTO node_materials (osm_node_id, kind, has_traffic_signals, source_run_id)"
                 " VALUES (:id, :kind, :signals, :run)"),
            {"id": node_id, "kind": kind, "signals": signals, "run": run_id})


async def test_nearby_points_merge_only_within_the_same_legend_row(road_graph_session):
    await _insert_scene(road_graph_session)
    around = BoundingBox(min_latitude=BASE_LAT, min_longitude=BASE_LON,
                         max_latitude=BASE_LAT + 3 * FAR, max_longitude=BASE_LON + NEAR)
    tiles = tiles_covering_bbox(around, ZOOM)
    # 前提: 全部の点が1枚のタイルに入る（境界で分かれると、まとめ方ではなく切り方を見ることになる）。
    assert len(tiles) == 1
    x, y = tiles[0]

    tile = await RoadGraphRepository(road_graph_session).get_poi_tile_mvt(
        ZOOM, x, y, tile_bounds_lonlat(ZOOM, x, y))

    features = mapbox_vector_tile.decode(tile)[STOP_POI_LAYER_NAME]["features"]
    assert sorted(f["properties"]["kind"] for f in features) == [
        "barrier", "convenience", "convenience", "level_crossing", "traffic_calming", "traffic_signals"]
