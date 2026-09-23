"""キャッシュ鍵の組み立て（方針は docs/conventions/caching.md）。

署名はSHA-1の先頭12桁。鍵はタイルURLとディスクのディレクトリ名へ入るため、衝突耐性より
パス長を優先している（形の変化を見分けるのが目的で、暗号的な強度は要らない）。
"""

import dataclasses
import hashlib


# 土地被覆ラスタタイル。同じ配色のまま元のGeoTIFFを別の年次・別の版へ差し替えたときに
# 上げる（画素が変わるのにURLが変わらないため）。
LANDCOVER_REVISION = "1"

# 静的Edge×公開軸スコア行列。同じ材料・同じ列から違う値を作るようになったとき
# （`domain/evaluation.py: build_static_edge_score_matrix`の計算式変更）に上げる。
SCORE_MATRIX_REVISION = "12"


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

    dataclassを列名の並びで署名するのは、pickleが状態を**列の位置**で持つため
    （`dataclasses._dataclass_setstate`がfieldsとstateをzipする）。列を足す・消す・
    並べ替えると、古いキャッシュを復元したときに後ろの列が欠けたまま実体化し、最初に
    その列へ触れた場所でAttributeErrorになる。
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


def tile_version(revision: int | None, shape: str) -> str:
    """配信するタイルの世代。`<DBの世代>-<形の署名>`。

    `revision`は`derived_data_meta.get_revision()`の値。Noneは世代を読めない状態
    （migration未適用のテストDB等）で、`UNKNOWN_REVISION`を使う。
    """
    return f"{UNKNOWN_REVISION if revision is None else revision}-{shape}"
