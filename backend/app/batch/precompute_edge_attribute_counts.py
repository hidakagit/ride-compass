"""edge_attribute_counts（改善計画T144）の事前集計バッチ。

事故密度・停止密度（タグなし交差点込み、T149）のPostGIS空間結合は、既存の
`RoadGraphRepository.get_accident_counts`/`get_stop_poi_counts`/`get_intersection_counts`が
既に正しく実装・チューニング済み（GiST索引を使う`&&`前置フィルタ等、各メソッドのdocstring
参照）。本バッチは同じメソッドを`road_edges`全件に対してチャンク単位で呼び出し、結果を
`edge_attribute_counts`へUPSERTするだけで、新しいSQLは書かない（正確性・パフォーマンス
チューニングを二重に持たない）。

migration 0010適用後、本番でも初回実行が必須（`designation_attributes`と同じ運用、
`match_designations.py`のdocstring参照）。`accident_points`/`osm_raw_pois`/`road_edges`の
いずれかが変わった場合は再実行が必要（増分更新ではなく全件再計算、`designation_attributes`と
同じ設計）。**app.batch.precompute_road_node_degrees（改善計画T151）の実行後に行うこと**
（intersection_countはこのバッチが書く`road_nodes.degree`を参照するため、未実行のままだと
全edgeでintersection_count=0になる）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.precompute_edge_attribute_counts
    .venv\\Scripts\\python.exe -m app.batch.precompute_edge_attribute_counts --database-url ...
    --dry-runで対象件数のログのみ（DB書き込みなし）
"""

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.infrastructure.road_graph_models import EdgeAttributeCountsRow, RoadEdgeRow
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("app.batch.precompute_edge_attribute_counts")

# 1チャンクあたりのedge数。既存の per-request 呼び出し（ルート生成1回=数百edge程度）より
# 大きいが、request向けのcommand_timeout=20秒（infrastructure/database.py参照）を受けない
# 専用エンジン（バッチ・検証スクリプト共通の慣例、measure_axis_stats.py等参照）で動くため、
# 大きめでも安全側。実測に応じて調整可能。
# 改善計画T351で列数が5→8へ増えたため、5,000のままだとasyncpgのバインドパラメータ上限
# （32,767個/クエリ、T224の教訓と同じ制約）を1チャンクのUPSERT（列数×行数）だけで
# 超過する（5,000行×8列=40,000）ようになった。4,000行×8列=32,000で上限内に収まる値へ
# 引き下げる（実機確認済み、2026-08-30）。
CHUNK_SIZE = 4_000

# 計算ロジック自体（半径・重み付け等）の版数（改善計画T351）。region_service.py:
# ROAD_SURFACE_TILE_VERSIONと同じ「パラメータを変えたら手動で上げる」運用。入力データの
# 版数（source_*_import_run_id）とは別軸で、入力が同じでもロジック変更時は再計算が要ることを
# 判別可能にするために持つ。
ALGORITHM_VERSION = "v1"

_LATEST_SUCCEEDED_ACCIDENT_RUN_ID_SQL = text(
    "SELECT MAX(id) FROM accident_import_runs WHERE status = 'succeeded'"
)
_LATEST_SUCCEEDED_OSM_RUN_ID_SQL = text("SELECT MAX(id) FROM osm_import_runs WHERE status = 'succeeded'")


async def _fetch_all_edge_ids(session: AsyncSession) -> list[str]:
    result = await session.execute(select(RoadEdgeRow.edge_id))
    return [row[0] for row in result.all()]


