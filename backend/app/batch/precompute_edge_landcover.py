"""edge_landcoverの事前集計バッチ。

`precompute_way_landcover.py`と同じリング・同じ割合の算出（`_landcover.py`を共有）を、
way丸ごとではなく**区間（`road_edges`）**に対して行う。母集団が違うだけで、値の意味は同じ。

`road_edges`はforward/backwardを別行で持つため、**向きに依らない区間の同定子**
（way＋両端ノードの小さい方・大きい方）ごとに1回だけ読む。路面タイルが代表として残す行は
`edge_id`昇順で決まり、materialが代表の向きにしか無いと値が落ちるため、鍵をedge_idにしない
（`road_graph_repository.py: _TILE_FEATURE_SOURCE_SQL`が`node_lo`/`node_hi`を出しているのと
同じ理由）。

`way_landcover`は置き換えない。`road_edges`は`presplit_road_graph.py`が埋める派生データで、
区間を持たないwayや未splitの範囲には行が作れないため、読み出し側はここに行が無ければway単位の
値へ落とす。

**このバッチをDBホスト（本番VM）上で走らせない**。本番DBはbackendと同じVMに同居しており、
重いバッチはVM全体を巻き込む（docs/disaster-recovery.md「既知のリスク」）。開発機から
`--database-url`で本番DBへ接続して実行する（`precompute_way_landcover.py`の本番実行と同じ
方法、docs/tasks/T624.md段階3）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.precompute_edge_landcover --raster <path>
    --dry-runで対象件数のログのみ（DB書き込み・ラスタ読み込みなし）
"""

import argparse
import asyncio
import logging
import math
import sys
import time
from datetime import datetime, timezone

import shapely
from shapely.geometry import LineString
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.batch._common import with_derived_data_revision_bump, batch_session_factory, count_targets, stream_id_chunks
from app.batch._landcover import NoValueReason, RasterSource, infer_data_version_from_filename, measure_ring
from app.config import settings
from app.domain.derived_data_versions import (
    LANDCOVER_ALGORITHM_VERSION,
    LANDCOVER_DEFAULT_BUFFER_M,
    LANDCOVER_DEFAULT_INNER_M,
    landcover_algorithm_version,
)
from app.domain.landcover import EdgeLandcover, raster_set_fingerprint
from app.infrastructure.road_graph_models import EdgeLandcoverRow, RoadEdgeRow
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("ridecompass.precompute_edge_landcover")

CHUNK_SIZE = 5_000
DEFAULT_BUFFER_M = LANDCOVER_DEFAULT_BUFFER_M
DEFAULT_INNER_M = LANDCOVER_DEFAULT_INNER_M
DATA_SOURCE = "esri-io-lulc"

_LATEST_SUCCEEDED_OSM_RUN_ID_SQL = text("SELECT MAX(id) FROM osm_import_runs WHERE status = 'succeeded'")

algorithm_version = landcover_algorithm_version
ALGORITHM_VERSION = LANDCOVER_ALGORITHM_VERSION


def _representative_edges():
    """物理区間ごとに1本だけ残した`road_edges`。残す側は`edge_id`昇順で決定論的に固定する
    （路面タイルの重複排除と同じ鍵・同じ規則、`_TILE_FEATURE_SOURCE_SQL`参照）。"""
    node_lo = func.least(RoadEdgeRow.from_node_id, RoadEdgeRow.to_node_id).label("node_lo")
    node_hi = func.greatest(RoadEdgeRow.from_node_id, RoadEdgeRow.to_node_id).label("node_hi")
    return (
        select(
            RoadEdgeRow.edge_id.label("edge_id"),
            RoadEdgeRow.osm_way_id.label("osm_way_id"),
            node_lo,
            node_hi,
            RoadEdgeRow.geom.label("geom"),
        )
        .where(RoadEdgeRow.osm_way_id.is_not(None))
        .distinct(RoadEdgeRow.osm_way_id, node_lo, node_hi)
        .order_by(RoadEdgeRow.osm_way_id, node_lo, node_hi, RoadEdgeRow.edge_id)
        .subquery()
    )


