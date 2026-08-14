"""`RegionService.get_road_surface_tile`がイベントループをどれだけ止めるかを実測する。

修正前は`tile_cache.get/set`（ディスクI/O）を`asyncio.to_thread`でラップしているのに、
CPU専用の`encode_road_surface_tile`（MVTエンコード）だけラップせずそのまま`await`無しで
同期呼び出ししていた。この関数はコルーチンではないため、実行中はイベントループ上の
他の全てのタスク（同時に処理中の別リクエストのルート生成・標高取得の`await`再開等）が
完全に止まっていた。`region_service.py`側で`await asyncio.to_thread(encode_road_surface_tile, ...)`
に変更済み（修正後）。

「他のタスクがどれだけ足止めされるか」を、一定間隔で`asyncio.sleep(0)`するだけの
心拍コルーチンを並行実行し、その心拍の間隔（本来はほぼ即時に戻るはず）の最大値として
実測する。(1)(2)は`encode_road_surface_tile`単体での修正前後比較、(3)は実際の
`RegionService.get_road_surface_tile`（修正後のコード）をOverpass/tile_cacheをスタブ化して
end-to-endで計測し、(2)相当の改善が本番コード側でも効いていることを確認する。
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from benchmarks._harness import BenchmarkResult, print_report
from benchmarks._synthetic import synthetic_road_surface_ways

WAY_COUNT_FOR_STALL_DEMO = 3000  # 密な市街地タイルを想定したway数


async def _heartbeat_max_gap(during: "asyncio.Future") -> float:
    max_gap = 0.0
    last = time.perf_counter()
    while not during.done():
        await asyncio.sleep(0)
        now = time.perf_counter()
        max_gap = max(max_gap, now - last)
        last = now
    return max_gap


async def _measure_stall(label: str, blocking_coro) -> BenchmarkResult:
    task = asyncio.ensure_future(blocking_coro())
    max_gap = await _heartbeat_max_gap(task)
    await task
    return BenchmarkResult(name=label, n=1, samples_s=[max_gap])


def _raw_overpass_ways(count: int) -> list[dict]:
    """OverpassClient.get_roadsが返す生の形（{"tags", "coordinates"}）の合成way一覧。"""
    ways = []
    for way in synthetic_road_surface_ways(count):
        ways.append({"tags": {} if way["surface_good"] else {"surface": "unpaved"}, "coordinates": way["coordinates"]})
    return ways


def run() -> list[BenchmarkResult]:
    from app.infrastructure.vector_tile import encode_road_surface_tile

    ways = synthetic_road_surface_ways(WAY_COUNT_FOR_STALL_DEMO)

    async def call_directly():
        # 修正前の呼び方（awaitでラップしていない、同期関数をそのままイベントループの
        # コルーチン内で実行する）。
        encode_road_surface_tile(14, 14552, 6451, ways)

    async def call_in_thread():
        # 修正後と同じパターン（asyncio.to_threadでラップ、tile_cache.get/setと揃える）。
        await asyncio.to_thread(encode_road_surface_tile, 14, 14552, 6451, ways)

    async def call_region_service():
        # 実際の修正後コード（region_service.py）をend-to-endで計測する。
        # Overpass/tile_cacheは外部依存のためスタブ化し、MVTエンコード部分のみ実データに揃える。
        from app.infrastructure import tile_cache
        from app.services.region_service import RegionService

        class FakeOverpassClient:
            async def get_roads(self, client, bbox):
                return _raw_overpass_ways(WAY_COUNT_FOR_STALL_DEMO)

        original_cache_dir = tile_cache.CACHE_DIR
        tile_cache.CACHE_DIR = Path(tempfile.mkdtemp(prefix="ridecompass_bench_tile_"))
        try:
            service = RegionService(FakeOverpassClient(), http_client=None)
            await service.get_road_surface_tile(14, 14552, 6451)
        finally:
            tile_cache.CACHE_DIR = original_cache_dir

    async def _run_all() -> list[BenchmarkResult]:
        direct = await _measure_stall(
            f"before fix: encode_road_surface_tile called directly (ways={WAY_COUNT_FOR_STALL_DEMO}) "
            f"- max event-loop heartbeat gap",
            call_directly,
        )
        threaded = await _measure_stall(
            f"after fix: same encode via asyncio.to_thread (ways={WAY_COUNT_FOR_STALL_DEMO}) "
            f"- max event-loop heartbeat gap",
            call_in_thread,
        )
        service_level = await _measure_stall(
            f"after fix: RegionService.get_road_surface_tile end-to-end (ways={WAY_COUNT_FOR_STALL_DEMO}, "
            f"Overpass/tile_cache stubbed) - max event-loop heartbeat gap",
            call_region_service,
        )
        return [direct, threaded, service_level]

    return asyncio.run(_run_all())


if __name__ == "__main__":
    print_report("Event-loop stall caused by synchronous MVT encoding in an async request handler", run())
