"""タイル単位の複雑なPythonオブジェクトをディスクへ永続化する汎用キャッシュ（改善計画T538）。

`infrastructure/tile_cache.py`（DEMタイル・ベクタタイルのディスクキャッシュ、生バイト列を
そのまま保存する）と同じ「デプロイのたびにプロセスが再起動されても、ディスク上のキャッシュは
残る」という考え方を、タイル単位の複雑なPythonオブジェクト（`SearchMaterials`・
`StaticEdgeScoreMatrix`。いずれもPydanticモデル/dataclass/numpy配列が混在する構造）へ
拡張したもの。`graph_material_cache.py`・`tile_score_matrix_cache.py`のプロセス内LRUが
missしたときの第2段として使う——`graph_material_cache`（z12タイル単位のトポロジ＋材料）は
元々プロセス内メモリのみで、`deploy-backend.yml`がデプロイのたびにコンテナを再起動するため、
再起動後最初の利用者が毎回DB読み出し（本番VM実測29〜45秒、東京駅30km・16タイル）を負担して
いた（docs/tasks/T538.md）。

**シリアライズはpickleを使う**: 対象（`SearchMaterials`・`StaticEdgeScoreMatrix`）は
Pydanticモデル・frozen dataclass・numpy配列が混在する構造で、JSON化に適さない
（`road_edge_geometry_cache.py`がRedis向けにPydanticのJSON化を使うのとは対象の複雑さが
異なる）。picklable性はテストで確認済み。

**ファイル破損・部分書き込みはすべてキャッシュミス扱いにフォールバックする**
（`tile_cache.py`の`get()`と同じ「壊れていたら未キャッシュ扱いにして呼び出し元に
再構築させる」方針）。pickleの壊れ方は`UnpicklingError`に限らず`EOFError`/
`AttributeError`（クラス定義変更）/`ImportError`（モジュール移動）等、型を予測しきれない
ため、読み込み時は意図的に`Exception`を広く捕捉する。

**無効化はバージョン文字列をファイルパスへ埋め込む方式**
（`region_service.py: ROAD_SURFACE_TILE_VERSION`と同じ流儀）。呼び出し側
（`graph_material_cache.py`・`tile_score_matrix_cache.py`）がキャッシュ対象の種類ごとに
独立したバージョン定数を持ち、PBF再取込・precomputeバッチ実行・構築ロジック変更時に
手動で上げる（対応する定数のdocstring参照）。旧バージョンのファイルは新バージョンの
パスから見えなくなるだけで、明示的な削除は行わない（`clear_namespace`/`clear_all`は
テスト・即時無効化専用）。
"""

import logging
import os
import pickle
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.infrastructure.tile_cache import DATA_DIR

logger = logging.getLogger("app.infrastructure.tile_persistent_cache")

CACHE_DIR = DATA_DIR / "tile_persistent_cache"


def _tile_path(namespace: str, version: str, zoom: int, x: int, y: int) -> Path:
    return CACHE_DIR / namespace / f"v{version}" / f"{zoom}_{x}_{y}.pkl"


def _write_atomic(final_path: Path, write: Callable[[Path], None]) -> None:
    """同じディレクトリへ一意な一時ファイルを書き、`os.replace`で最終パスへ差し替える
    （`tile_cache.py: _write_atomic`と同じアトミック差し替え。対象がバイト列
    [tile_cache.py]か任意のPythonオブジェクト[本モジュール]かで書き込み手段
    ["write"コールバックの中身]が異なるため、モジュールをまたいだ共通化はせず
    同じロジックをこちらにも持たせる——tile_cache.py自体はDEM/ベクタタイル専用の
    既存モジュールとして変更しない）。
    """
    tmp_path = final_path.with_suffix(f"{final_path.suffix}.tmp-{uuid.uuid4().hex}")
    write(tmp_path)
    os.replace(tmp_path, final_path)


def get(namespace: str, version: str, zoom: int, x: int, y: int) -> Any | None:
    """キャッシュ済みならデシリアライズ済みの値を返す。未キャッシュ・破損時はNone。"""
    path = _tile_path(namespace, version, zoom, x, y)
    try:
        if not path.is_file():
            return None
        with path.open("rb") as f:
            return pickle.load(f)
    except Exception as exc:  # noqa: BLE001 破損ファイル・pickle形式の不整合(UnpicklingError/
        # EOFError/AttributeError/ImportError等、壊れ方次第で例外の型が多岐にわたる)は
        # すべて未キャッシュ扱いにフォールバックし、呼び出し元にDBから再構築させる
        # （tile_cache.pyのget()と同じ方針。is_file()確認とread/unpickleの間に
        # clear_namespace()[rmtree]と競合した場合もここに含まれる）。
        logger.warning(
            "tile persistent cache read failed namespace=%s version=%s zoom=%d x=%d y=%d, treating as cache miss",
            namespace, version, zoom, x, y, exc_info=True,
        )
        return None


def set(namespace: str, version: str, zoom: int, x: int, y: int, value: Any) -> None:
    """呼び出し元は既にvalueをメモリキャッシュ・レスポンスに使える状態にあるため、
    ディスク書き込み失敗（ディスクフル・権限エラー・pickle化不能な値等）はここで
    握りつぶし、警告ログのみでno-opにフォールバックする（`tile_cache.py`の`set()`と
    同じ方針。キャッシュ書き込みの失敗がルート生成応答を止める理由にはならない）。
    """
    try:
        path = _tile_path(namespace, version, zoom, x, y)
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(path, lambda p: p.write_bytes(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)))
    except Exception as exc:  # noqa: BLE001 OSError(ディスクフル/権限)・pickle化不能
        # (PicklingError/TypeError/AttributeError等)のいずれもここで吸収する。
        logger.warning(
            "tile persistent cache write failed namespace=%s version=%s zoom=%d x=%d y=%d error=%r",
            namespace, version, zoom, x, y, exc, exc_info=True,
        )


def clear_namespace(namespace: str) -> None:
    """指定namespace配下（全バージョン）を丸ごと削除する。

    テスト用に加え、実行時のAPI操作で即時無効化が要る呼び出し元
    （軸定義編集時の`tile_score_matrix_cache.clear()`等、バージョン文字列の手動更新では
    表現できないタイミングの無効化）が使う。
    """
    shutil.rmtree(CACHE_DIR / namespace, ignore_errors=True)


def clear_all() -> None:
    """テスト用。全namespaceを削除する。"""
    shutil.rmtree(CACHE_DIR, ignore_errors=True)
