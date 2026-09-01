"""改善計画T538のサニティチェック用ベンチマーク: 実DB（dev機）に対して`GraphService.
get_search_materials_for_bbox`を複数回呼び、ディスク永続化キャッシュ
（`infrastructure/tile_persistent_cache.py`）経由の読み込みが、プロセス内メモリLRUを
空にした状態（デプロイでコンテナが再起動した直後を模す）でもDB読み出しより有意に速い
ことを実測する。

`bench_t537_prepare_cache.py`と同様、実DB接続が必須（`DATABASE_URL`、backend/.env）。

計測の流れ:
  1. 両キャッシュ（メモリ・ディスク）を空にした状態で1回目を呼ぶ（真の冷パス、DB読み出し）。
  2. メモリLRUだけを空にする（`graph_material_cache._tile_materials_cache.clear()`・
     `tile_score_matrix_cache._cache.clear()`、プロセス再起動を模す）。ディスクキャッシュは
     1回目の呼び出しで書き込まれたまま残る。
  3. 2回目を呼ぶ（ディスク永続化キャッシュ経由、DB読み出しなし）。1回目との所要時間を比較する。
  4. 参考として、メモリがヒットする3回目（真の温パス）も計測する。

使い方: `python -m benchmarks.bench_t538_persistent_cache`
"""

from __future__ import annotations

import asyncio
import time

from app.domain.region import BoundingBox
from app.infrastructure import graph_material_cache, tile_score_matrix_cache
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.infrastructure.database import get_route_generation_session_factory, get_session_factory
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.axis_registry_service import refresh_axis_definitions
from app.services.graph_service import GraphService

# 東京駅相当、T536/T537ベンチマークと同じ規模感になるよう半径10km相当のbboxを直接指定する
# （経緯度でおおよそ±0.09度、道路密度の高い都心部）。
BBOX = BoundingBox(
    min_latitude=35.60, min_longitude=139.68,
    max_latitude=35.76, max_longitude=139.86,
)


async def _run_once(label: str) -> float:
    async with get_route_generation_session_factory()() as session:
        service = GraphService(repository=RoadGraphRepository(session))
        started = time.monotonic()
        built = await service.get_search_materials_for_bbox(BBOX)
        elapsed_ms = (time.monotonic() - started) * 1000
        edge_count = len(built[0].graph.edges) if built else 0
        print(f"=== {label}: elapsed_ms={elapsed_ms:.1f} edges={edge_count} ok={built is not None} ===")
        return elapsed_ms


async def main() -> None:
    print(f"bbox={BBOX} (T538サニティチェック: tile_persistent_cache)")

    async with get_session_factory()() as axis_session:
        await refresh_axis_definitions(AxisDefinitionRepository(axis_session))

    graph_material_cache.clear()
    tile_score_matrix_cache.clear()
    cold_ms = await _run_once("1回目(真の冷パス、メモリ・ディスクとも空、DB読み出し)")

    # プロセス再起動を模す: メモリLRUだけを空にする（ディスクは温存）。
    graph_material_cache._tile_materials_cache.clear()
    tile_score_matrix_cache._cache.clear()
    disk_ms = await _run_once("2回目(メモリのみ再起動を模す、ディスク永続化キャッシュ経由)")

    warm_ms = await _run_once("3回目(真の温パス、メモリLRUヒット)")

    print()
    print(f"cold(DB)_ms={cold_ms:.1f}  disk_cache_ms={disk_ms:.1f}  warm_memory_ms={warm_ms:.1f}")
    if disk_ms > 0:
        print(f"ディスクキャッシュはDB読み出しの約{cold_ms / disk_ms:.1f}倍高速")


if __name__ == "__main__":
    asyncio.run(main())
