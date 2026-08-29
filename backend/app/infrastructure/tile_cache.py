import hashlib
import logging
import shutil
from pathlib import Path

# 改善計画T398でcache_db.py（SQLite永続キャッシュ）を撤去した際、唯一の非SQLite用途
# だったDATA_DIRの定義をここへ移設した（地図タイル・路面ベクタタイルのファイルキャッシュは
# 元々SQLiteとは無関係で、DATA_DIRという保存先ディレクトリの定数だけを間借りしていた）。
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
CACHE_DIR = DATA_DIR / "tile_cache"

logger = logging.getLogger("app.infrastructure.tile_cache")


def _cache_key(path: str) -> str:
    """`path`をフラットなファイル名にハッシュ化する。

    OpenFreeMapのURL構造には`planet`（TileJSON本体）と`planet/<version>/{z}/{x}/{y}.pbf`
    （実タイル）のように、同じセグメントがファイルとディレクトリ接頭辞の両方として使われる
    ケースがある。パスをそのままディレクトリ階層にミラーリングすると、Windowsでは
    「同名のファイルがあるためディレクトリを作成できない」というエラーで実際にクラッシュした
    （実機確認で発見）。ハッシュ化してフラットに保存することでこの衝突を構造的に避ける。
    ディレクトリトラバーサル（`..`等）も、パスがファイル名に使われないため問題にならない。
    """
    return hashlib.sha256(path.encode("utf-8")).hexdigest()


def get(path: str) -> tuple[bytes, str] | None:
    """キャッシュ済みなら(内容, Content-Type)を返す。未キャッシュならNone。"""
    key = _cache_key(path)
    content_file = CACHE_DIR / f"{key}.bin"
    try:
        if not content_file.is_file():
            return None
        meta_file = CACHE_DIR / f"{key}.meta"
        content_type = meta_file.read_text(encoding="utf-8") if meta_file.is_file() else "application/octet-stream"
        return content_file.read_bytes(), content_type
    except OSError:
        # is_file()確認とread_bytes()の間にclear_all()（rmtree）と競合すると
        # FileNotFoundError等が起きうる。未キャッシュ扱いにフォールバックし、
        # 呼び出し元に再取得させる。
        logger.warning("tile cache read failed for path=%s, treating as cache miss", path, exc_info=True)
        return None


def set(path: str, content: bytes, content_type: str) -> None:
    # キャッシュ書き込みはあくまで高速化目的で、呼び出し元は取得済みのcontentを既に
    # 返せる状態にある。ディスクフル・権限エラー等（OSError）でここが失敗しても、
    # basemap/road-surfaceタイルの配信自体を丸ごと500にする理由にはならないため、
    # 天候キャッシュ（wind_forecast_cache.py）と同じ「キャッシュ書き込み失敗は握りつぶす」
    # 方針に合わせ、警告ログのみでno-opにフォールバックする。
    try:
        key = _cache_key(path)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{key}.bin").write_bytes(content)
        (CACHE_DIR / f"{key}.meta").write_text(content_type, encoding="utf-8")
    except OSError:
        logger.warning("tile cache write failed for path=%s (disk full/permission?)", path, exc_info=True)


def clear_all() -> None:
    shutil.rmtree(CACHE_DIR, ignore_errors=True)
