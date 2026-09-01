"""タイル単位の静的Edge×公開軸スコア行列のプロセス内メモリキャッシュ（改善計画T536）。

`GraphService._get_or_build_tile_materials`が、z12タイル単位で`domain/evaluation.py:
build_static_edge_score_matrix`の結果（`StaticEdgeScoreMatrix`）をここへキャッシュする。
同一タイルへの2回目以降の探索リクエストは、Edgeごとのコスト計算（Pythonコールバック）を
一切行わずこの行列から配列演算でコストを合成できる（旧`infrastructure/axis_score_cache.py`
[Edge単位の辞書キャッシュ、T534。約1.3KB/Edge]を置き換える。本行列はEdgeあたり公開軸の
数×8バイト程度で収まる、T536実測はdocs/tasks/T536.md参照）。

**`infrastructure/graph_material_cache.py`（`EdgeMaterialBundle`等の材料そのもの）とは
意図的に別のキャッシュとして持つ**。軸スタジオでの軸定義編集（`AxisRegistryAdminService`
経由の`refresh_axis_definitions`）はこちらだけを`clear()`し、材料キャッシュ（DBアクセスを
伴う取得）は温存する——軸編集直後の最初のリクエストがDBへ再問い合わせせずに済み、
訪れたタイルぶんだけ静的スコア行列を再計算するだけで反映される設計（旧axis_score_cache.py
と同じ設計意図をタイル粒度へ引き継ぐ）。

**無効化方針（改善計画T538で変更）**: プロセス内メモリのLRU（タイル単位、
`graph_material_cache`と同じ`DEFAULT_MAX_TILES`）に加え、`infrastructure/
tile_persistent_cache.py`へも同じ内容をディスク永続化する（`graph_material_cache.py`と
同じ動機・設計、docs/tasks/T538.md）。無効化経路は2種類ある:

1. **PBF再取込・precomputeバッチ・構築ロジック変更**: `TILE_SCORE_MATRIX_CACHE_VERSION`の
   バージョン文字列を手動で上げる（`region_service.py: ROAD_SURFACE_TILE_VERSION`と
   同じ流儀。コメント参照）。
2. **軸定義編集（`refresh_axis_definitions`）**: バージョン文字列は据え置いたまま、
   `clear()`がメモリ・ディスク両方のキャッシュを無条件で即座に削除する。軸編集は
   デプロイを伴わない実行時のAPI操作のため、ファイル世代の手動更新では表現できない
   タイミングの無効化が要る（バージョン文字列を上げてしまうと、軸編集と無関係な他の
   全タイルのディスクキャッシュまで巻き添えで無効化されてしまう）。
"""

from collections import OrderedDict

from app.domain.evaluation import StaticEdgeScoreMatrix
from app.infrastructure import tile_persistent_cache

# graph_material_cache.pyのDEFAULT_MAX_TILESと同じ値（同じタイル粒度・同じ対象範囲
# [関東圏]を想定するため、上限も揃える）。
DEFAULT_MAX_TILES = 2_000

_cache: "OrderedDict[tuple[int, int, int], StaticEdgeScoreMatrix]" = OrderedDict()
_max_entries = DEFAULT_MAX_TILES

# ディスク永続化キャッシュ（tile_persistent_cache.py）のnamespace・バージョン
# （改善計画T538）。パスへ埋め込むことで対応しない世代のファイルを読まないようにする。
#
# 以下を実行したときはこの値を手動で上げること:
#   - PBF再取込（app/batch/import_pbf.py）
#   - 交差点分割の事前バッチ（app/batch/presplit_road_graph.py）
#   - `StaticEdgeScoreMatrix`が読む事前集計・派生データを更新するprecomputeバッチ
#     （precompute_edge_attribute_counts.py・precompute_elevation_attributes.py・
#     precompute_road_node_degrees.py・precompute_way_attribute_counts.py）
#   - `build_static_edge_score_matrix`自体の計算式変更（domain/evaluation.py）
#
# **軸定義（axis_definitionsテーブル）の追加・削除・shape_params調整はこの世代管理の
# 対象外**——軸スタジオでの編集は上記のバージョン更新（デプロイを伴う）ではなく、
# 下記`clear()`（`refresh_axis_definitions`経由の即時呼び出し）が担う。
# v1: 初版（改善計画T538）。
_CACHE_NAMESPACE = "score_matrix"
TILE_SCORE_MATRIX_CACHE_VERSION = "1"


def _remember(key: tuple[int, int, int], matrix: StaticEdgeScoreMatrix) -> None:
    """メモリLRUへ書き込み、上限超過分を退避する（`set()`・ディスクヒット時の
    再取り込みの両方から使う共通ロジック）。"""
    _cache[key] = matrix
    _cache.move_to_end(key)
    if len(_cache) > _max_entries:
        _cache.popitem(last=False)


def get(zoom: int, x: int, y: int) -> StaticEdgeScoreMatrix | None:
    key = (zoom, x, y)
    value = _cache.get(key)
    if value is not None:
        _cache.move_to_end(key)
        return value
    # 改善計画T538: メモリmissでもディスク永続化キャッシュを確認する（プロセス再起動
    # 直後や、LRU上限で立ち退いた直後がこの経路に該当する）。
    persisted: StaticEdgeScoreMatrix | None = tile_persistent_cache.get(
        _CACHE_NAMESPACE, TILE_SCORE_MATRIX_CACHE_VERSION, zoom, x, y
    )
    if persisted is None:
        return None
    _remember(key, persisted)
    return persisted


def set(zoom: int, x: int, y: int, matrix: StaticEdgeScoreMatrix) -> None:
    _remember((zoom, x, y), matrix)
    tile_persistent_cache.set(_CACHE_NAMESPACE, TILE_SCORE_MATRIX_CACHE_VERSION, zoom, x, y, matrix)


def clear() -> None:
    """テスト用、および軸定義変更時（`refresh_axis_definitions`）に呼ぶ。

    改善計画T538: ディスク永続化キャッシュ（tile_persistent_cache）も同時に削除する。
    メモリだけクリアしてディスクを残すと、次回プロセス再起動時に軸編集前の古いスコア
    行列がディスクから復元されてしまう（軸編集はバージョン文字列の手動更新を伴わない
    実行時操作のため、即時削除で対応する。モジュールdocstring参照）。
    """
    _cache.clear()
    tile_persistent_cache.clear_namespace(_CACHE_NAMESPACE)


def size() -> int:  # テストの検証用（メモリLRUの件数のみ。ディスク側は対象外）
    return len(_cache)
