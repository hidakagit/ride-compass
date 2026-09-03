"""派生データ再構築の単一エントリポイント（改善計画T281段階2）。

[docs/batch-pipeline-dependencies.md](../../../docs/batch-pipeline-dependencies.md)の
④〜⑨（road_edges起点・osm_raw_ways起点の派生計算バッチ）を、依存順序どおり1コマンドへ
まとめる。①〜③（import_pbf/import_accidents/import_designations、生データ取込）は対象外
——個別のファイル・年次・kind指定を要する生データ取込そのものであり、「派生データの
再構築」ではないため。

実行順序（依存DAGどおり）: ④presplit_road_graph→⑤precompute_road_node_degrees→
⑥precompute_edge_attribute_counts→⑦precompute_elevation_attributes→
⑧precompute_way_attribute_counts→⑨match_designations。いずれか1段が例外を送出したら
即座に停止し後続を実行しない（各バッチは低頻度・人が監視して実行する運用のため、部分的に
古いデータのまま後続段を進めるより、失敗にすぐ気づける方を優先する）。

各段は既存バッチの`run`/`run_match`関数をそのまま呼ぶだけで、新しいロジックは持たない
（本バッチ自体は複数コマンドを畳む薄いオーケストレーションのみ）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.refresh_derived
    .venv\\Scripts\\python.exe -m app.batch.refresh_derived --database-url ...
    --dry-runで全段をdry-runモードで実行（DB書き込みなし）
"""

import argparse
import asyncio
import logging
import sys
import time
from types import ModuleType

from app.batch import (
    match_designations,
    precompute_edge_attribute_counts,
    precompute_elevation_attributes,
    precompute_road_node_degrees,
    precompute_way_attribute_counts,
    presplit_road_graph,
)

logger = logging.getLogger("app.batch.refresh_derived")

# (ラベル, モジュール, 呼び出す関数名)。モジュール＋関数名の文字列で持ち実行時に
# getattrする（モジュールロード時に関数オブジェクトを直接束ねると、テストが
# monkeypatch.setattr(module, "run", ...)しても本バッチが最初に束ねた古い参照を
# 使い続けてしまい、モックが効かず実DBへ接続してしまうため）。match_designations
# だけ他バッチと関数名が異なる（`run_match`）。
_STAGES: list[tuple[str, ModuleType, str]] = [
    ("④presplit_road_graph", presplit_road_graph, "run"),
    ("⑤precompute_road_node_degrees", precompute_road_node_degrees, "run"),
    ("⑥precompute_edge_attribute_counts", precompute_edge_attribute_counts, "run"),
    ("⑦precompute_elevation_attributes", precompute_elevation_attributes, "run"),
    ("⑧precompute_way_attribute_counts", precompute_way_attribute_counts, "run"),
    ("⑨match_designations", match_designations, "run_match"),
]


async def run(database_url: str | None, dry_run: bool) -> int:
    started = time.perf_counter()
    logger.info("派生データ再構築を開始します stages=%d dry_run=%s", len(_STAGES), dry_run)
    for label, module, attr_name in _STAGES:
        stage_started = time.perf_counter()
        logger.info("段階開始: %s", label)
        await getattr(module, attr_name)(database_url, dry_run)
        logger.info("段階完了: %s elapsed=%.1fs", label, time.perf_counter() - stage_started)
    logger.info("派生データ再構築が完了しました elapsed=%.1fs", time.perf_counter() - started)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="派生データ再構築の単一エントリポイント（改善計画T281段階2）"
    )
    parser.add_argument("--database-url", default=None, help="対象DB（省略時はsettings.database_url）")
    parser.add_argument("--dry-run", action="store_true", help="全段をdry-runモードで実行しDBへ書き込まない")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(run(args.database_url, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
