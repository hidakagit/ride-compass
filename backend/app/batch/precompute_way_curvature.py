"""way_geometry（way単位の形状由来スカラー）の事前計算バッチ。

現在の中身は蛇行の強さ（度/km）1列。母集団は`osm_raw_ways`全域で、road_edges
（ルート生成時に遅延構築される）には依存しない——地図タイル・区間インスペクタ・
軸スタジオの分布プレビューはway単位で材料を組むため、Edge単位の値では母集団が足りない。

同じ材料をwayの折れ線そのものへ測るため、wayをEdgeへ切り出す交差点頂点の折れも含み、
値はEdge単位（road_edges.curvature_deg_per_km）の延長加重平均以上になる。測り方のSQLは
`road_graph_repository.py`がEdge単位版と共有する。

migration 0036適用後、本番でも初回実行が必須（他のprecomputeバッチと同じ運用）。
osm_raw_waysが変わった場合（PBF再取込）は再実行し、タイル世代
（region_service.py: ROAD_SURFACE_TILE_VERSION）を対上げしてキャッシュ済みタイルの
陳腐化を断つこと。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.precompute_way_curvature
    .venv\\Scripts\\python.exe -m app.batch.precompute_way_curvature --database-url ...
    --dry-runで対象件数のログのみ（DB書き込みなし）
"""

import logging
import sys
from datetime import datetime, timezone

from sqlalchemy import select, text

from app.batch._common import batch_session_factory, run_chunked_precompute, run_simple_batch_cli
from app.infrastructure.road_graph_models import OsmRawWayRow
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("ridecompass.precompute_way_curvature")

# 1チャンクあたりのway数。precompute_way_attribute_counts.pyと同じ理由で
# request向けcommand_timeoutを受けない専用エンジンで動くため大きめでも安全側。
CHUNK_SIZE = 20_000

# 派生データの系譜追跡（precompute_way_attribute_counts.pyと同じ意味・同じ運用）。
ALGORITHM_VERSION = "v1"

_LATEST_SUCCEEDED_OSM_RUN_ID_SQL = text("SELECT MAX(id) FROM osm_import_runs WHERE status = 'succeeded'")


def _target_way_ids_stmt():
    # geomの有無で対象を絞らない。測れないwayもNULLの行を作ることで、`WayGeometryRow`が
    # 宣言する「行が無い＝未計算、列がNULL＝算出不能」の2状態が成立する。
    return select(OsmRawWayRow.osm_way_id)


async def run(database_url: str | None, dry_run: bool) -> int:
    stmt = _target_way_ids_stmt()
    async with batch_session_factory(database_url) as session_factory:
        now = datetime.now(timezone.utc)

        async def handle_chunk(chunk: list[int]) -> int:
            async with session_factory() as session:
                source_osm_run_id = (await session.execute(_LATEST_SUCCEEDED_OSM_RUN_ID_SQL)).scalar_one()
                repository = RoadGraphRepository(session)
                await repository.recompute_way_curvature(chunk, now, source_osm_run_id, ALGORITHM_VERSION)
                await session.commit()
            logger.info("系譜: source_osm_run_id=%s", source_osm_run_id)
            return len(chunk)

        return await run_chunked_precompute(
            session_factory, stmt, CHUNK_SIZE, handle_chunk,
            logger=logger,
            target_label="対象way数",
            empty_warning="対象wayが0件のため更新をスキップします（osm_raw_waysが空の可能性）",
            dry_run=dry_run,
        )


def main(argv: list[str] | None = None) -> int:
    return run_simple_batch_cli(argv, description="way_geometry事前集計バッチ", run_fn=run)


if __name__ == "__main__":
    sys.exit(main())
