"""edge_attribute_counts（改善計画T144の事前集計テーブル）の値が、都度クエリ
（`RoadGraphRepository.get_accident_counts`/`get_stop_poi_counts`/`get_intersection_counts`）と
一致することを検証する。

`app/batch/precompute_edge_attribute_counts.py`実行後、dev機・本番の両方でこのスクリプトを
実行し、事前集計値が正しいことを確認してから使う（T144の完了条件）。

**intersection_countの検証はaccident_count/stop_countと異なる方式を取る**（実装中に発見した
制約）。`get_intersection_countsの次数計算は「渡されたedge_ids集合内だけで完結するローカルな
次数」（`_INTERSECTION_COUNTS_SQL`のコメント参照）で、小さいランダムサンプルに対して都度
呼ぶと本来の次数を過小評価する（ノードに接続する道路の一部しかサンプルに含まれないため）。
事前集計バッチと同じく「全edge_idsを1回のクエリに渡した場合の値」（真のグローバルな次数）を
基準にする。accident_count/stop_countはedge単位で独立のためこの問題が無く、小サンプルの
都度クエリと直接比較する。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\verify_edge_attribute_counts.py
    .venv\\Scripts\\python.exe scripts\\verify_edge_attribute_counts.py --database-url ... --sample-size 500
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.config import settings  # noqa: E402
from app.infrastructure.road_graph_models import EdgeAttributeCountsRow, RoadEdgeRow  # noqa: E402
from app.infrastructure.road_graph_repository import RoadGraphRepository  # noqa: E402

DEFAULT_SAMPLE_SIZE = 500


async def main(database_url: str | None = None, sample_size: int = DEFAULT_SAMPLE_SIZE) -> int:
    engine = create_async_engine(database_url or settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    mismatches: list[str] = []
    try:
        async with session_factory() as session:
            total_precomputed = (
                await session.execute(text("SELECT COUNT(*) FROM edge_attribute_counts"))
            ).scalar_one()
            if total_precomputed == 0:
                print(
                    "edge_attribute_countsが空です。先にapp.batch.precompute_edge_attribute_counts"
                    "を実行してください。"
                )
                return 1

            sample_rows = (
                await session.execute(
                    select(EdgeAttributeCountsRow).order_by(EdgeAttributeCountsRow.edge_id).limit(sample_size)
                )
            ).scalars().all()
            sample_edge_ids = [row.edge_id for row in sample_rows]
            precomputed_by_id = {row.edge_id: row for row in sample_rows}

            repository = RoadGraphRepository(session)
            live_stop_counts = await repository.get_stop_poi_counts(sample_edge_ids)
            live_accident_counts = await repository.get_accident_counts(sample_edge_ids)

            # intersection_countは全edge_idsを1回のクエリに渡した場合の値（真のグローバルな
            # 次数）を基準にする（モジュールdocstring参照）。事前集計バッチと同じ計算方法。
            # **road_edges由来のedge_idsを使うこと**（バッチが使うのと同じソース・同じ順序系列）。
            # 検証実装中に、同一edge_id集合でもSELECT元テーブルが異なると配列の順序が変わり、
            # get_intersection_countsの結果が一部edgeで変わる非決定性を実際に確認した
            # （改善計画T151としてフォローアップ起票済み、get_stop_poi_counts/
            # get_accident_countsには無い問題）。road_edges起点に統一することで、
            # precompute_edge_attribute_counts.pyの計算時と同じ条件で再現し、この非決定性の
            # 影響を受けないようにする。
            all_edge_ids = [row[0] for row in (await session.execute(select(RoadEdgeRow.edge_id))).all()]
            global_intersection_counts = await repository.get_intersection_counts(all_edge_ids)
    finally:
        await engine.dispose()

    for edge_id in sample_edge_ids:
        precomputed = precomputed_by_id[edge_id]
        live_stop = live_stop_counts.get(edge_id, 0)
        live_intersection = global_intersection_counts.get(edge_id, 0)
        live_accident = live_accident_counts.get(edge_id, 0.0)

        if precomputed.stop_count != live_stop:
            mismatches.append(f"{edge_id}: stop_count precomputed={precomputed.stop_count} live={live_stop}")
        if precomputed.intersection_count != live_intersection:
            mismatches.append(
                f"{edge_id}: intersection_count precomputed={precomputed.intersection_count} live={live_intersection}"
            )
        if abs(precomputed.accident_count - live_accident) > 1e-9:
            mismatches.append(
                f"{edge_id}: accident_count precomputed={precomputed.accident_count} live={live_accident}"
            )

    print(f"edge_attribute_counts総件数: {total_precomputed}")
    print(f"検証サンプル数: {len(sample_edge_ids)}")
    if mismatches:
        print(f"不一致: {len(mismatches)}件")
        for line in mismatches[:20]:
            print(f"  {line}")
        if len(mismatches) > 20:
            print(f"  ...他{len(mismatches) - 20}件")
        return 1

    print("すべてのサンプルで事前集計値と都度クエリの結果が一致しました。")
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None, help="検証対象DB（省略時はsettings.database_url）")
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE, help="検証するEdge件数")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(asyncio.run(main(args.database_url, args.sample_size)))
