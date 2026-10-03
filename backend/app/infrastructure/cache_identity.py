"""キャッシュ鍵の組み立て（方針は docs/conventions/caching.md）。

署名はSHA-1の先頭12桁。鍵はタイルURLとディスクのディレクトリ名へ入るため、衝突耐性より
パス長を優先している（形の変化を見分けるのが目的で、暗号的な強度は要らない）。
"""

import dataclasses
import hashlib

from app.infrastructure.derived_data_meta import DataRevisions

# 土地被覆ラスタタイル。同じ配色のまま、元のGeoTIFFを別の年次・別の版へ差し替えたときと、
# ラスタの読み方・描き方（`landcover_raster.py`）を変えたときに上げる（画素が変わるのに
# URLもディスクキャッシュの鍵も変わらないため）。
LANDCOVER_REVISION = "2"

def bound_values(source: object) -> list[tuple[str, str]]:
    """SQLのバインドパラメータのうち、定義時点で値が決まっているもの（名前と値）。

    実行時に値を渡すパラメータ（タイル座標等）はこの時点で値を持たない。
    """
    bindparams = getattr(source, "_bindparams", None)
    if not bindparams:
        return []
    return sorted(
        (name, repr(param.value)) for name, param in bindparams.items() if param.value is not None
    )


def shape_digest(*sources: object) -> str:
    """形の署名。dataclassは列名の並び、それ以外は文字列化した内容とバインド済みの値で決まる。

    dataclassを列名で署名するのは、道路網の置き場（`road_network_store.py`）が列ごとの
    ファイルを列名で読み書きするため。列を足す・消す・改名したコードが古い置き場を選ぶと、
    足した列のファイルが無いまま読みに行く。
    """
    parts = []
    for source in sources:
        if dataclasses.is_dataclass(source):
            parts.append(",".join(f.name for f in dataclasses.fields(source)))
            continue
        parts.append(str(source))
        parts.append(repr(bound_values(source)))
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()[:12]


def cache_identity(revision: str, *shape_sources: object) -> str:
    """`<リビジョン>-<形の署名>`。タイルURL・ディスクパスへそのまま入れる。"""
    return f"{revision}-{shape_digest(*shape_sources)}"


#: DBの世代を読めないときに使う印。**この値のタイルをディスクへ残さない**——世代が
#: 分からないまま焼いたタイルは、後で世代が判明しても古いと判定できない。
UNKNOWN_REVISION = "x"


def tile_version(revisions: DataRevisions | None, shape: str) -> str:
    """配信するタイルの世代。`<派生の世代>.<生データの世代>-<形の署名>`。

    `revisions`は`derived_data_meta.get_revisions()`の値。Noneはまだ読めていない状態で、
    派生の世代の行が無いDBと同じく`UNKNOWN_REVISION`を使う。
    """
    if revisions is None or revisions.derived is None:
        return f"{UNKNOWN_REVISION}-{shape}"
    return f"{revisions.derived}.{revisions.imported}-{shape}"


def is_known_tile_version(version: str) -> bool:
    """`tile_version`が世代を読めて組んだものか。違えばディスクへ残さない。"""
    return not version.startswith(f"{UNKNOWN_REVISION}-")