async def _fetch_source_run_ids(session: AsyncSession) -> tuple[int | None, int | None]:
    """派生データの系譜追跡（改善計画T351）用に、このバッチ実行時点でのaccident_import_runs/
    osm_import_runsの最新成功run idを取得する（高水位マーク、migrationのコメント参照）。"""
    accident_run_id = (await session.execute(_LATEST_SUCCEEDED_ACCIDENT_RUN_ID_SQL)).scalar_one()
    osm_run_id = (await session.execute(_LATEST_SUCCEEDED_OSM_RUN_ID_SQL)).scalar_one()
    return accident_run_id, osm_run_id


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def _upsert_chunk(session: AsyncSession, rows: list[dict]) -> None:
    if not rows:
        return
    stmt = pg_insert(EdgeAttributeCountsRow).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["edge_id"],
        set_={
            "accident_count": stmt.excluded.accident_count,
            "stop_count": stmt.excluded.stop_count,
            "intersection_count": stmt.excluded.intersection_count,
            "computed_at": stmt.excluded.computed_at,
            "source_accident_import_run_id": stmt.excluded.source_accident_import_run_id,
            "source_osm_import_run_id": stmt.excluded.source_osm_import_run_id,
            "algorithm_version": stmt.excluded.algorithm_version,
        },
    )
    await session.execute(stmt)
    await session.commit()


async def run(database_url: str | None, dry_run: bool) -> int:
    started = time.perf_counter()
    engine = create_async_engine(database_url or settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            edge_ids = await _fetch_all_edge_ids(session)
            source_accident_run_id, source_osm_run_id = await _fetch_source_run_ids(session)

        logger.info(
            "対象edge数: %d件（chunk_size=%d） source_accident_run_id=%s source_osm_run_id=%s",
            len(edge_ids), CHUNK_SIZE, source_accident_run_id, source_osm_run_id,
        )
        if dry_run:
            logger.info("dry-run完了: DB書き込みなし elapsed=%.1fs", time.perf_counter() - started)
            return 0
        if not edge_ids:
            logger.warning("対象edgeが0件のため更新をスキップします（road_edgesが空の可能性）")
            return 0

        now = datetime.now(timezone.utc)

        # 改善計画T151（2026-08-19改訂）: get_intersection_countsは以前「渡されたedge_ids
        # 集合内だけで完結するローカルな次数」を計算しており、本バッチのようにroad_edgesを
        # 空間的な連続性を考慮せず任意順にチャンク分割すると次数を過小評価する問題があった
        # （全edge一括で回避を試みても、内部の50,000件チャンク分割で同じ問題が再発しうる
        # ことが後日判明）。T151でroad_nodes.degree（DB全体から見た真のグローバル次数、
        # precompute_road_node_degrees.pyが事前計算）を参照する設計へ変更したため、
        # get_intersection_countsは呼び出し元の集合に依存しない決定的な値を返すようになり、
        # accident_count/stop_countと同じチャンク単位の呼び出しで問題なくなった。
        # **本バッチの実行前にprecompute_road_node_degrees.pyの実行が必須**
        # （road_nodes.degreeが未計算＝全行0のままだとintersection_countも全件0になる）。
        total_written = 0
        chunks = _chunked(edge_ids, CHUNK_SIZE)
        for chunk_index, chunk in enumerate(chunks):
            chunk_started = time.perf_counter()
            async with session_factory() as session:
                repository = RoadGraphRepository(session)
                stop_counts = await repository.get_stop_poi_counts(chunk)
                accident_counts = await repository.get_accident_counts(chunk)
                intersection_counts = await repository.get_intersection_counts(chunk)

                rows = [
                    {
                        "edge_id": edge_id,
                        "accident_count": accident_counts.get(edge_id, 0.0),
                        "stop_count": stop_counts.get(edge_id, 0),
                        "intersection_count": intersection_counts.get(edge_id, 0),
                        "computed_at": now,
                        "source_accident_import_run_id": source_accident_run_id,
                        "source_osm_import_run_id": source_osm_run_id,
                        "algorithm_version": ALGORITHM_VERSION,
                    }
                    for edge_id in chunk
                ]
                await _upsert_chunk(session, rows)
            total_written += len(rows)
            logger.info(
                "chunk %d/%d 完了: %d件 elapsed=%.1fs",
                chunk_index + 1, len(chunks), len(rows), time.perf_counter() - chunk_started,
            )

        logger.info(
            "事前集計完了: total=%d件 elapsed=%.1fs", total_written, time.perf_counter() - started
        )
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="edge_attribute_counts事前集計バッチ（改善計画T144）")
    parser.add_argument("--database-url", default=None, help="対象DB（省略時はsettings.database_url）")
    parser.add_argument("--dry-run", action="store_true", help="件数のみログ出力しDBへ書き込まない")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(run(args.database_url, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
