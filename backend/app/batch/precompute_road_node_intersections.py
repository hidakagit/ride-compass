"""road_nodesの交差点属性（信号の有無・集まる道の最大階級）の事前集計バッチ。

ターンの費用（`domain/routing.py: build_turn_expanded_structure`）は「進入した道より上位の
道と交わる交差点」で追加の秒数を足す。信号での待ちは停止密度の材料が走行モデルへ運ぶため
（`domain/traffic.py: stop_count_material_ids`）、ターン側が足すべきなのは**信号が無いのに
上位の道を渡る・そこへ入る**ときの待ちだけである。それを表すには交差点ノード単位で信号の
有無が要る（Edgeへ畳み込むと、どちらの端の信号かが失われる）。

実際の集計SQLは`road_graph_repository.py`の`DerivedGraphRepository`側にあり、
ここからはファサード（`RoadGraphRepository`のフラットな契約）経由で呼ぶ
（`recompute_node_max_highway_rank`・`recompute_node_traffic_signals`）。本バッチは
そのメソッドを呼ぶだけで新しいSQLを持たない（既存の各precomputeバッチと同じ規約）。

最大階級はroad_edgesだけを見る単一UPDATEで、`precompute_road_node_degrees.py`と同じく
チャンク分割は要らない。信号の有無は半径での空間結合のため、
`precompute_edge_attribute_counts.py`と同じくノードをチャンクへ分けて処理する。

migration 0041適用後、本番でも初回実行が必須。`road_edges`・`osm_raw_pois`のいずれかが
変わった場合（PBF再取込等）は再実行が必要。未実行のあいだは
`has_traffic_signals=false`・`max_highway_rank=0`で、どちらもターンの費用が本バッチ導入前と
同じ結果になる側の既定値である。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.precompute_road_node_intersections
    .venv\\Scripts\\python.exe -m app.batch.precompute_road_node_intersections --database-url ...
    --dry-runで対象件数のログのみ（DB書き込みなし）
"""

import logging
import sys
import time

from sqlalchemy import select

from app.batch._common import batch_session_factory, run_chunked_precompute, run_simple_batch_cli
from app.infrastructure.road_graph_models import RoadNodeRow
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("ridecompass.precompute_road_node_intersections")

# 1チャンクあたりのnode数。信号の有無は`ST_DWithin`の空間結合で、
# `precompute_edge_attribute_counts.py`と同じくプランが全組み合わせ評価へ落ちるのを避ける
# ために分ける。ノードはEdgeより軽い（点×点の半径判定）ためチャンクは大きめに取る。
CHUNK_SIZE = 20_000


async def run(database_url: str | None, dry_run: bool) -> int:
    started = time.perf_counter()
    async with batch_session_factory(database_url) as session_factory:
        if not dry_run:
            async with session_factory() as session:
                await RoadGraphRepository(session).recompute_node_max_highway_rank()
                await session.commit()
            logger.info("max_highway_rank更新完了: elapsed=%.1fs", time.perf_counter() - started)

        async def handle_chunk(node_ids: list[str]) -> int:
            async with session_factory() as session:
                await RoadGraphRepository(session).recompute_node_traffic_signals(node_ids)
                await session.commit()
            return len(node_ids)

        code = await run_chunked_precompute(
            session_factory,
            select(RoadNodeRow.node_id),
            CHUNK_SIZE,
            handle_chunk,
            logger=logger,
            target_label="対象road_nodes",
            empty_warning="road_nodesが0件のため更新をスキップします",
            dry_run=dry_run,
        )
    logger.info("交差点属性の事前集計完了: elapsed=%.1fs", time.perf_counter() - started)
    return code


def main(argv: list[str] | None = None) -> int:
    return run_simple_batch_cli(argv, description="road_nodesの交差点属性 事前集計バッチ", run_fn=run)


if __name__ == "__main__":
    sys.exit(main())
