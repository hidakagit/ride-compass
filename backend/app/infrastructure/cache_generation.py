"""DBが持つ世代と、ディスクキャッシュを書いた時点の記録を突き合わせる。

キャッシュの無効化には2つの軸がある。**形が変わった**（列構成・焼き込むSQL）は鍵そのものを
変えれば表せる（`cache_identity.py`）。**中身が変わった**（軸定義の編集、バッチによる派生
データの作り直し）はデプロイを伴わずに起きるため鍵では表せず、DB側の単調カウンタと
ディスクへ書いた時点の記録を比べるしかない。本モジュールは後者の比較だけを引き受ける。

比較の対象が何か（軸定義か、派生データか）と、食い違ったとき何を捨てるかは呼び出し側が
決める。ここが持つのは「一致なら温存・不一致なら捨てて記録し直す・読めなければ安全側へ倒す」
という判断だけである。
"""

import logging
from collections.abc import Callable

from app.infrastructure import tile_persistent_cache

logger = logging.getLogger("ridecompass.cache_generation")

# 記録を置く予約タイル座標。実タイルのzoomは常にROAD_GRAPH_TILE_ZOOM（12）のため衝突しない。
_REVISION_MARKER_TILE = (-1, 0, 0)


def sync_with_revision(
    namespace: str, version: str, revision: int | None, clear: Callable[[], None]
) -> bool:
    """`revision`がディスクへ最後に書いた時点の記録と食い違っていれば`clear`を呼ぶ。

    捨てたときTrueを返す（呼び出し側が、そこから作られる他のキャッシュも一緒に捨てるため）。
    `revision`がNone——記録の行が無い等の想定外——のときは常に捨てる。**記録し直さない**ので、
    次回も同じ安全側の判定になる。
    """
    zoom, x, y = _REVISION_MARKER_TILE
    if revision is not None and tile_persistent_cache.get(namespace, version, zoom, x, y) == revision:
        return False
    clear()
    if revision is not None:
        tile_persistent_cache.set(namespace, version, zoom, x, y, revision)
    return True


def read_persisted_revision(namespace: str, version: str) -> int | None:
    """ディスクへ最後に書いた時点の記録（テスト・診断用）。"""
    zoom, x, y = _REVISION_MARKER_TILE
    return tile_persistent_cache.get(namespace, version, zoom, x, y)
