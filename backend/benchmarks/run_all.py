"""全ベンチマークをまとめて実行する（backend/から`.venv/Scripts/python -m benchmarks.run_all`）。

各`bench_*.py`モジュールは単体でも`python -m benchmarks.bench_xxx`として実行できる
（個別モジュールのdocstring参照）。標高キャッシュ・Road Graph構築系は合成データでも
規模次第で数秒〜十数秒かかるため、時間を絞りたい場合は個別モジュールを直接実行すること。

計測対象が構造的に無くなったベンチマークはこの一覧から外す（モジュール自体も残さない）。
"""

from __future__ import annotations

import time

from benchmarks._harness import print_report
from benchmarks._revision import require_current_revision
from benchmarks import (
    bench_evaluate_graph,
    bench_graph_build,
    bench_nearest_node,
    bench_route_trace,
)


def main() -> None:
    # どのコードを測ったかを数字と同じ出力に残し、作業コピーが配信元と違えばここで止める
    # （_revision.py参照）。個別の`bench_*`モジュールは手元での反復用のため呼ばない。
    require_current_revision()
    started = time.perf_counter()

    print_report("1/4 find_nearest_node_indexed: grid bucket index scaling", bench_nearest_node.run())
    print_report("2/4 build_road_graph: construction scaling", bench_graph_build.run())
    print_report(
        "3/4 RoadGraphEngine trace phase: nearest-node + Dijkstra x 8 bearings", bench_route_trace.run()
    )
    print_report("4/4 evaluation_service.evaluate_graph: car_stress判定ホットパス", bench_evaluate_graph.run())

    print(f"\nTotal wall time: {time.perf_counter() - started:.1f} s")


if __name__ == "__main__":
    main()
