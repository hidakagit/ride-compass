"""DBが持つ世代と、ディスクキャッシュを書いた時点の記録を突き合わせる
（無効化の方針は docs/conventions/caching.md）。

比較の対象が何か（軸定義か、派生データか）と、食い違ったとき何を捨てるかは呼び出し側が
決める。
"""

import logging
from collections.abc import Callable

from app.infrastructure import tile_persistent_cache

logger = logging.getLogger("ridecompass.cache_generation")

# 記録を置く予約タイル座標。実タイルのzoomは常にROAD_GRAPH_TILE_ZOOM（12）のため衝突しない。
_REVISION_MARKER_TILE = (-1, 0, 0)


#: 世代を読めなかったことの記録。実際の世代（int）とは別の型にして取り違えを防ぐ。
_UNKNOWN_REVISION_MARK = "unknown"


def sync_with_revision(
    namespace: str, version: str, revision: int | None, clear: Callable[[], None]
) -> bool:
    """`revision`がディスクへ最後に書いた時点の記録と食い違っていれば`clear`を呼ぶ。

    捨てたときTrueを返す（呼び出し側が、そこから作られる他のキャッシュも一緒に捨てるため）。

    `revision`がNone——記録の行が無い等の想定外——のときも一度は捨てる（安全側）。ただし
    **「読めなかった」ことを記録する**ため、状態が変わらない限り2度目は捨てない。記録しないと
    確認のたびに全消去が走り、確認の発火点が増えるほど消える頻度が上がる。
    """
    zoom, x, y = _REVISION_MARKER_TILE
    current = revision if revision is not None else _UNKNOWN_REVISION_MARK
    if tile_persistent_cache.get(namespace, version, zoom, x, y) == current:
        return False
    clear()
    tile_persistent_cache.set(namespace, version, zoom, x, y, current)
    return True


def read_persisted_revision(namespace: str, version: str) -> int | None:
    """ディスクへ最後に書いた時点の記録（テスト・診断用）。"""
    zoom, x, y = _REVISION_MARKER_TILE
    return tile_persistent_cache.get(namespace, version, zoom, x, y)
