"""road_nodes.degreeの事前集計バッチ。

次数はroad_edges全件から見た「そのnode_idに接続する相異なる隣接node数」という
グラフ全体の集約値で、呼び出し元が渡すedge_ids集合には依存しない（渡された集合内だけで
完結するローカルな次数ではなく、DB全体から見た真のグローバル次数にすることで、
get_intersection_countsが呼び出し元のedge_ids集合やチャンク分割に依存しない結果を
返せるようにしている）。

実際の集計SQL（`_RECOMPUTE_NODE_DEGREES_SQL`）はroad_graph_repository.py:
`DerivedGraphRepository.recompute_node_degrees`が実装済み・チューニング済み
（新しいSQLを二重に持たない、既存の各precomputeバッチと同じ規約）。本バッチは
そのメソッドを呼び出すだけ。road_edgesの2倍行（from/to）をUNIONしてGROUP BYするだけの
単一SQLで完結し、accident_count/stop_countのようなPostGIS空間結合を伴わないため、
precompute_edge_attribute_counts.pyのようなチャンク分割は不要（本番207,767件規模でも
単一UPDATE...FROMで十分高速、実行時ログのelapsedで実測する）。

migration 0011適用後、本番でも初回実行が必須（`edge_attribute_counts`と同じ運用）。
road_edgesが変わった場合（PBF再取込等）は再実行が必要。
**precompute_edge_attribute_counts.pyより先に実行すること**
（intersection_countはこのバッチが書いたdegree列を参照するため）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.precompute_road_node_degrees
    .venv\\Scripts\\python.exe -m app.batch.precompute_road_node_degrees --database-url ...
    --dry-runで対象件数のログのみ（DB書き込みなし）
"""

import argparse
import asyncio
import logging
import sys
import time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.infrastructure.road_graph_models import RoadEdgeRow
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("app.batch.precompute_road_node_degrees")


async def run(database_url: str | None, dry_run: bool) -> int:
    started = time.perf_counter()
    engine = create_async_engine(database_url or settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            result = await session.execute(select(func.count()).select_from(RoadEdgeRow))
            edge_count = result.scalar_one()

        logger.info("対象road_edges: %d件", edge_count)
        if dry_run:
            logger.info("dry-run完了: DB書き込みなし elapsed=%.1fs", time.perf_counter() - started)
            return 0
        if edge_count == 0:
            logger.warning("road_edgesが0件のため更新をスキップします")
            return 0

        async with session_factory() as session:
            repository = RoadGraphRepository(session)
            await repository.recompute_node_degrees()
            await session.commit()

        logger.info("degree事前集計完了: elapsed=%.1fs", time.perf_counter() - started)
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="road_nodes.degree事前集計バッチ")
    parser.add_argument("--database-url", default=None, help="対象DB（省略時はsettings.database_url）")
    parser.add_argument("--dry-run", action="store_true", help="件数のみログ出力しDBへ書き込まない")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(run(args.database_url, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
