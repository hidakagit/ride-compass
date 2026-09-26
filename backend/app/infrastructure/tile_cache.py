"""取得・生成したタイル・フォント等の生バイトを、配信パスを鍵にディスクへ置く
（保持層の選び方・容量の持ち方は docs/conventions/caching.md）。

保存の実体は`diskcache`で、容量上限を超えればライブラリが書き込みのついでに退避する。
"""

import logging
from pathlib import Path

import diskcache

from app.config import settings

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
CACHE_DIR = DATA_DIR / "tile_cache"

logger = logging.getLogger("ridecompass.tile_cache")

_cache: diskcache.Cache | None = None


def _opened() -> diskcache.Cache:
    """遅延生成した共有キャッシュ。スレッド（`asyncio.to_thread`）から同時に呼んでよい。"""
    global _cache
    if _cache is None:
        _cache = diskcache.Cache(
            str(CACHE_DIR),
            size_limit=settings.tile_cache_size_limit_mb * 1024 * 1024,
            # 退避の順は書いた順にする。読んだ順（least-recently-used）は読むたびに書き込みが走り、
            # 地図の読み込みで同時に来る数十件のタイル要求がそのぶん重くなる。
            eviction_policy="least-recently-stored",
        )
    return _cache


def get(path: str) -> tuple[bytes, str] | None:
    """キャッシュ済みなら(内容, Content-Type)を返す。未キャッシュ・読めないときはNone（呼び出し元が取り直す）。"""
    try:
        return _opened().get(path)
    except Exception:  # noqa: BLE001 ディスク・SQLiteの障害と壊れた項目は、いずれも未キャッシュ扱いにする
        logger.warning("tile cache read failed for path=%s, treating as cache miss", path, exc_info=True)
        return None


def set(path: str, content: bytes, content_type: str) -> None:
    """書き込みの失敗（ディスクフル等）は警告だけにする——キャッシュに書けないことが配信を止める理由にはならない。"""
    try:
        _opened().set(path, (content, content_type))
    except Exception:  # noqa: BLE001 ディスクフル・権限・SQLiteの障害のいずれも吸収する
        logger.warning("tile cache write failed for path=%s (disk full/permission?)", path, exc_info=True)


def clear_all() -> None:
    _opened().clear()