def _target_edge_ids_stmt(recompute: bool, raster_set: str | None = None, algorithm: str | None = None):
    """対象区間の代表`edge_id`を地理的順序で選ぶselect。`recompute=False`（既定）では
    既に結果を持つ区間をanti-joinで除外する（`precompute_way_landcover.py`と同じ考え方——
    除外するのは「値を持つ行」と「今回と同じラスタ構成・同じアルゴリズムで値なしと確定済み」）。
    """
    rep = _representative_edges()
    stmt = select(rep.c.edge_id)
    if not recompute:
        stmt = stmt.outerjoin(
            EdgeLandcoverRow,
            and_(
                EdgeLandcoverRow.osm_way_id == rep.c.osm_way_id,
                EdgeLandcoverRow.node_lo == rep.c.node_lo,
                EdgeLandcoverRow.node_hi == rep.c.node_hi,
            ),
        ).where(
            or_(
                EdgeLandcoverRow.osm_way_id.is_(None),
                and_(
                    EdgeLandcoverRow.trees_percent.is_(None),
                    or_(
                        EdgeLandcoverRow.source_raster_set.is_distinct_from(raster_set),
                        EdgeLandcoverRow.algorithm_version.is_distinct_from(algorithm),
                    ),
                ),
            )
        )
    else:
        stmt = stmt.select_from(rep)
    return stmt.order_by(rep.c.geom)


async def _fetch_segments(session: AsyncSession, edge_ids: list[str]) -> list[tuple[int, str, str, LineString]]:
    """代表edge_idから、区間の同定子とジオメトリを引く。"""
    stmt = select(
        RoadEdgeRow.osm_way_id,
        func.least(RoadEdgeRow.from_node_id, RoadEdgeRow.to_node_id),
        func.greatest(RoadEdgeRow.from_node_id, RoadEdgeRow.to_node_id),
        RoadEdgeRow.geom,
    ).where(RoadEdgeRow.edge_id.in_(edge_ids))
    rows = (await session.execute(stmt)).all()
    if not rows:
        return []
    geometries = shapely.from_wkb([bytes(row[3].data) for row in rows])
    return [(row[0], row[1], row[2], geom) for row, geom in zip(rows, geometries)]


