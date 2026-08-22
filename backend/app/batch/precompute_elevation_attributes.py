"""elevation_attributes（勾配、改善計画T218a）の全道路網一括事前計算バッチ。

Road Graphエンジンの探索コスト（`road_graph_engine.py: prepare`）は、リクエストの都度
GSIへ標高を問い合わせず、事前計算済みの`elevation_attributes`テーブルを単純なキー参照する
設計にした（T218a、T12 ADR Stage 0.5）。本バッチはそのための一括計算を行う。

実際の計算ロジック（Edgeの形状点ごとにGSI DEMタイル方式の`ElevationClient`で標高取得→
`compute_elevation_attribute`でaverage_grade等を算出→`elevation_attributes`へ保存）は
`ElevationAttributeService.get_attributes_for_graph`が実装・チューニング済み（他の
precomputeバッチと同じ「新しいロジックを二重に持たない」規約）。本バッチはチャンクごとに
実ジオメトリ付きEdgeを読み、同サービスへ渡すだけ。同サービスは既に`repository`経由で
「未計算のEdgeのみ計算」を行うため、本バッチは再実行しても未計算分だけを埋める形で
安全に再実行できる（`road_edges`にEdgeが追加された場合の増分実行にも使える）。

T10（DEMタイル化）によりGSIへの外部呼び出しはタイル単位（近接するEdge・形状点は
同一タイルを共有）に削減されているため、全道路網規模でも現実的な呼び出し回数で完了する
（1プロセス内で全チャンクを処理し、`ElevationClient`のタイルキャッシュ
（`_tile_grid_cache`・`infrastructure/tile_cache.py`）をチャンクをまたいで使い回す）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.precompute_elevation_attributes
    .venv\\Scripts\\python.exe -m app.batch.precompute_elevation_attributes --database-url ...
    --dry-runで対象件数のログのみ（DB書き込み・外部呼び出しなし）
"""

import argparse
import asyncio
import logging
import sys
import time

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.domain.graph import RoadGraph
from app.infrastructure.elevation_client import ElevationClient
from app.infrastructure.road_graph_models import RoadEdgeRow
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.elevation_attribute_service import ElevationAttributeService

logger = logging.getLogger("app.batch.precompute_elevation_attributes")

# 他のprecomputeバッチ（edge_attribute_counts等、CHUNK_SIZE=5,000）より小さくしている。
# こちらは外部HTTP呼び出しを伴うため、進捗ログを短い間隔で出し途中経過を追いやすくする。
CHUNK_SIZE = 2_000


async def _fetch_all_edge_ids(session: AsyncSession) -> list[str]:
    result = await session.execute(select(RoadEdgeRow.edge_id))
    return [row[0] for row in result.all()]


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def run(database_url: str | None, dry_run: bool) -> int:
    started = time.perf_counter()
    engine = create_async_engine(database_url or settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            edge_ids = await _fetch_all_edge_ids(session)

        logger.info("対象edge数: %d件（chunk_size=%d）", len(edge_ids), CHUNK_SIZE)
        if dry_run:
            logger.info("dry-run完了: DB書き込み・外部呼び出しなし elapsed=%.1fs", time.perf_counter() - started)
            return 0
        if not edge_ids:
            logger.warning("対象edgeが0件のため更新をスキップします（road_edgesが空の可能性）")
            return 0

        client = ElevationClient()
        chunks = _chunked(edge_ids, CHUNK_SIZE)
        total_computed = 0
        # ElevationClient本体はコネクションを内部で持たないため、AttributeErrorのT10と
        # 同じ理由（TLSハンドシェイク再確立の回避）でこのバッチ全体を通して1本のみ生成する。
        async with httpx.AsyncClient(timeout=15.0) as http_client:
            for chunk_index, chunk in enumerate(chunks):
                chunk_started = time.perf_counter()
                async with session_factory() as session:
                    repository = RoadGraphRepository(session)
                    edges = await repository.get_edges_with_geometry(chunk)
                    graph = RoadGraph(graph_version="batch-elevation", nodes={}, edges=edges)

                    service = ElevationAttributeService(client, http_client, repository=repository)
                    computed = await service.get_attributes_for_graph(graph)

                total_computed += len(computed)
                logger.info(
                    "chunk %d/%d 完了: %d件（累計%d件） elapsed=%.1fs",
                    chunk_index + 1, len(chunks), len(computed), total_computed,
                    time.perf_counter() - chunk_started,
                )

        logger.info(
            "標高属性事前計算完了: total=%d件 elapsed=%.1fs", total_computed, time.perf_counter() - started
        )
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="elevation_attributes事前計算バッチ（改善計画T218a）")
    parser.add_argument("--database-url", default=None, help="対象DB（省略時はsettings.database_url）")
    parser.add_argument("--dry-run", action="store_true", help="件数のみログ出力し外部呼び出し・DB書き込みを行わない")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(run(args.database_url, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
