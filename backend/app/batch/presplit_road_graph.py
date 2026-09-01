"""交差点分割（split）をPBF取込後のバッチで全域に済ませ、実行時再構築を無くす（改善計画T539）。

未splitエリアへの初回リクエストは`GraphService.get_or_build_graph_with_attributes`の
再構築経路（closure取得→`build_road_graph`→`save_graph`、都心規模のbboxで数十秒級）が
リクエスト内で走る（改善計画T522「本番環境での再現・内訳調査」節）。本バッチは取込済み
全z12タイル（`road_graph_tiles`）を走査し、未split分だけへ同じ再構築経路を事前に適用する
（実際の分割ロジックは二重実装せず`GraphService`をそのまま呼ぶ。他のprecomputeバッチと
同じ「新しいロジックを二重に持たない」規約）。

`is_split_up_to_date`で既にsplit済みと判定できたタイルはスキップするため、再実行しても
未split分だけを埋める形で安全に再実行できる（PBF再取込後の定期実行を想定）。実行時の
`GraphService`側の再構築経路自体は、本バッチの実行漏れに対する安全網としてそのまま残る
（本バッチは「レスポンスを遅らせない事前実行」であり、機能上の必須ではない）。

依存関係の全体像はdocs/batch-pipeline-dependencies.mdを参照（本バッチは④、
precompute_road_node_degrees.py等road_edges起点の派生計算の前提）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.presplit_road_graph
    .venv\\Scripts\\python.exe -m app.batch.presplit_road_graph --database-url ...
    --dry-runで対象タイル数のログのみ（DB書き込みなし）
"""

import argparse
import asyncio
import logging
import sys
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.domain.region import ROAD_GRAPH_TILE_ZOOM, tile_bounds_lonlat
from app.infrastructure.road_graph_models import RoadGraphTileRow
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.graph_service import GraphService

logger = logging.getLogger("app.batch.presplit_road_graph")


async def _fetch_all_tiles(session: AsyncSession, zoom: int) -> list[tuple[int, int]]:
    result = await session.execute(
        select(RoadGraphTileRow.x, RoadGraphTileRow.y).where(RoadGraphTileRow.zoom == zoom)
    )
    return [(row.x, row.y) for row in result.all()]


async def run(database_url: str | None, dry_run: bool) -> int:
    started = time.perf_counter()
    engine = create_async_engine(database_url or settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            tiles = await _fetch_all_tiles(session, ROAD_GRAPH_TILE_ZOOM)

        logger.info("対象タイル数: %d件（zoom=%d）", len(tiles), ROAD_GRAPH_TILE_ZOOM)
        if dry_run:
            logger.info("dry-run完了: DB書き込みなし elapsed=%.1fs", time.perf_counter() - started)
            return 0
        if not tiles:
            logger.warning("対象タイルが0件のため処理をスキップします（road_graph_tilesが空の可能性）")
            return 0

        rebuilt = 0
        skipped = 0
        # タイルごとに新規セッションを開く（他のprecomputeバッチのチャンク単位セッションと
        # 同じ理由: 1タイルの再構築が数十秒級かかりうるため、長時間の単一トランザクションを
        # 避ける）。
        for index, (x, y) in enumerate(tiles):
            bbox = tile_bounds_lonlat(ROAD_GRAPH_TILE_ZOOM, x, y)
            tile_started = time.perf_counter()
            async with session_factory() as session:
                repository = RoadGraphRepository(session)
                if await repository.is_split_up_to_date(bbox):
                    skipped += 1
                    continue
                service = GraphService(repository=repository)
                await service.get_or_build_graph_with_attributes(bbox)
            rebuilt += 1
            logger.info(
                "tile %d/%d 再構築完了 zoom=%d x=%d y=%d elapsed=%.1fs",
                index + 1, len(tiles), ROAD_GRAPH_TILE_ZOOM, x, y, time.perf_counter() - tile_started,
            )

        logger.info(
            "交差点分割の事前実行完了: rebuilt=%d skipped=%d（既にsplit済み） elapsed=%.1fs",
            rebuilt, skipped, time.perf_counter() - started,
        )
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="交差点分割の事前実行バッチ（改善計画T539）")
    parser.add_argument("--database-url", default=None, help="対象DB（省略時はsettings.database_url）")
    parser.add_argument("--dry-run", action="store_true", help="対象タイル数のみログ出力しDB書き込みを行わない")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(run(args.database_url, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
