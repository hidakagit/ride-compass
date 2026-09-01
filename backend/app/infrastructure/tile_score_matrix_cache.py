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

無効化方針は`graph_material_cache`と同じ「プロセス寿命でのみキャッシュ、LRUで上限件数」
（タイル単位、`graph_material_cache`と同じ`DEFAULT_MAX_TILES`）に加え、軸定義変更時の
明示的な`clear()`（`axis_registry_service.py: refresh_axis_definitions`）。
"""

from collections import OrderedDict

from app.domain.evaluation import StaticEdgeScoreMatrix

# graph_material_cache.pyのDEFAULT_MAX_TILESと同じ値（同じタイル粒度・同じ対象範囲
# [関東圏]を想定するため、上限も揃える）。
DEFAULT_MAX_TILES = 2_000

_cache: "OrderedDict[tuple[int, int, int], StaticEdgeScoreMatrix]" = OrderedDict()
_max_entries = DEFAULT_MAX_TILES


def get(zoom: int, x: int, y: int) -> StaticEdgeScoreMatrix | None:
    key = (zoom, x, y)
    value = _cache.get(key)
    if value is not None:
        _cache.move_to_end(key)
    return value


def set(zoom: int, x: int, y: int, matrix: StaticEdgeScoreMatrix) -> None:
    key = (zoom, x, y)
    _cache[key] = matrix
    _cache.move_to_end(key)
    if len(_cache) > _max_entries:
        _cache.popitem(last=False)


def clear() -> None:
    """テスト用、および軸定義変更時（`refresh_axis_definitions`）に呼ぶ。"""
    _cache.clear()


def size() -> int:  # テストの検証用
    return len(_cache)
