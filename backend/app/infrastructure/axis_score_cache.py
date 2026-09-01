"""Edge単位の静的軸別スコア（風以外）のプロセス内メモリキャッシュ（改善計画T534）。

`domain/evaluation.py: compute_edge_static_axis_data`の戻り値をEdge ID単位で遅延キャッシュ
する。`compute_edge_cost`内部（タグパース・区分線形補間・`AXIS_DEFINITIONS`の軸評価
ループ）が探索ホットパス（訪れたEdgeごとに最大24回＝8方位×3レグ呼ばれる）の支配的コスト
とcProfile実測で判明したが、風以外の軸別スコアはEdgeの材料のみで決まりリクエスト間で
不変なため、初回計算時にここへ積み上げることで2回目以降の探索が同じEdgeを再訪した際に
重い計算を再実行せずに済む（docs/tasks/T534.md参照）。

**`infrastructure/graph_material_cache.py`（`EdgeMaterialBundle`等の材料そのもの）とは
意図的に別のキャッシュとして持つ**。軸スタジオでの軸定義編集（`AxisRegistryAdminService`
経由の`refresh_axis_definitions`）はこちらだけを`clear()`し、材料キャッシュ（DBアクセスを
伴う取得）は温存する——軸編集直後の最初のリクエストがDBへ再問い合わせせずに済み、訪れた
Edgeぶんだけ軸別スコアを再計算するだけで反映される設計（本番は`uvicorn --workers`未指定の
単一プロセスのため、`refresh_axis_definitions`完了直後のリクエストから確実に新定義を見る）。

無効化方針は`graph_material_cache`と同じ「プロセス寿命でのみキャッシュする」に加え、
軸定義変更時の明示的な`clear()`（`axis_registry_service.py: refresh_axis_definitions`）。
"""

from collections import OrderedDict

# graph_material_cache.pyのタイル単位（z12、上限2,000枚）とは異なりEdge ID単位の
# フラットなキャッシュのため、上限もEdge数ベースで設定する。24.7万Edge規模のbboxを
# 複数保持できる余裕を持たせた値（実測ベンチマーク[T522.md]の渋谷相当bboxが基準）。
DEFAULT_MAX_ENTRIES = 1_000_000

_cache: OrderedDict[str, dict[str, object]] = OrderedDict()
_max_entries = DEFAULT_MAX_ENTRIES


def get(edge_id: str) -> dict[str, object] | None:
    value = _cache.get(edge_id)
    if value is not None:
        _cache.move_to_end(edge_id)
    return value


def set(edge_id: str, data: dict[str, object]) -> None:
    _cache[edge_id] = data
    _cache.move_to_end(edge_id)
    if len(_cache) > _max_entries:
        _cache.popitem(last=False)


def clear() -> None:
    """テスト用、および軸定義変更時（`refresh_axis_definitions`）に呼ぶ。"""
    _cache.clear()


def size() -> int:  # テストの検証用
    return len(_cache)
