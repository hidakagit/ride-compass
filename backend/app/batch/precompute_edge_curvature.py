"""road_edges.curvature_deg_per_km（蛇行の強さ）の事前計算バッチ。

折れ線の頂点ごとの方位変化を積み上げ距離kmで割った値。既存行はmigration 0035の適用後も
NULL（未計算）のままで、再splitされない限り埋まらないため、適用後の実行が必須。
NULLは「未計算」であって0（まっすぐ）ではない——0で埋めると、未計算の区間が
「まっすぐな良い道」として評価に混ざる。

計算はPostGISで完結しPythonへ行を持ち出さない（本番500万行規模のため）。SQLは
`road_graph_repository.py`が持ち（way単位版と測り方を共有する）、ここは対象edge_idを
チャンクで切り出して呼ぶだけ。
road_edgesが変わった場合（PBF再取込・再split）は再実行が必要。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.precompute_edge_curvature
    .venv\\Scripts\\python.exe -m app.batch.precompute_edge_curvature --database-url ...
    --dry-runで対象件数のログのみ（DB書き込みなし）
"""

import logging
import math
import sys
import time

from sqlalchemy import select

from app.batch._common import batch_session_factory, count_targets, run_simple_batch_cli, stream_id_chunks
from app.infrastructure.road_graph_models import RoadEdgeRow
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("ridecompass.precompute_edge_curvature")

# 1文で全件更新すると本番規模では長時間ロックを取り続けるため、対象edge_idを分割する。
CHUNK_SIZE = 200_000


def _target_edge_ids_stmt():
    # 長さ0のEdgeは度/kmを測れないため対象外（NULL＝算出不能のまま残す）。
    return select(RoadEdgeRow.edge_id).where(RoadEdgeRow.distance_m > 0)


async def run(database_url: str | None, dry_run: bool) -> int:
    started = time.perf_counter()
    stmt = _target_edge_ids_stmt()
    async with batch_session_factory(database_url) as session_factory:
        edge_count = await count_targets(session_factory, stmt)

        logger.info("対象road_edges: %d件（%d件ずつ更新）", edge_count, CHUNK_SIZE)
        if dry_run:
            logger.info("dry-run完了: DB書き込みなし elapsed=%.1fs", time.perf_counter() - started)
            return 0
        if edge_count == 0:
            logger.warning("road_edgesが0件のため更新をスキップします")
            return 0
        total_chunks = math.ceil(edge_count / CHUNK_SIZE)

        updated = 0
        chunk_index = -1
        async for chunk in stream_id_chunks(session_factory, stmt, CHUNK_SIZE):
            chunk_index += 1
            chunk_started = time.perf_counter()
            async with session_factory() as session:
                repository = RoadGraphRepository(session)
                rowcount = await repository.recompute_edge_curvature(chunk)
                await session.commit()
            updated += rowcount
            logger.info(
                "chunk %d/%d 完了: 累計%d/%d件 chunk_ms=%d",
                chunk_index + 1, total_chunks, updated, edge_count,
                round((time.perf_counter() - chunk_started) * 1000),
            )

        logger.info("蛇行の事前計算完了: %d件 elapsed=%.1fs", updated, time.perf_counter() - started)
        return 0


def main(argv: list[str] | None = None) -> int:
    return run_simple_batch_cli(argv, description="road_edges.curvature_deg_per_km事前計算バッチ", run_fn=run)


if __name__ == "__main__":
    sys.exit(main())
