"""edge_attribute_countsの事前集計バッチ。

事故密度・停止密度（タグなし交差点込み、T149）のPostGIS空間結合は、既存の
`RoadGraphRepository.get_accident_counts`/`get_stop_poi_counts`/`get_intersection_counts`が
既に正しく実装・チューニング済み（GiST索引を使う`&&`前置フィルタ等、各メソッドのdocstring
参照）。本バッチは同じメソッドを`road_edges`全件に対してチャンク単位で呼び出し、結果を
`edge_attribute_counts`へUPSERTするだけで、新しいSQLは書かない（正確性・パフォーマンス
チューニングを二重に持たない）。

migration 0010適用後、本番でも初回実行が必須（`designation_attributes`と同じ運用、
`match_designations.py`のdocstring参照）。`accident_points`/`osm_raw_pois`/`road_edges`の
いずれかが変わった場合は再実行が必要（増分更新ではなく全件再計算、`designation_attributes`と
同じ設計）。**app.batch.precompute_road_node_degreesの実行後に行うこと**
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

from app.batch._common import chunked
from app.config import settings
from app.infrastructure.road_graph_models import EdgeAttributeCountsRow, RoadEdgeRow
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("app.batch.precompute_edge_attribute_counts")

# 1チャンクあたりのedge数。既存の per-request 呼び出し（ルート生成1回=数百edge程度）より
# 大きいが、request向けのcommand_timeout=20秒（infrastructure/database.py参照）を受けない
# 専用エンジン（バッチ・検証スクリプト共通の慣例、measure_axis_stats.py等参照）で動くため、
# 大きめでも安全側。実測に応じて調整可能。
# 1チャンクのUPSERT（列数×行数）がasyncpgのバインドパラメータ上限（32,767個/クエリ）を
# 超えないよう、4,000行×8列=32,000で上限内に収まる値にする。
CHUNK_SIZE = 4_000

# 計算ロジック自体（半径・重み付け等）の版数。region_service.py: ROAD_SURFACE_TILE_VERSIONと
# 同じ「パラメータを変えたら手動で上げる」運用。入力データの版数（source_*_import_run_id）
# とは別軸で、入力が同じでもロジック変更時は再計算が要ることを判別可能にするために持つ。
ALGORITHM_VERSION = "v1"

_LATEST_SUCCEEDED_ACCIDENT_RUN_ID_SQL = text(
    "SELECT MAX(id) FROM accident_import_runs WHERE status = 'succeeded'"
)
_LATEST_SUCCEEDED_OSM_RUN_ID_SQL = text("SELECT MAX(id) FROM osm_import_runs WHERE status = 'succeeded'")


async def _fetch_all_edge_ids(session: AsyncSession) -> list[str]:
    result = await session.execute(select(RoadEdgeRow.edge_id))
    return [row[0] for row in result.all()]


async def _fetch_source_run_ids(session: AsyncSession) -> tuple[int | None, int | None]:
    """派生データの系譜追跡用に、このバッチ実行時点でのaccident_import_runs/
    osm_import_runsの最新成功run idを取得する（高水位マーク、migrationのコメント参照）。"""
    accident_run_id = (await session.execute(_LATEST_SUCCEEDED_ACCIDENT_RUN_ID_SQL)).scalar_one()
    osm_run_id = (await session.execute(_LATEST_SUCCEEDED_OSM_RUN_ID_SQL)).scalar_one()
    return accident_run_id, osm_run_id


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

        logger.info("対象edge数: %d件（chunk_size=%d）", len(edge_ids), CHUNK_SIZE)
        if dry_run:
            logger.info("dry-run完了: DB書き込みなし elapsed=%.1fs", time.perf_counter() - started)
            return 0
        if not edge_ids:
            logger.warning("対象edgeが0件のため更新をスキップします（road_edgesが空の可能性）")
            return 0

        now = datetime.now(timezone.utc)

        # get_intersection_countsはroad_nodes.degree（DB全体から見た真のグローバル次数、
        # precompute_road_node_degrees.pyが事前計算）を参照するため、呼び出し元の集合に
        # 依存しない決定的な値を返す。road_edgesを空間的な連続性を考慮せず任意順に
        # チャンク分割しても、accident_count/stop_countと同じチャンク単位の呼び出しで
        # 問題ない。**本バッチの実行前にprecompute_road_node_degrees.pyの実行が必須**
        # （road_nodes.degreeが未計算＝全行0のままだとintersection_countも全件0になる）。
        total_written = 0
        chunks = chunked(edge_ids, CHUNK_SIZE)
        for chunk_index, chunk in enumerate(chunks):
            chunk_started = time.perf_counter()
            async with session_factory() as session:
                # run id取得はチャンクごとに直前で行う。edge_ids全体の処理は長時間かかりうるため、
                # 開始前に1回だけ取得すると、途中で別プロセスのimport_accidents.py/
                # import_pbf.pyが完了した場合に後半のチャンクの実際のデータと記録される
                # run idがずれる（match_designations.pyの同種の対応と同じ狙い）。
                source_accident_run_id, source_osm_run_id = await _fetch_source_run_ids(session)
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
                "chunk %d/%d 完了: %d件 source_accident_run_id=%s source_osm_run_id=%s elapsed=%.1fs",
                chunk_index + 1, len(chunks), len(rows), source_accident_run_id, source_osm_run_id,
                time.perf_counter() - chunk_started,
            )

        logger.info(
            "事前集計完了: total=%d件 elapsed=%.1fs", total_written, time.perf_counter() - started
        )
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="edge_attribute_counts事前集計バッチ")
    parser.add_argument("--database-url", default=None, help="対象DB（省略時はsettings.database_url）")
    parser.add_argument("--dry-run", action="store_true", help="件数のみログ出力しDBへ書き込まない")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(run(args.database_url, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
