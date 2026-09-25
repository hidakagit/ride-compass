"""探索範囲ごとに学習した迂回率（道なり距離÷直線距離）のプロセス内キャッシュ。

往路木を求めるたびに実測の中央値を学習し、同じ範囲の次のリクエストが通過予定時刻の見積もりに使う
（`RoadGraphEngine`の`_learn_detour_ratio`）。鍵は探索範囲を覆うz12タイル集合で、値は実数1つ。
失っても既定値（`ROUTE_DETOUR_RATIO`）へ戻るだけのため、プロセス寿命とLRUだけで持つ。
"""

from cachetools import LRUCache

TileSet = frozenset[tuple[int, int, int]]

MAX_ENTRIES = 64

_detour_ratios: LRUCache = LRUCache(maxsize=MAX_ENTRIES)


def get_detour_ratio(tile_set: TileSet) -> float | None:
    return _detour_ratios.get(tile_set)


def set_detour_ratio(tile_set: TileSet, ratio: float) -> None:
    _detour_ratios[tile_set] = ratio
