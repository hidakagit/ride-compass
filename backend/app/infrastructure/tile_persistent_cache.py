"""Pythonオブジェクトを、呼び出し元が設計したタプルの鍵でディスクへ永続化する汎用キャッシュ
（保持層の選び方・無効化の方針は docs/conventions/caching.md）。

保存の実体は`diskcache`（SQLite＋ファイル）で、32KBを超える値はライブラリがファイルへ、
以下はSQLite内へ格納する。シリアライズはpickle（`diskcache`の既定）——対象はPydantic
モデル・frozen dataclass・numpy配列が混在する構造でJSON化に適さない。

世代・失効は鍵と`expire`で呼び出し側が表す。容量上限を超えればライブラリが古いものから退避する。
"""

import logging
import time
from typing import Any

import diskcache

from app.config import settings
from app.infrastructure.tile_cache import DATA_DIR

logger = logging.getLogger("ridecompass.tile_persistent_cache")

CACHE_DIR = DATA_DIR / "tile_persistent_cache"

_cache: diskcache.Cache | None = None


def cache() -> diskcache.Cache:
    """遅延生成した共有キャッシュ。同じディレクトリを複数プロセスから開いてよい。"""
    global _cache
    if _cache is None:
        _cache = diskcache.Cache(
            str(CACHE_DIR),
            size_limit=settings.tile_persistent_cache_size_limit_mb * 1024 * 1024,
            eviction_policy="least-recently-used",
            tag_index=True,
        )
    return _cache


def use_directory(directory) -> None:
    """キャッシュ先ディレクトリを差し替える（テスト専用）。開いていたキャッシュは閉じる。"""
    global _cache, CACHE_DIR
    if _cache is not None:
        _cache.close()
        _cache = None
    CACHE_DIR = directory


def get_by_key(key: tuple) -> Any | None:
    """任意のタプルキーで読む。キーの設計は呼び出し元が持つ（先頭要素をnamespaceにする）。
    未キャッシュ・破損時はNone。"""
    try:
        started = time.monotonic()
        value = cache().get(key)
        read_ms = (time.monotonic() - started) * 1000
    except Exception:  # noqa: BLE001 破損エントリ・SQLite障害はいずれも未キャッシュ扱いにする
        logger.warning("tile persistent cache read failed key=%r, treating as cache miss", key, exc_info=True)
        return None
    if value is not None:
        logger.debug("tile persistent cache hit key=%r read_ms=%.1f", key, read_ms)
    return value


def set_by_key(key: tuple, value: Any, *, tag: str | None = None, expire: float | None = None) -> None:
    """任意のタプルキーで書く。`expire`（秒）を渡すとその時間で失効する。

    書き込み失敗（ディスクフル・pickle化不能な値等）は握りつぶし、警告ログのみで
    no-opにフォールバックする（キャッシュ書き込みの失敗が応答を止める理由にはならない）。
    """
    try:
        cache().set(key, value, tag=tag, expire=expire)
    except Exception as exc:  # noqa: BLE001 OSError（ディスクフル）・pickle化不能のいずれも吸収する
        logger.warning("tile persistent cache write failed key=%r error=%r", key, exc, exc_info=True)

