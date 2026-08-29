"""way_attribute_counts（改善計画T145b）の事前集計バッチ。

地図タイル（_ROAD_SURFACE_TILE_MVT_SQL）へ焼き込む事実カウント（事故・停止POI・交差点）の
way単位事前集計。母集団はosm_raw_ways全域（geom・highwayを持つway）で、Road Graph
（road_edges、ルート生成済みエリアのみ）には依存しない。

2段階で実行する:
1. raw_intersection_nodesの全再構築（osm_raw_ways.node_idsの隣接関係から次数3以上の
   生ノードを導出、`AttributeRepository.rebuild_raw_intersection_nodes`）
2. way単位カウントのチャンクUPSERT（`AttributeRepository.recompute_way_attribute_counts`、
   半径・kindフィルタ・死亡事故重みの意味論はedge単位版と同一）

SQLはroad_graph_repository.pyのリポジトリメソッドが実装済み（新しいSQLを二重に持たない、
既存の各precomputeバッチと同じ規約）。

migration 0012適用後、本番でも初回実行が必須（`edge_attribute_counts`と同じ運用）。
accident_points/osm_raw_pois/osm_raw_waysのいずれかが変わった場合（PBF再取込等）は
再実行し、タイル世代（region_service.py: ROAD_SURFACE_TILE_VERSION）を対上げして
キャッシュ済みタイルの陳腐化を断つこと。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.precompute_way_attribute_counts
    .venv\\Scripts\\python.exe -m app.batch.precompute_way_attribute_counts --database-url ...
    --dry-runで対象件数のログのみ（DB書き込みなし）
"""

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.infrastructure.road_graph_models import OsmRawWayRow
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("app.batch.precompute_way_attribute_counts")

# 1チャンクあたりのway数。precompute_edge_attribute_counts.pyと同じ理由で
# request向けcommand_timeoutを受けない専用エンジンで動くため大きめでも安全側。
CHUNK_SIZE = 5_000

# 派生データの系譜追跡（改善計画T351）。precompute_edge_attribute_counts.pyと同じ意味・
# 同じ運用（ROAD_SURFACE_TILE_VERSIONと同種の手動版数）。edge単位版とway単位版は同じ
# 集計ロジック（意味論は共通、_RECOMPUTE_WAY_ATTRIBUTE_COUNTS_SQLのコメント参照）のため
# 同じ版数文字列を使うが、対象テーブルが別のため定数自体は独立に持つ（それぞれが
# 単独で読めることを優先、edge側の値と実際に揃っているかはコードレビュー時の目視確認）。
ALGORITHM_VERSION = "v1"

_LATEST_SUCCEEDED_ACCIDENT_RUN_ID_SQL = text(
    "SELECT MAX(id) FROM accident_import_runs WHERE status = 'succeeded'"
)
_LATEST_SUCCEEDED_OSM_RUN_ID_SQL = text("SELECT MAX(id) FROM osm_import_runs WHERE status = 'succeeded'")


def _chunked(items: list[int], size: int) -> list[list[int]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def run(database_url: str | None, dry_run: bool) -> int:
    started = time.perf_counter()
    engine = create_async_engine(database_url or settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            result = await session.execute(
                select(OsmRawWayRow.osm_way_id)
                .where(OsmRawWayRow.geom.is_not(None))
                .where(OsmRawWayRow.highway.is_not(None))
            )
            way_ids = [row[0] for row in result.all()]
            source_accident_run_id = (await session.execute(_LATEST_SUCCEEDED_ACCIDENT_RUN_ID_SQL)).scalar_one()
            source_osm_run_id = (await session.execute(_LATEST_SUCCEEDED_OSM_RUN_ID_SQL)).scalar_one()

        logger.info(
            "対象way数: %d件（chunk_size=%d） source_accident_run_id=%s source_osm_run_id=%s",
            len(way_ids), CHUNK_SIZE, source_accident_run_id, source_osm_run_id,
        )
        if dry_run:
            logger.info("dry-run完了: DB書き込みなし elapsed=%.1fs", time.perf_counter() - started)
            return 0
        if not way_ids:
            logger.warning("対象wayが0件のため更新をスキップします（osm_raw_waysが空の可能性）")
            return 0

        intersection_started = time.perf_counter()
        async with session_factory() as session:
            repository = RoadGraphRepository(session)
            await repository.rebuild_raw_intersection_nodes()
            await session.commit()
        logger.info(
            "raw_intersection_nodes全再構築完了: elapsed=%.1fs",
            time.perf_counter() - intersection_started,
        )

        now = datetime.now(timezone.utc)
        total_written = 0
        chunks = _chunked(way_ids, CHUNK_SIZE)
        for chunk_index, chunk in enumerate(chunks):
            chunk_started = time.perf_counter()
            async with session_factory() as session:
                repository = RoadGraphRepository(session)
                await repository.recompute_way_attribute_counts(
                    chunk, now, source_accident_run_id, source_osm_run_id, ALGORITHM_VERSION
                )
                await session.commit()
            total_written += len(chunk)
            logger.info(
                "chunk %d/%d 完了: %d件 elapsed=%.1fs",
                chunk_index + 1, len(chunks), len(chunk), time.perf_counter() - chunk_started,
            )

        logger.info(
            "事前集計完了: total=%d件 elapsed=%.1fs", total_written, time.perf_counter() - started
        )
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="way_attribute_counts事前集計バッチ（改善計画T145b）")
    parser.add_argument("--database-url", default=None, help="対象DB（省略時はsettings.database_url）")
    parser.add_argument("--dry-run", action="store_true", help="件数のみログ出力しDBへ書き込まない")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(run(args.database_url, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
