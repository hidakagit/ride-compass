"""way_attribute_countsの事前集計バッチ。

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

import logging
import sys
import time
from datetime import datetime, timezone

from sqlalchemy import select, text

from app.batch._common import batch_session_factory, run_chunked_precompute, run_simple_batch_cli
from app.infrastructure.road_graph_models import OsmRawWayRow
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("ridecompass.precompute_way_attribute_counts")

# 1チャンクあたりのway数。precompute_edge_attribute_counts.pyと同じ理由で
# request向けcommand_timeoutを受けない専用エンジンで動くため大きめでも安全側。
CHUNK_SIZE = 5_000

# 派生データの系譜追跡。precompute_edge_attribute_counts.pyと同じ意味・同じ運用
# （ROAD_SURFACE_TILE_VERSIONと同種の手動版数）。edge単位版とway単位版は同じ
# 集計ロジック（意味論は共通、_RECOMPUTE_WAY_ATTRIBUTE_COUNTS_SQLのコメント参照）のため
# 同じ版数文字列を使うが、対象テーブルが別のため定数自体は独立に持つ（それぞれが
# 単独で読めることを優先、edge側の値と実際に揃っているかはコードレビュー時の目視確認）。
ALGORITHM_VERSION = "v2"

_LATEST_SUCCEEDED_ACCIDENT_RUN_ID_SQL = text(
    "SELECT MAX(id) FROM accident_import_runs WHERE status = 'succeeded'"
)
_LATEST_SUCCEEDED_OSM_RUN_ID_SQL = text("SELECT MAX(id) FROM osm_import_runs WHERE status = 'succeeded'")


def _target_way_ids_stmt():
    return (
        select(OsmRawWayRow.osm_way_id)
        .where(OsmRawWayRow.geom.is_not(None))
        .where(OsmRawWayRow.highway.is_not(None))
    )


async def run(database_url: str | None, dry_run: bool) -> int:
    stmt = _target_way_ids_stmt()
    async with batch_session_factory(database_url) as session_factory:
        if not dry_run:
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

        async def handle_chunk(chunk: list[int]) -> int:
            async with session_factory() as session:
                # run id取得はチャンクごとの直前で行う（precompute_edge_attribute_counts.py
                # と同種の対応、同ファイルのコメント参照）。各チャンクが実際に読んだ
                # accident_points/osm_raw_waysとの対応がズレないようにする。
                source_accident_run_id = (await session.execute(_LATEST_SUCCEEDED_ACCIDENT_RUN_ID_SQL)).scalar_one()
                source_osm_run_id = (await session.execute(_LATEST_SUCCEEDED_OSM_RUN_ID_SQL)).scalar_one()
                repository = RoadGraphRepository(session)
                await repository.recompute_way_attribute_counts(
                    chunk, now, source_accident_run_id, source_osm_run_id, ALGORITHM_VERSION
                )
                await session.commit()
            logger.info(
                "系譜: source_accident_run_id=%s source_osm_run_id=%s",
                source_accident_run_id, source_osm_run_id,
            )
            return len(chunk)

        return await run_chunked_precompute(
            session_factory, stmt, CHUNK_SIZE, handle_chunk,
            logger=logger,
            target_label="対象way数",
            empty_warning="対象wayが0件のため更新をスキップします（osm_raw_waysが空の可能性）",
            dry_run=dry_run,
        )


def main(argv: list[str] | None = None) -> int:
    return run_simple_batch_cli(argv, description="way_attribute_counts事前集計バッチ", run_fn=run)


if __name__ == "__main__":
    sys.exit(main())
