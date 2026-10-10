"""取得・生成したタイル・フォント等の生バイトを、配信パスを鍵にディスクへ置く
（保持層の選び方・容量の持ち方は .claude/rules/caching.md）。

保存の実体は`diskcache`で、容量上限を超えればライブラリが書き込みのついでに退避する。
"""

from collections.abc import Callable

import diskcache

from app.config import settings
from app.infrastructure.data_paths import DATA_DIR
from app.infrastructure.debug_log import log_throttled_warning

CACHE_DIR = DATA_DIR / "tile_cache"

_CATEGORY = "cache:tile-disk"

_opened_cache: diskcache.Cache | None = None


def _opened() -> diskcache.Cache:
    """遅延生成した共有キャッシュ。スレッド（`asyncio.to_thread`）から同時に呼んでよい。"""
    global _opened_cache
    if _opened_cache is None:
        _opened_cache = diskcache.Cache(
            str(CACHE_DIR),
            size_limit=settings.tile_cache_size_limit_mb * 1024 * 1024,
            # 退避の順は書いた順にする。読んだ順（least-recently-used）は読むたびに書き込みが走り、
            # 地図の読み込みで同時に来る数十件のタイル要求がそのぶん重くなる。
            eviction_policy="least-recently-stored",
        )
    return _opened_cache


def get(path: str) -> tuple[bytes, str] | None:
    """キャッシュ済みなら(内容, Content-Type)を返す。未キャッシュ・読めないときはNone（呼び出し元が取り直す）。"""
    try:
        return _opened().get(path)
    except Exception as exc:  # noqa: BLE001 ディスク・SQLiteの障害と壊れた項目は、いずれも未キャッシュ扱いにする
        log_throttled_warning(_CATEGORY, "tile cache read failed for path=%s, treating as cache miss error=%r", path, exc)
        return None


def set(path: str, content: bytes, content_type: str) -> None:
    """書き込みの失敗（ディスクフル等）は警告だけにする——キャッシュに書けないことが配信を止める理由にはならない。"""
    try:
        _opened().set(path, (content, content_type))
    except Exception as exc:  # noqa: BLE001 ディスクフル・権限・SQLiteの障害のいずれも吸収する
        log_throttled_warning(_CATEGORY, "tile cache write failed for path=%s (disk full/permission?) error=%r", path, exc)


def delete_where(is_stale: Callable[[str], bool]) -> int:
    """`is_stale`が真を返す鍵を消し、消した数を返す。容量の上限とは別に、世代交代で読まれなくなった実体を消す口。

    鍵を全部読み終えてから消す（読みながら消すと、読み進める位置が消した分だけずれる）。
    失敗は警告だけにする——消せなければ容量の上限が退避するまで残るだけで、配信は止めない。
    """
    try:
        cache = _opened()
        stale = [key for key in cache.iterkeys() if is_stale(key)]
        return sum(1 for key in stale if cache.delete(key))
    except Exception as exc:  # noqa: BLE001 ディスク・SQLiteの障害は、消さずに残すことへ倒す
        log_throttled_warning(_CATEGORY, "tile cache prune failed, stale entries are kept error=%r", exc)
        return 0


def clear_all() -> None:
    _opened().clear()


def close() -> None:
    """開いたキャッシュを閉じる（プロセスの終わりに`process_resources.py`が呼ぶ）。次の読み書きで開き直す。"""
    global _opened_cache
    if _opened_cache is not None:
        _opened_cache.close()
        _opened_cache = None
