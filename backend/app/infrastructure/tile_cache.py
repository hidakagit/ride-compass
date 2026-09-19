import hashlib
import logging
import os
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
CACHE_DIR = DATA_DIR / "tile_cache"

logger = logging.getLogger("ridecompass.tile_cache")


def cache_key(path: str) -> str:
    """`path`をフラットなファイル名にハッシュ化する。

    OpenFreeMapのURL構造には`planet`（TileJSON本体）と`planet/<version>/{z}/{x}/{y}.pbf`
    （実タイル）のように、同じセグメントがファイルとディレクトリ接頭辞の両方として使われる
    ケースがある。パスをそのままディレクトリ階層にミラーリングすると、Windowsでは
    「同名のファイルがあるためディレクトリを作成できない」というエラーでクラッシュしうる。
    ハッシュ化してフラットに保存することでこの衝突を構造的に避ける。ディレクトリ
    トラバーサル（`..`等）も、パスがファイル名に使われないため問題にならない。

    `jma_tile_redis_cache.py`もこのハッシュ方式を踏襲する（ファイルキャッシュとRedis
    キャッシュで同じpathから異なるキー体系にならないように、公開関数にしている）。
    """
    return hashlib.sha256(path.encode("utf-8")).hexdigest()


def get(path: str) -> tuple[bytes, str] | None:
    """キャッシュ済みなら(内容, Content-Type)を返す。未キャッシュならNone。"""
    key = cache_key(path)
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


def _write_atomic(final_path: Path, write: Callable[[Path], None]) -> None:
    """同じディレクトリへ一意な一時ファイルを書き、`os.replace`で最終パスへ差し替える。

    最終パスへ直接write_bytes/write_textすると、書き込み中の`get()`が「存在するが
    未完了」のファイルを読んでしまう（部分書き込みの混入）。`os.replace`は同一
    ファイルシステム内であればPOSIX/Windowsどちらでもアトミックなため、読み手は
    常に「無い」か「完全に書き終わった内容」のどちらかしか見えなくなる。
    """
    tmp_path = final_path.with_suffix(f"{final_path.suffix}.tmp-{uuid.uuid4().hex}")
    write(tmp_path)
    os.replace(tmp_path, final_path)


def set(path: str, content: bytes, content_type: str) -> None:
    # キャッシュ書き込みはあくまで高速化目的で、呼び出し元は取得済みのcontentを既に
    # 返せる状態にある。ディスクフル・権限エラー等（OSError）でここが失敗しても、
    # basemap/road-surfaceタイルの配信自体を丸ごと500にする理由にはならないため、
    # 他のキャッシュ層（jma_tile_redis_cache.py等）と同じ「キャッシュ書き込み失敗は握りつぶす」
    # 方針に合わせ、警告ログのみでno-opにフォールバックする。
    try:
        key = cache_key(path)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # get()は`.bin`の存在を「キャッシュ済みか」の判定に使う（下記get()参照）ため、
        # `.meta`を先に書き終えてから`.bin`を書く。これにより
        # `.bin`が見えた時点で`.meta`は必ず既に完全に書き終わっている（存在＝完了、を
        # os.replaceのアトミック性と合わせて保証する）。
        _write_atomic(CACHE_DIR / f"{key}.meta", lambda p: p.write_text(content_type, encoding="utf-8"))
        _write_atomic(CACHE_DIR / f"{key}.bin", lambda p: p.write_bytes(content))
    except OSError:
        logger.warning("tile cache write failed for path=%s (disk full/permission?)", path, exc_info=True)


def clear_all() -> None:
    shutil.rmtree(CACHE_DIR, ignore_errors=True)


def prune_to_size_limit(max_bytes: int) -> int:
    """合計が`max_bytes`を超えていたら、最終更新の古いものから消す（解放バイト数を返す）。

    この置き場は**鍵に世代を持たない**（パスをハッシュ化してフラットに保つ。`cache_key`参照）
    ため、`tile_persistent_cache`のように世代単位では消せない。世代の変わったタイルは
    書かれなくなるだけで残り続けるので、古い順の退避で頭打ちにする。

    **古い順は「最後に書いた順」であって「最後に読んだ順」ではない**（`get`はmtimeを
    更新しない）。読まれ続けているタイルでも、書かれた時刻が古ければ先に消える——次の
    要求で作り直されるだけなので正しさは変わらないが、LRUのつもりで頼らないこと。

    削除は`.bin`と対の`.meta`をまとめて行う。途中の失敗（別プロセスが同じファイルを消した等）は
    握りつぶす——掃除の失敗が配信を止める理由にはならない。
    """
    try:
        entries = []
        total = 0
        for path in CACHE_DIR.glob("*.bin"):
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((stat.st_mtime, stat.st_size, path))
            total += stat.st_size
        if total <= max_bytes:
            return 0

        freed = 0
        for _mtime, size, path in sorted(entries):
            if total - freed <= max_bytes:
                break
            for target in (path, path.with_suffix(".meta")):
                try:
                    freed += target.stat().st_size
                    target.unlink()
                except OSError:
                    pass
        return freed
    except OSError:
        logger.warning("tile cache prune failed", exc_info=True)
        return 0
