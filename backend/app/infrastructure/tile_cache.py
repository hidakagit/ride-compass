import hashlib
import shutil

from app.infrastructure.cache_db import DATA_DIR

CACHE_DIR = DATA_DIR / "tile_cache"


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
    if not content_file.is_file():
        return None
    meta_file = CACHE_DIR / f"{key}.meta"
    content_type = meta_file.read_text(encoding="utf-8") if meta_file.is_file() else "application/octet-stream"
    return content_file.read_bytes(), content_type


def set(path: str, content: bytes, content_type: str) -> None:
    key = _cache_key(path)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.bin").write_bytes(content)
    (CACHE_DIR / f"{key}.meta").write_text(content_type, encoding="utf-8")


def clear_all() -> None:
    shutil.rmtree(CACHE_DIR, ignore_errors=True)
