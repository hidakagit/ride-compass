"""edge_attribute_countsの事前集計バッチ。

事故密度・停止密度（タグなし交差点込み、T149）のPostGIS空間結合は、既存の
`RoadGraphRepository.get_accident_counts`/`get_intersection_counts`/`get_poi_counts_by_kind`が
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

import logging
import sys
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.batch._common import batch_session_factory, run_chunked_precompute, run_simple_batch_cli
from app.infrastructure.road_graph_models import RoadEdgeRow
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("ridecompass.precompute_edge_attribute_counts")

# 1チャンクあたりのedge数。既存の per-request 呼び出し（ルート生成1回=数百edge程度）より
# 大きいが、request向けのcommand_timeout=20秒（infrastructure/database.py参照）を受けない
# 専用エンジン（バッチ・検証スクリプト共通の慣例、measure_axis_stats.py等参照）で動くため、
# 大きめでも安全側。実測に応じて調整可能。
CHUNK_SIZE = 4_000

# 計算ロジック自体（半径・重み付け等）の版数。region_service.py: ROAD_SURFACE_TILE_VERSIONと
# 同じ「パラメータを変えたら手動で上げる」運用。入力データの版数（source_*_import_run_id）
# とは別軸で、入力が同じでもロジック変更時は再計算が要ることを判別可能にするために持つ。
ALGORITHM_VERSION = "v2"

_LATEST_SUCCEEDED_ACCIDENT_RUN_ID_SQL = text(
    "SELECT MAX(id) FROM accident_import_runs WHERE status = 'succeeded'"
)
_LATEST_SUCCEEDED_OSM_RUN_ID_SQL = text("SELECT MAX(id) FROM osm_import_runs WHERE status = 'succeeded'")


def _target_edge_ids_stmt():
    return select(RoadEdgeRow.edge_id)


async def _fetch_source_run_ids(session: AsyncSession) -> tuple[int | None, int | None]:
    """派生データの系譜追跡用に、このバッチ実行時点でのaccident_import_runs/
    osm_import_runsの最新成功run idを取得する（高水位マーク、migrationのコメント参照）。"""
    accident_run_id = (await session.execute(_LATEST_SUCCEEDED_ACCIDENT_RUN_ID_SQL)).scalar_one()
    osm_run_id = (await session.execute(_LATEST_SUCCEEDED_OSM_RUN_ID_SQL)).scalar_one()
    return accident_run_id, osm_run_id


async def run(database_url: str | None, dry_run: bool) -> int:
    stmt = _target_edge_ids_stmt()
    async with batch_session_factory(database_url) as session_factory:
        now = datetime.now(timezone.utc)

        # get_intersection_countsはroad_nodes.degree（DB全体から見た真のグローバル次数、
        # precompute_road_node_degrees.pyが事前計算）を参照するため、呼び出し元の集合に
        # 依存しない決定的な値を返す。road_edgesを空間的な連続性を考慮せず任意順に
        # チャンク分割しても、accident_countと同じチャンク単位の呼び出しで
        # 問題ない。**本バッチの実行前にprecompute_road_node_degrees.pyの実行が必須**
        # （road_nodes.degreeが未計算＝全行0のままだとintersection_countも全件0になる）。
        async def handle_chunk(chunk: list[str]) -> int:
            async with session_factory() as session:
                # run id取得はチャンクごとに直前で行う。edge_ids全体の処理は長時間かかりうるため、
                # 開始前に1回だけ取得すると、途中で別プロセスのimport_accidents.py/
                # import_pbf.pyが完了した場合に後半のチャンクの実際のデータと記録される
                # run idがずれる（match_designations.pyの同種の対応と同じ狙い）。
                source_accident_run_id, source_osm_run_id = await _fetch_source_run_ids(session)
                repository = RoadGraphRepository(session)
                accident_counts = await repository.get_accident_counts(chunk)
                intersection_counts = await repository.get_intersection_counts(chunk)
                poi_counts = await repository.get_poi_counts_by_kind(chunk)

                rows = [
                    {
                        "edge_id": edge_id,
                        "accident_count": accident_counts.get(edge_id, 0.0),
                        "intersection_count": intersection_counts.get(edge_id, 0),
                        "poi_counts": poi_counts.get(edge_id, {}),
                        "computed_at": now,
                        "source_accident_import_run_id": source_accident_run_id,
                        "source_osm_import_run_id": source_osm_run_id,
                        "algorithm_version": ALGORITHM_VERSION,
                    }
                    for edge_id in chunk
                ]
                await repository.save_edge_attribute_counts(rows)
                await session.commit()
            logger.info(
                "系譜: source_accident_run_id=%s source_osm_run_id=%s",
                source_accident_run_id, source_osm_run_id,
            )
            return len(rows)

        return await run_chunked_precompute(
            session_factory, stmt, CHUNK_SIZE, handle_chunk,
            logger=logger,
            target_label="対象edge数",
            empty_warning="対象edgeが0件のため更新をスキップします（road_edgesが空の可能性）",
            dry_run=dry_run,
        )


def main(argv: list[str] | None = None) -> int:
    return run_simple_batch_cli(argv, description="edge_attribute_counts事前集計バッチ", run_fn=run)


if __name__ == "__main__":
    sys.exit(main())
