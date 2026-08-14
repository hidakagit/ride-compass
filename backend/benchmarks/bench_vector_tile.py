"""`infrastructure/vector_tile.py: encode_road_surface_tile`（MVTエンコード）の計測。

CPU専用の同期関数で、`RegionService.get_road_surface_tile`から`await`無しで直接
呼ばれている（同ファイルの`tile_cache.get/set`は`asyncio.to_thread`でラップされているのに
対し、このエンコード処理はラップされていない）。way数（Overpassからそのタイルに
返ってきた道路の本数）に対するスケールと、他の同時進行中のリクエスト（ルート生成の
`asyncio.gather`等）がその間どれだけ足止めされるかは`bench_event_loop_stall.py`で扱う。
"""

from __future__ import annotations

from benchmarks._harness import BenchmarkResult, measure, print_report
from benchmarks._synthetic import synthetic_road_surface_ways

WAY_COUNTS = [50, 200, 800, 3000]


def run() -> list[BenchmarkResult]:
    from app.infrastructure.vector_tile import encode_road_surface_tile

    results: list[BenchmarkResult] = []
    for count in WAY_COUNTS:
        ways = synthetic_road_surface_ways(count)
        result = measure(
            f"encode_road_surface_tile (ways={count})",
            lambda w=ways: encode_road_surface_tile(14, 14552, 6451, w),
            repeat=15,
        )
        results.append(result)

    return results


if __name__ == "__main__":
    print_report("encode_road_surface_tile (MVT encoding): way-count scaling", run())
