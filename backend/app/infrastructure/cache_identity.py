"""キャッシュ鍵の組み立て方の正本。

鍵は「手で書くリビジョン」と「形の署名」の2つから作る。形——MVTへ焼き込むSQL、そこへ
あらかじめ束ねた値、pickleするdataclassの列構成——はここで機械的に署名するため、形を変えた版は
リビジョンを上げ忘れても別の鍵になり、古いキャッシュを復元しない。

手で上げるのは「形は変わらないが意味が変わった」ときだけである。具体的には、同じSQL・
同じ列構成のまま、それが読むDBの中身を作り直したとき（PBF再取込・precomputeバッチ）と、
値の意味を決める計算式をSQLの外で変えたとき。判断の材料は各リビジョンのコメントにある。

署名はSHA-1の先頭12桁。鍵はタイルURLとディスクのディレクトリ名へ入るため、衝突耐性より
パス長を優先している（形の変化を見分けるのが目的で、暗号的な強度は要らない）。

**値を作る関数のソース自体はハッシュしない**。純粋な改名やコメント修正でも全キャッシュが
無効化され、冷パス（材料で29〜45秒規模）を毎デプロイで踏むことになるため
（docs/tasks/T747.md）。
"""

import dataclasses
import hashlib


# --- 手で上げるリビジョン（形の変化は署名が捕まえるので、ここは「意味」だけ） ---

# **タイルへ焼く3系統（路面・停止要因POI・事故）の世代は、手で書く定数を持たない。**
# これらの世代が表すのは「SQLが読むテーブルの中身が作り直されたか」で、それを知っている
# のはバッチが進めるDBの世代（`derived_data_meta.revision`）だけである。手で書くと、
# 上げ忘れ（古い値のまま配り続ける）と、バッチ完了後にもう一度上げ直す必要（デプロイと
# バッチの間に焼かれたタイルが新しい鍵のまま古い値で残る）の両方が起きる。
# 実行時の組み立ては`services/tile_version_service.py`が行う。

# 土地被覆ラスタタイル。配色・クラス構成の変化は署名側（`LANDCOVER_CLASSES`）が捕まえる。
# ここを上げるのは、同じ配色のまま元のGeoTIFFを別の年次・別の版へ差し替えたとき
# （画素が変わるのにURLが変わらないため）。
LANDCOVER_REVISION = "1"

# Road Graph探索用の材料（`EdgeMaterialArrays`・`SearchMaterials`）はここにリビジョンを持たない。
# 形の署名だけで鍵を作り、中身の作り直しはDBの`derived_data_meta.revision`が表す
# （`graph_material_cache.sync_disk_cache_with_derived_data_revision`）。バッチの実行は
# デプロイを伴わないため、手で書き換える定数では表せない。

# 静的Edge×公開軸スコア行列。dataclassの列構成の変化は署名側が、材料の作り直しは材料世代
# との複合（`tile_score_matrix_cache.py`）が捕まえる。ここを上げるのは、同じ材料・同じ列から
# 違う値を作るようになったとき（`domain/evaluation.py: build_static_edge_score_matrix`の
# 計算式変更）。軸定義の編集はこの世代管理の対象外——デプロイを伴わない実行時の操作のため、
# `sync_disk_cache_with_axis_revision()`が担う。
#
# **可変長の列（`raw_axis_ids`/`material_ids`/`categorical_material_ids`）はここでは
# 捕まえられない**。`dataclasses.fields()`に現れない「中身で決まる列」で、集合を決める述語
# （`evaluation.py`の`route_facing_*`、その先の`axis_display.py`の生値可否判定と
# `MaterialSpec`の該当フィールド）はこのファイルを触らずに変えられる。そちらは
# `tile_score_matrix_cache.get()`が読み出し時に現在の述語と突き合わせて吸収する。
SCORE_MATRIX_REVISION = "11"


def bound_values(source: object) -> list[tuple[str, str]]:
    """SQLへ**あらかじめ値を束ねた**バインドパラメータ（名前と値）。

    実行時に値を渡すパラメータ（タイル座標等）は値を持たないため入らない。定義時点で
    決まっている集合（分類タグ等）だけが署名の材料になる。
    """
    bindparams = getattr(source, "_bindparams", None)
    if not bindparams:
        return []
    return sorted(
        (name, repr(param.value)) for name, param in bindparams.items() if param.value is not None
    )


def shape_digest(*sources: object) -> str:
    """形の署名。dataclassは列名の並び、それ以外は文字列化した内容で決まる。

    dataclassを渡せるのは、pickleが状態を**列の位置**で持つため
    （`dataclasses._dataclass_setstate`がfieldsとstateをzipする）。列を足す・消す・
    並べ替えると、古いキャッシュを復元したときに後ろの列が欠けたまま実体化し、最初に
    その列へ触れた場所でAttributeErrorになる。

    SQLは文字列化した内容に加えて**あらかじめ値を束ねたバインドパラメータ**も署名へ入れる。
    `str()`にはプレースホルダ名しか現れないため、分類に使うタグ集合を足し引きしても署名が
    動かない——焼き込み値は変わるのに鍵が同じ、という最も気づきにくい形になる。
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
