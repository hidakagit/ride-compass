"""派生データ再構築の単一エントリポイント。

[docs/batch-pipeline-dependencies.md](../../../docs/batch-pipeline-dependencies.md)の
④〜⑩（road_edges起点・osm_raw_ways起点の派生計算バッチ）を、依存順序どおり1コマンドへ
まとめる。①〜③（import_pbf/import_accidents/import_designations、生データ取込）は対象外
——個別のファイル・年次・kind指定を要する生データ取込そのものであり、「派生データの
再構築」ではないため。

実行順序（依存DAGどおり）: ④presplit_road_graph→⑤precompute_road_node_degrees→
⑥precompute_edge_attribute_counts→⑦precompute_elevation_attributes→
⑧precompute_way_attribute_counts→⑨match_designations→⑩precompute_way_landcover。
いずれか1段が例外を送出したら即座に停止し後続を実行しない（各バッチは低頻度・人が
監視して実行する運用のため、部分的に古いデータのまま後続段を進めるより、失敗にすぐ
気づける方を優先する）。

各段は既存バッチの`run`/`run_match`関数をそのまま呼ぶだけで、新しいロジックは持たない
（本バッチ自体は複数コマンドを畳む薄いオーケストレーションのみ）。⑩precompute_way_
landcoverだけラスタファイル（`settings.lulc_raster_paths`、リポジトリにコミットしない
手動取得データ）を要するため、未設定の環境では`--skip-landcover`で明示的にこの段だけ
スキップできる（他の段と違い「ラスタを用意していないだけ」であり派生データの実際の
障害ではないため、スキップ自体はWARNINGに留め処理は続行する）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.refresh_derived
    .venv\\Scripts\\python.exe -m app.batch.refresh_derived --database-url ...
    --dry-runで全段をdry-runモードで実行（DB書き込みなし）
    --skip-landcoverでラスタ未整備環境向けに⑩だけスキップ
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
    precompute_way_landcover,
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
    ("⑩precompute_way_landcover", precompute_way_landcover, "run_default"),
]


async def run(database_url: str | None, dry_run: bool, skip_landcover: bool = False) -> int:
    started = time.perf_counter()
    logger.info("派生データ再構築を開始します stages=%d dry_run=%s", len(_STAGES), dry_run)
    for label, module, attr_name in _STAGES:
        if skip_landcover and module is precompute_way_landcover:
            logger.warning("段階スキップ: %s（--skip-landcover指定）", label)
            continue
        stage_started = time.perf_counter()
        logger.info("段階開始: %s", label)
        await getattr(module, attr_name)(database_url, dry_run)
        logger.info("段階完了: %s elapsed=%.1fs", label, time.perf_counter() - stage_started)
    logger.info("派生データ再構築が完了しました elapsed=%.1fs", time.perf_counter() - started)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="派生データ再構築の単一エントリポイント"
    )
    parser.add_argument("--database-url", default=None, help="対象DB（省略時はsettings.database_url）")
    parser.add_argument("--dry-run", action="store_true", help="全段をdry-runモードで実行しDBへ書き込まない")
    parser.add_argument(
        "--skip-landcover", action="store_true", help="ラスタ未整備の環境向けに⑩precompute_way_landcoverだけスキップする"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(run(args.database_url, args.dry_run, args.skip_landcover))


if __name__ == "__main__":
    sys.exit(main())
