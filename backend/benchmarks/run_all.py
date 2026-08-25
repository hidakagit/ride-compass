"""全ベンチマークをまとめて実行する（backend/から`.venv/Scripts/python -m benchmarks.run_all`）。

各`bench_*.py`モジュールは単体でも`python -m benchmarks.bench_xxx`として実行できる
（個別モジュールのdocstring参照）。標高キャッシュ・Road Graph構築系は合成データでも
規模次第で数秒〜十数秒かかるため、時間を絞りたい場合は個別モジュールを直接実行すること。

改善計画T22でOverpassフォールバックを撤去し、地域路面レイヤーのPython側MVTエンコード
（`encode_road_surface_tile`のway数スケーリング）が構造的に無くなったため、それを計測していた
`bench_vector_tile`・`bench_event_loop_stall`はこの一覧から削除した（2026-08-16）。

改善計画T10（DEMタイル化＋標高キャッシュ1系統化）でGSI点API＋SQLite点キャッシュ
（`infrastructure/cache_db.py`のelevation_cacheテーブル・get_elevation/set_elevation）を
廃止したため、それを計測していた`bench_elevation_cache`もこの一覧から削除した
（2026-08-23。新方式のタイルキャッシュ自体は`tests/test_elevation_client_cache.py`で
機能面を検証済み。パフォーマンス計測が必要になった際は新規ベンチマークとして書き直す）。
"""

from __future__ import annotations

import time

from benchmarks._harness import print_report
from benchmarks import (
    bench_evaluate_graph,
    bench_graph_build,
    bench_nearest_node,
    bench_route_trace,
)


def main() -> None:
    started = time.perf_counter()

    print_report("1/4 find_nearest_node_indexed: grid bucket index scaling", bench_nearest_node.run())
    print_report("2/4 build_road_graph: construction scaling", bench_graph_build.run())
    print_report(
        "3/4 RoadGraphEngine trace phase: nearest-node + Dijkstra x 8 bearings", bench_route_trace.run()
    )
    print_report("4/4 EvaluationService.evaluate_graph: car_stress判定ホットパス", bench_evaluate_graph.run())

    print(f"\nTotal wall time: {time.perf_counter() - started:.1f} s")


if __name__ == "__main__":
    main()
