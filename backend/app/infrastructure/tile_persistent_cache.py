"""タイル単位の複雑なPythonオブジェクトをディスクへ永続化する汎用キャッシュ。

`infrastructure/tile_cache.py`（DEMタイル・ベクタタイルのディスクキャッシュ、生バイト列を
そのまま保存する）と同じ「デプロイのたびにプロセスが再起動されても、ディスク上のキャッシュは
残る」という考え方を、タイル単位の複雑なPythonオブジェクト（`SearchMaterials`・
`StaticEdgeScoreMatrix`。いずれもPydanticモデル/dataclass/numpy配列が混在する構造）へ
拡張したもの。`graph_material_cache.py`・`tile_score_matrix_cache.py`のプロセス内LRUが
missしたときの第2段として使う——プロセス内メモリのみだと、`deploy-backend.yml`が
デプロイのたびにコンテナを再起動するたびに、再起動後最初の利用者が毎回DB読み出し
（29〜45秒規模、東京駅30km・16タイル）を負担することになる。

**保存の実体は`diskcache`**（SQLite＋ファイル）。容量上限
（`settings.tile_persistent_cache_size_limit_mb`）・退避（least-recently-used）・複数
プロセスからの安全な共有をライブラリが持つため、これらを自前で書かない
（docs/caching.md参照）。32KBを超える値はライブラリがファイルへ、以下はSQLite内へ格納する。

**シリアライズはpickle**（`diskcache`の既定）。対象はPydanticモデル・frozen dataclass・
numpy配列が混在する構造で、JSON化に適さない。picklable性はテストで確認済み。

**壊れたエントリ・書き込み失敗はすべてキャッシュミス扱いにフォールバックする**
（`tile_cache.py`の`get()`と同じ「壊れていたら未キャッシュ扱いにして呼び出し元に
再構築させる」方針）。キャッシュ書き込みの失敗がルート生成応答を止める理由にはならない。

**無効化はバージョン文字列をキーへ含める方式**（`region_service.py:
ROAD_SURFACE_TILE_VERSION`と同じ流儀）。呼び出し側がキャッシュ対象の種類ごとに独立した
バージョン定数を持ち、PBF再取込・precomputeバッチ実行・構築ロジック変更時に手動で上げる。
旧バージョンのエントリは`prune_stale_generations`が削除する（世代番号だけでは古い実体が
残り続けるため。docs/caching.md「無効化」参照）。
"""

import logging
import time
from typing import Any

import diskcache

from app.config import settings
from app.infrastructure.tile_cache import DATA_DIR

logger = logging.getLogger("app.infrastructure.tile_persistent_cache")

CACHE_DIR = DATA_DIR / "tile_persistent_cache"

_cache: diskcache.Cache | None = None


def _tag(namespace: str, version: str) -> str:
    """世代単位でまとめて扱えるようにするタグ。"""
    return f"{namespace}:v{version}"


def _key(namespace: str, version: str, zoom: int, x: int, y: int) -> tuple[str, str, int, int, int]:
    return (namespace, version, zoom, x, y)


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


def get_by_key(key: tuple, stats: dict[str, object] | None = None) -> Any | None:
    """任意のタプルキーで読む。キーの設計は呼び出し元が持つ（先頭要素をnamespaceにする）。

    `stats`を渡すと読み出しの所要時間（ms）を`read_ms`へ書き込む。未キャッシュ・破損時は
    `stats`へ何も書き込まない。
    """
    try:
        started = time.monotonic()
        value = cache().get(key)
        read_ms = (time.monotonic() - started) * 1000
    except Exception:  # noqa: BLE001 破損エントリ・SQLite障害はいずれも未キャッシュ扱いにする
        logger.warning("tile persistent cache read failed key=%r, treating as cache miss", key, exc_info=True)
        return None
    if value is None:
        return None
    if stats is not None:
        stats["read_ms"] = read_ms
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


def get(
    namespace: str, version: str, zoom: int, x: int, y: int, stats: dict[str, object] | None = None
) -> Any | None:
    """キャッシュ済みなら値を返す。未キャッシュ・破損時はNone。

    `stats`を渡すと読み出しの所要時間（ms）を`read_ms`へ書き込む。呼び出し元
    （`graph_material_cache.py`・`tile_score_matrix_cache.py`）が更に上位（リクエスト単位の
    INFOサマリ）へ集約する。未キャッシュ・破損時は`stats`へ何も書き込まない。
    """
    try:
        started = time.monotonic()
        value = cache().get(_key(namespace, version, zoom, x, y))
        read_ms = (time.monotonic() - started) * 1000
    except Exception:  # noqa: BLE001 破損エントリ・SQLite障害はいずれも未キャッシュ扱いにする
        logger.warning(
            "tile persistent cache read failed namespace=%s version=%s zoom=%d x=%d y=%d, treating as cache miss",
            namespace, version, zoom, x, y, exc_info=True,
        )
        return None
    if value is None:
        return None
    if stats is not None:
        stats["read_ms"] = read_ms
    logger.debug(
        "tile persistent cache hit namespace=%s version=%s zoom=%d x=%d y=%d read_ms=%.1f",
        namespace, version, zoom, x, y, read_ms,
    )
    return value


def set(namespace: str, version: str, zoom: int, x: int, y: int, value: Any) -> None:
    """呼び出し元は既にvalueをメモリキャッシュ・レスポンスに使える状態にあるため、
    書き込み失敗（ディスクフル・pickle化不能な値等）はここで握りつぶし、警告ログのみで
    no-opにフォールバックする。"""
    try:
        cache().set(_key(namespace, version, zoom, x, y), value, tag=_tag(namespace, version))
    except Exception as exc:  # noqa: BLE001 OSError（ディスクフル）・pickle化不能のいずれも吸収する
        logger.warning(
            "tile persistent cache write failed namespace=%s version=%s zoom=%d x=%d y=%d error=%r",
            namespace, version, zoom, x, y, exc, exc_info=True,
        )


def _delete_matching(predicate) -> int:
    removed = 0
    for key in list(cache().iterkeys()):
        if isinstance(key, tuple) and len(key) == 5 and predicate(key):
            if cache().delete(key):
                removed += 1
    return removed


def prune_stale_generations(namespace: str, keep_version: str) -> int:
    """`namespace`配下のうち`keep_version`以外の世代を削除し、削除件数を返す。

    容量上限に達すれば古いものから自動で退避されるが、世代を上げた直後は「もう誰も
    読まないエントリ」が上限に達するまで居座る。世代交代のタイミングで明示的に捨てる。
    """
    try:
        return _delete_matching(lambda key: key[0] == namespace and key[1] != keep_version)
    except Exception:  # noqa: BLE001 掃除の失敗は容量上限の自動退避へ委ねる
        logger.warning("tile persistent cache prune failed namespace=%s", namespace, exc_info=True)
        return 0


def clear_namespace(namespace: str) -> None:
    """指定namespace配下（全バージョン）を丸ごと削除する。

    テスト用に加え、実行時のAPI操作で即時無効化が要る呼び出し元
    （軸定義編集時の`tile_score_matrix_cache.clear()`等、バージョン文字列の手動更新では
    表現できないタイミングの無効化）が使う。
    """
    _delete_matching(lambda key: key[0] == namespace)


def clear_all() -> None:
    """テスト用。全namespaceを削除する。"""
    cache().clear()