async def run(
    database_url: str | None,
    raster_paths: list[str],
    buffer_m: float,
    inner_m: float,
    data_version: str | None,
    recompute: bool,
    dry_run: bool,
) -> int:
    started = time.perf_counter()
    version = algorithm_version(inner_m, buffer_m)
    raster_set = raster_set_fingerprint(raster_paths)
    stmt = _target_edge_ids_stmt(recompute, raster_set, version)
    async with batch_session_factory(database_url) as session_factory:
        target_count = await count_targets(session_factory, stmt)

        logger.info("対象区間数: %d件（chunk_size=%d）", target_count, CHUNK_SIZE)
        if dry_run:
            logger.info("dry-run完了: DB書き込み・ラスタ読み込みなし elapsed=%.1fs", time.perf_counter() - started)
            return 0
        if target_count == 0:
            logger.warning(
                "対象区間が0件のため更新をスキップします"
                "（road_edgesが空[presplit_road_graph.py未実行]、または全件計算済みの可能性）"
            )
            return 0
        total_chunks = math.ceil(target_count / CHUNK_SIZE)
        if not raster_paths:
            raise ValueError("--rasterが1件も指定されていません（dry-run以外では必須）")

        resolved_data_version = data_version or infer_data_version_from_filename(raster_paths[0])
        if not resolved_data_version:
            raise ValueError("--data-versionが未指定で、ファイル名からも推定できませんでした")

        sources = [RasterSource(path) for path in raster_paths]
        try:
            now = datetime.now(timezone.utc)
            total_written = 0
            total_out_of_range = 0
            total_partial_coverage = 0
            total_low_pixels = 0
            chunk_index = -1
            async for chunk in stream_id_chunks(session_factory, stmt, CHUNK_SIZE):
                chunk_index += 1
                chunk_started = time.perf_counter()
                chunk_out_of_range = 0
                chunk_partial_coverage = 0
                chunk_low_pixels = 0
                async with session_factory() as session:
                    segments = await _fetch_segments(session, chunk)
                    source_osm_import_run_id = (await session.execute(_LATEST_SUCCEEDED_OSM_RUN_ID_SQL)).scalar_one()

                    records: list[EdgeLandcover] = []
                    for osm_way_id, node_lo, node_hi, line in segments:
                        if not isinstance(line, LineString):
                            continue
                        measured = measure_ring(sources, line, inner_m, buffer_m)
                        if measured.percentages is None:
                            if measured.reason is NoValueReason.PARTIAL_COVERAGE:
                                chunk_partial_coverage += 1
                            elif measured.reason is NoValueReason.LOW_PIXELS:
                                chunk_low_pixels += 1
                            else:
                                chunk_out_of_range += 1
                        records.append(
                            EdgeLandcover(
                                osm_way_id=osm_way_id,
                                node_lo=node_lo,
                                node_hi=node_hi,
                                percentages=measured.percentages,
                                data_source=DATA_SOURCE,
                                data_version=resolved_data_version,
                                computed_at=now,
                                source_osm_import_run_id=source_osm_import_run_id,
                                algorithm_version=version,
                                source_raster_set=raster_set,
                            )
                        )

                    repository = RoadGraphRepository(session)
                    await repository.save_edge_landcover(records)
                    await session.commit()

                chunk_written = len(records) - chunk_out_of_range - chunk_partial_coverage - chunk_low_pixels
                total_written += chunk_written
                total_out_of_range += chunk_out_of_range
                total_partial_coverage += chunk_partial_coverage
                total_low_pixels += chunk_low_pixels
                logger.info(
                    "chunk %d/%d 完了: %d件書込（値なしで記録: 範囲外%d件・境界またぎ%d件・画素不足%d件） elapsed=%.1fs",
                    chunk_index + 1, total_chunks, chunk_written, chunk_out_of_range, chunk_partial_coverage,
                    chunk_low_pixels, time.perf_counter() - chunk_started,
                )

            log_completion = logger.warning if total_partial_coverage else logger.info
            log_completion(
                "区間土地被覆事前計算完了: 対象=%d件 書込=%d件 値なしで記録（範囲外=%d件 境界またぎ=%d件 "
                "画素不足=%d件） elapsed=%.1fs",
                target_count, total_written, total_out_of_range, total_partial_coverage, total_low_pixels,
                time.perf_counter() - started,
            )
            return 0
        finally:
            for source in sources:
                source.close()


async def run_default(database_url: str | None, dry_run: bool) -> int:
    """`refresh_derived.py`向けの薄いラッパー（`precompute_way_landcover.run_default`と同じ
    規約・同じラスタ設定を使う）。"""
    raster_paths = settings.lulc_raster_paths_list
    if not raster_paths and not dry_run:
        raise ValueError(
            "settings.lulc_raster_paths（環境変数LULC_RASTER_PATHS）が未設定です。"
            "ラスタを用意できない環境ではrefresh_derived.pyの--skip-landcoverを使ってください。"
        )
    return await run(database_url, raster_paths, DEFAULT_BUFFER_M, DEFAULT_INNER_M, None, False, dry_run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="edge_landcover事前集計バッチ")
    parser.add_argument("--raster", action="append", default=[], help="Esri LULC GeoTIFFのパス（複数指定可）")
    parser.add_argument("--buffer-m", type=float, default=DEFAULT_BUFFER_M, help="リング外径(m)")
    parser.add_argument("--inner-m", type=float, default=DEFAULT_INNER_M, help="リング内径・道路面除外幅(m)")
    parser.add_argument("--data-version", default=None, help="使用したラスタの年（省略時はファイル名から推定）")
    parser.add_argument("--recompute", action="store_true", help="既存行の有無に関わらず対象区間全件を再計算する")
    parser.add_argument("--dry-run", action="store_true", help="対象件数のみログ出力しDB書き込み・ラスタ読み込みを行わない")
    parser.add_argument("--database-url", default=None, help="対象DB（省略時はsettings.database_url）")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(
        with_derived_data_revision_bump(
            run(
                args.database_url,
                args.raster,
                args.buffer_m,
                args.inner_m,
                args.data_version,
                args.recompute,
                args.dry_run,
            ),
            database_url=args.database_url,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
