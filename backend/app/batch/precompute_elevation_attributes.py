"""elevation_attributesの全道路網一括事前計算バッチ。

Road Graphエンジンの探索コスト（`road_graph_engine.py: prepare`）は、リクエストの都度
GSIへ標高を問い合わせず、事前計算済みの`elevation_attributes`テーブルを単純なキー参照する
設計にした（T12 ADR Stage 0.5）。本バッチはそのための一括計算を行う。

実際の計算ロジック（Edgeの形状点ごとにGSI DEMタイル方式の`ElevationClient`で標高取得→
`compute_elevation_attribute`でaverage_grade等を算出→`elevation_attributes`へ保存）は
`ElevationAttributeService.get_attributes_for_graph`が実装・チューニング済み（他の
precomputeバッチと同じ「新しいロジックを二重に持たない」規約）。本バッチはチャンクごとに
実ジオメトリ付きEdgeを読み、同サービスへ渡すだけ。同サービスは既に`repository`経由で
「未計算のEdgeのみ計算」を行うため、本バッチは再実行しても未計算分だけを埋める形で
安全に再実行できる（`road_edges`にEdgeが追加された場合の増分実行にも使える）。

GSIへの外部呼び出しはタイル単位（近接するEdge・形状点は同一タイルを共有）に削減されて
いるため、全道路網規模でも現実的な呼び出し回数で完了する（1プロセス内で全チャンクを
処理し、`ElevationClient`のタイルキャッシュ（`_tile_grid_cache`・
`infrastructure/tile_cache.py`）をチャンクをまたいで使い回す）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.precompute_elevation_attributes
    .venv\\Scripts\\python.exe -m app.batch.precompute_elevation_attributes --database-url ...
    --dry-runで対象件数のログのみ（DB書き込み・外部呼び出しなし）
"""

import logging
import math
import sys
import time

import httpx
from sqlalchemy import select

from app.batch._common import batch_session_factory, count_targets, run_simple_batch_cli, stream_id_chunks
from app.domain.graph import RoadGraph
from app.infrastructure.elevation_client import ElevationClient
from app.infrastructure.road_graph_models import ElevationAttributeRow, RoadEdgeRow
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.elevation_attribute_service import ElevationAttributeService

logger = logging.getLogger("ridecompass.precompute_elevation_attributes")

# 他のprecomputeバッチ（edge_attribute_counts等、CHUNK_SIZE=5,000）より小さくしている。
# こちらは外部HTTP呼び出しを伴うため、進捗ログを短い間隔で出し途中経過を追いやすくする。
CHUNK_SIZE = 2_000


def _target_edge_ids_stmt():
    """未計算のEdge idを地理的順序（`ORDER BY geom`）で選ぶselect。

    計算済み（`elevation_attributes`に行がある）Edgeはanti-joinで最初から除外する
    ——再実行時に計算済み分のgeometryを読み直さずに済む。地理的順序にする理由・
    anti-joinの詳細はdocs/modules/backend/elevation.md「事前計算バッチ」節参照。
    """
    return (
        select(RoadEdgeRow.edge_id)
        .outerjoin(ElevationAttributeRow, ElevationAttributeRow.edge_id == RoadEdgeRow.edge_id)
        .where(ElevationAttributeRow.edge_id.is_(None))
        .order_by(RoadEdgeRow.geom)
    )


async def run(database_url: str | None, dry_run: bool) -> int:
    started = time.perf_counter()
    stmt = _target_edge_ids_stmt()
    async with batch_session_factory(database_url) as session_factory:
        target_count = await count_targets(session_factory, stmt)

        logger.info("対象edge数: %d件（chunk_size=%d）", target_count, CHUNK_SIZE)
        if dry_run:
            logger.info("dry-run完了: DB書き込み・外部呼び出しなし elapsed=%.1fs", time.perf_counter() - started)
            return 0
        if target_count == 0:
            logger.warning("対象edgeが0件のため更新をスキップします（road_edgesが空の可能性）")
            return 0
        total_chunks = math.ceil(target_count / CHUNK_SIZE)

        client = ElevationClient()
        total_computed = 0
        # ElevationClientはhttpx.AsyncClientを内部で持たない設計のため、TLSハンドシェイク
        # 再確立を避けてこのバッチ全体を通して1本のみ生成する。
        async with httpx.AsyncClient(timeout=15.0) as http_client:
            chunk_index = -1
            async for chunk in stream_id_chunks(session_factory, stmt, CHUNK_SIZE):
                chunk_index += 1
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
                    chunk_index + 1, total_chunks, len(computed), total_computed,
                    time.perf_counter() - chunk_started,
                )

        logger.info(
            "標高属性事前計算完了: total=%d件 elapsed=%.1fs", total_computed, time.perf_counter() - started
        )
        return 0


def main(argv: list[str] | None = None) -> int:
    return run_simple_batch_cli(argv, description="elevation_attributes事前計算バッチ", run_fn=run, dry_run_help="件数のみログ出力し外部呼び出し・DB書き込みを行わない")


if __name__ == "__main__":
    sys.exit(main())
