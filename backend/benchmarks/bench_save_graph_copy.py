"""save_graph（RoadGraphRepository.save_graph）のバルクUPSERT段（node_upsert/edge_upsert）を
現行実装（`INSERT ... ON CONFLICT`をchunk=1000で繰り返す）と、asyncpg COPYを使う代替実装で
比較する（改善計画T248候補1・T259のフォローアップ）。

T259で本番実測した「20km・未split地点は本番HTTP経由でRenderの約100秒プラットフォーム
タイムアウトに到達し完全失敗する」を受け、T248の実測（前橋10km save_graph total_ms=42,406
のうちedge_upsert=30,172が支配的、王子30kmではedge_upsert_ms=149,235）の主因である
バルクUPSERT段を高速化できるか検証する。

現行実装（`_bulk_upsert`）はSQLAlchemy CoreのVALUES一括INSERT ... ON CONFLICTを
1000行/チャンクで繰り返す。代替実装は、PBF取込バッチ（app/batch/import_pbf.py）が
既に使っているCOPY→一時テーブル→INSERT...SELECT...ON CONFLICTのパターンを踏襲し、
`AsyncSession`の裏にある生のasyncpg接続（`(await session.connection()).get_raw_connection()`の
`.driver_connection`、SQLAlchemy 2.0の正式なAPI）からCOPYを発行する。

実行方法（backend/ディレクトリから、dev DBに東京都心データが取込済みであること）:
    .venv\\Scripts\\python.exe -m benchmarks.bench_save_graph_copy
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from shapely.geometry import LineString, Point
from shapely import wkb as shapely_wkb
from sqlalchemy import text

from benchmarks._harness import BenchmarkResult, print_report

ORIGIN_LAT = 35.681
ORIGIN_LON = 139.767


async def _build_primary_graph(session_factory, distance_km: float):
    from app.domain.graph import RoadGraph, build_road_graph
    from app.domain.route import Coordinates
    from app.infrastructure.road_graph_repository import RoadGraphRepository
    from app.services.road_graph_engine import BBOX_MARGIN_MIN_KM, BBOX_MARGIN_RATIO, _bbox_around_point
    from app.services.route_generator import RADIUS_RATIO

    origin = Coordinates(latitude=ORIGIN_LAT, longitude=ORIGIN_LON)
    radius_km = distance_km * RADIUS_RATIO
    margin_km = max(BBOX_MARGIN_MIN_KM, radius_km * BBOX_MARGIN_RATIO)
    bbox = _bbox_around_point(origin, radius_km + margin_km)

    async with session_factory() as session:
        way_specs, node_coords, primary_way_ids = await RoadGraphRepository(session).get_way_specs_with_closure(
            bbox
        )

    graph = build_road_graph(way_specs, node_coords)
    primary_edges = {eid: e for eid, e in graph.edges.items() if e.osm_way_id in primary_way_ids}
    referenced_node_ids = {e.from_node_id for e in primary_edges.values()} | {
        e.to_node_id for e in primary_edges.values()
    }
    primary_nodes = {nid: n for nid, n in graph.nodes.items() if nid in referenced_node_ids}
    primary_graph = RoadGraph(graph_version=graph.graph_version, nodes=primary_nodes, edges=primary_edges)
    return primary_graph, primary_way_ids


async def _copy_based_save(session, graph, way_ids_to_replace: set[int]) -> None:
    """代替実装: COPY→一時テーブル→INSERT...SELECT...ON CONFLICT。

    既存のsave_graph同様、Nodeを先にUPSERTしてからEdgeをUPSERTする（FK制約順）。
    DELETE段（境界Edge差分削除）は現行実装と同じ結果になる前提のため計測から除外し、
    UPSERT段のみを比較する（T248実測でDELETE段はT246の対策により既に軽量[10秒台]と
    確認済みで、支配的なのはUPSERT段のため）。
    """
    now = datetime.now(timezone.utc)

    # SQLAlchemyのAsyncSessionは「autobegin」のため、SQLAlchemy経由で何か実行するまで
    # 実トランザクション（BEGIN）が送信されない。ここで生のasyncpg接続へ直接COPY/INSERTを
    # 発行する前に軽いSELECTを1つ挟んでBEGINを確定させないと、CREATE TEMP TABLE ...
    # ON COMMIT DROPが（asyncpg接続がautocommitのまま）即座にDROPされてしまい、直後の
    # TRUNCATEが存在しないテーブルへのアクセスになる。
    await session.execute(text("SELECT 1"))

    raw_conn = await session.connection()
    pooled = await raw_conn.get_raw_connection()
    asyncpg_conn = pooled.driver_connection

    await asyncpg_conn.execute(
        "CREATE TEMP TABLE IF NOT EXISTS _stage_road_nodes "
        "(node_id text, osm_node_id bigint, geom_wkb bytea) ON COMMIT DROP"
    )
    await asyncpg_conn.execute("TRUNCATE _stage_road_nodes")
    node_records = [
        (node.node_id, node.osm_node_id, shapely_wkb.dumps(Point(node.longitude, node.latitude)))
        for node in graph.nodes.values()
    ]
    await asyncpg_conn.copy_records_to_table(
        "_stage_road_nodes", records=node_records, columns=["node_id", "osm_node_id", "geom_wkb"]
    )
    await asyncpg_conn.execute(
        """
        INSERT INTO road_nodes (node_id, osm_node_id, geom, updated_at)
        SELECT node_id, osm_node_id, ST_SetSRID(ST_GeomFromWKB(geom_wkb), 4326), $1
        FROM _stage_road_nodes
        ON CONFLICT (node_id) DO UPDATE SET
            osm_node_id = EXCLUDED.osm_node_id, geom = EXCLUDED.geom, updated_at = EXCLUDED.updated_at
        """,
        now,
    )

    await asyncpg_conn.execute(
        "CREATE TEMP TABLE IF NOT EXISTS _stage_road_edges "
        "(edge_id text, from_node_id text, to_node_id text, geom_wkb bytea, "
        "distance_m float8, osm_way_id bigint, highway text, bearing_deg float8) ON COMMIT DROP"
    )
    await asyncpg_conn.execute("TRUNCATE _stage_road_edges")
    edge_records = [
        (
            edge.edge_id,
            edge.from_node_id,
            edge.to_node_id,
            shapely_wkb.dumps(LineString([(lon, lat) for lat, lon in edge.geometry])),
            edge.distance_m,
            edge.osm_way_id,
            edge.highway,
            edge.bearing_deg,
        )
        for edge in graph.edges.values()
        if edge.osm_way_id in way_ids_to_replace
    ]
    await asyncpg_conn.copy_records_to_table(
        "_stage_road_edges",
        records=edge_records,
        columns=["edge_id", "from_node_id", "to_node_id", "geom_wkb", "distance_m", "osm_way_id", "highway", "bearing_deg"],
    )
    await asyncpg_conn.execute(
        """
        INSERT INTO road_edges (edge_id, from_node_id, to_node_id, geom, distance_m, osm_way_id, highway, bearing_deg, updated_at)
        SELECT edge_id, from_node_id, to_node_id, ST_SetSRID(ST_GeomFromWKB(geom_wkb), 4326),
               distance_m, osm_way_id, highway, bearing_deg, $1
        FROM _stage_road_edges
        ON CONFLICT (edge_id) DO UPDATE SET
            from_node_id = EXCLUDED.from_node_id, to_node_id = EXCLUDED.to_node_id, geom = EXCLUDED.geom,
            distance_m = EXCLUDED.distance_m, osm_way_id = EXCLUDED.osm_way_id, highway = EXCLUDED.highway,
            bearing_deg = EXCLUDED.bearing_deg, updated_at = EXCLUDED.updated_at
        """,
        now,
    )


async def _current_bulk_upsert_save(session, graph, way_ids_to_replace: set[int]) -> None:
    """現行save_graphからDELETE段（T246で既に軽量化済み・比較対象外）を除いた
    node_upsert+edge_upsertのみを、現行の`_bulk_upsert`（chunk=1000のON CONFLICT）で再現する。
    `_copy_based_save`と同じ範囲（DELETE抜き）で公平に比較するため、`save_graph`本体は
    呼ばずここで組み立て直す。"""
    from shapely.geometry.base import BaseGeometry
    from geoalchemy2.shape import from_shape

    from app.infrastructure.road_graph_repository import _bulk_upsert, RoadNodeRow, RoadEdgeRow

    now = datetime.now(timezone.utc)
    node_rows = [
        {
            "node_id": node.node_id,
            "osm_node_id": node.osm_node_id,
            "geom": from_shape(Point(node.longitude, node.latitude), srid=4326),
            "updated_at": now,
        }
        for node in graph.nodes.values()
    ]
    await _bulk_upsert(session, RoadNodeRow, node_rows, ["node_id"], ["osm_node_id", "geom", "updated_at"])

    edge_rows = [
        {
            "edge_id": edge.edge_id,
            "from_node_id": edge.from_node_id,
            "to_node_id": edge.to_node_id,
            "geom": from_shape(LineString([(lon, lat) for lat, lon in edge.geometry]), srid=4326),
            "distance_m": edge.distance_m,
            "osm_way_id": edge.osm_way_id,
            "highway": edge.highway,
            "bearing_deg": edge.bearing_deg,
            "updated_at": now,
        }
        for edge in graph.edges.values()
        if edge.osm_way_id in way_ids_to_replace
    ]
    await _bulk_upsert(
        session, RoadEdgeRow, edge_rows, ["edge_id"],
        ["from_node_id", "to_node_id", "geom", "distance_m", "osm_way_id", "highway", "bearing_deg", "updated_at"],
    )


async def _run_scenario(session_factory, distance_km: float, repeat: int = 2) -> list[BenchmarkResult]:
    label = f"distance={distance_km}km"
    results: list[BenchmarkResult] = []

    graph, way_ids = await _build_primary_graph(session_factory, distance_km)
    scale_note = f"nodes={len(graph.nodes)} edges={len(graph.edges)}"
    print(f"[{label}] {scale_note}")

    # --- 現行実装（chunk=1000のON CONFLICT、DELETE段は既に軽量化済みのため比較対象外）---
    baseline_samples = []
    for _ in range(repeat):
        async with session_factory() as session:
            start = time.perf_counter()
            await _current_bulk_upsert_save(session, graph, way_ids)
            baseline_samples.append(time.perf_counter() - start)
            await session.rollback()  # 冪等性を保つため実コミットはしない
    results.append(BenchmarkResult(name=f"[{label}] 現行(chunk ON CONFLICT)", n=repeat, samples_s=baseline_samples, note=scale_note))

    # --- 代替実装（COPY→一時テーブル→ON CONFLICT）---
    copy_samples = []
    for _ in range(repeat):
        async with session_factory() as session:
            start = time.perf_counter()
            await _copy_based_save(session, graph, way_ids)
            copy_samples.append(time.perf_counter() - start)
            await session.rollback()
    results.append(BenchmarkResult(name=f"[{label}] COPY方式", n=repeat, samples_s=copy_samples, note=scale_note))

    return results


async def run() -> list[BenchmarkResult]:
    from app.infrastructure.database import get_engine, get_session_factory

    session_factory = get_session_factory()
    results: list[BenchmarkResult] = []
    try:
        results += await _run_scenario(session_factory, distance_km=10.0)
        results += await _run_scenario(session_factory, distance_km=20.0)
    finally:
        await get_engine().dispose()
    return results


if __name__ == "__main__":
    print_report(
        "save_graph bulk UPSERT: 現行(chunk ON CONFLICT) vs COPY方式（T248/T259）",
        asyncio.run(run()),
    )
