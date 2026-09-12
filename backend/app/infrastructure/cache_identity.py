"""キャッシュ鍵の組み立て方の正本。

鍵は「手で書くリビジョン」と「形の署名」の2つから作る。形——MVTへ焼き込むSQL、pickleする
dataclassの列構成——はここで機械的に署名するため、形を変えた版はリビジョンを上げ忘れても
別の鍵になり、古いキャッシュを復元しない。

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

# 路面ベクタタイル。焼き込むプロパティの増減・SQLの変更は署名側が捕まえる。ここを上げるのは
# SQLが読むテーブルの中身を作り直したとき（PBF再取込・precomputeバッチ）。
# プロパティ削除を伴う変更は、対応するfrontendのデプロイより先に本番へ出さないこと
# （旧フロントの凡例フィルタが全地物に一致し、対象レイヤーが一時的に「不明・他」になる）。
ROAD_SURFACE_REVISION = "24"

# 停止要因POIタイル。上と同じ運用。
POI_REVISION = "4"

# 事故タイル。上と同じ運用。
ACCIDENT_REVISION = "1"

# Road Graph探索用の材料（`EdgeMaterialTable`・`SearchMaterials`）。列構成の変化は署名側が
# 捕まえる。ここを上げるのは、材料が読む事前集計・派生データを作り直したとき:
#   - PBF再取込（app/batch/import_pbf.py）
#   - 交差点分割の事前バッチ（app/batch/presplit_road_graph.py）
#   - precompute系バッチ（edge_attribute_counts・elevation_attributes・road_node_degrees・
#     way_attribute_counts・edge_curvature 等）
#   - `app/batch/refresh_derived.py`（disaster-recovery.md参照。PBF再取込を除く上記一式を
#     1コマンドで実行するため、これを実行したときも上げる）
# 上げないと、バッチ実行前にキャッシュ済みだったタイルはディスク経由で古いまま復元され続け、
# 未訪問タイルだけが新しい値になる——症状が局所的で気づきにくい。
MATERIAL_REVISION = "12"

# 静的Edge×公開軸スコア行列。列構成の変化は署名側が、材料の作り直しは材料世代との複合
# （`tile_score_matrix_cache.py`）が捕まえる。ここを上げるのは、同じ材料・同じ列から
# 違う値を作るようになったとき（`domain/evaluation.py: build_static_edge_score_matrix`の
# 計算式変更）。軸定義の編集はこの世代管理の対象外——デプロイを伴わない実行時の操作のため、
# `sync_disk_cache_with_axis_revision()`が担う。
SCORE_MATRIX_REVISION = "11"


def shape_digest(*sources: object) -> str:
    """形の署名。dataclassは列名の並び、それ以外は文字列化した内容で決まる。

    dataclassを渡せるのは、pickleが状態を**列の位置**で持つため
    （`dataclasses._dataclass_setstate`がfieldsとstateをzipする）。列を足す・消す・
    並べ替えると、古いキャッシュを復元したときに後ろの列が欠けたまま実体化し、最初に
    その列へ触れた場所でAttributeErrorになる。
    """
    parts = []
    for source in sources:
        if dataclasses.is_dataclass(source):
            parts.append(",".join(f.name for f in dataclasses.fields(source)))
        else:
            parts.append(str(source))
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()[:12]


def cache_identity(revision: str, *shape_sources: object) -> str:
    """`<リビジョン>-<形の署名>`。タイルURL・ディスクパスへそのまま入れる。"""
    return f"{revision}-{shape_digest(*shape_sources)}"
