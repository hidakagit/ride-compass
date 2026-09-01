"""探索用グラフ・索引（LazyRoadGraph／routable Node空間索引）のプロセス内メモリキャッシュ
（改善計画T537、docs/tasks/T537.md）。

`RoadGraphEngine.prepare`/`preview_segment`は、リクエストごとに`build_lazy_road_graph`・
`compute_routable_node_ids`・`build_node_spatial_index`をbbox全体（数十万Edge規模）に
対して毎回作り直しており、温パスのprepare所要時間のほぼ全てを占めていた（T522実測）。
これらはタイル集合と0次フィルタ（`hard_filters`・`max_average_grade_percent`）だけで
決まる純粋な派生物のため、`graph_material_cache`と同じ「タイル集合キーのプロセス内
LRU」でキャッシュする（T537対応方針の案a、実装最小の案を採用——判断理由は
docs/tasks/T537.md参照）。

**キャッシュキーは`frozenset[tuple[zoom, x, y]]`（bboxを覆うz12タイル集合）**。
`GraphService.get_search_materials_for_bbox`が「bboxを覆う全z12タイルの材料キャッシュを
そのまま結合したグラフ」を返した場合のみこの集合が得られる（`_build_search_materials_
from_tile_cache`経由）。split鮮度が古くbbox限定で再構築した場合（`_build_search_materials_
uncached`）はタイル集合がNoneになり、呼び出し側はこのキャッシュを経由しない——タイル境界と
一致しない不完全な集合を書き込むと、後続の正規リクエストへ不完全な結果を返しかねないため
（`graph_material_cache`が同じ理由でこのbboxを書き込まないのと同じ設計）。

**無効化方針は`graph_material_cache`と同じ「プロセス寿命でのみキャッシュ、LRUで
上限件数」**（軸定義変更は無関係——静的スコア行列[`tile_score_matrix_cache`]と異なり
探索コストの値自体を持たないため。材料再取込の反映にはプロセス再起動が必要な点も同じ）。

LRU上限は`graph_material_cache`（タイル単位、上限2,000）より大幅に小さくしてある。
本キャッシュの1エントリは「bbox全体を結合した後のグラフ・索引」（起点半径・経由地に
応じて数タイル〜数十タイル分をまとめたもの）であり、粒度がタイル単体よりずっと粗い。
典型的な運用（起点付近への繰り返しアクセスが中心、docs/tasks/T522.md参照）では
同時にホットな探索エリアの数はタイル数よりずっと少ないという想定のもと、
小さめの上限で運用する（実測に基づく調整ではなく、他のプロセス内メモリキャッシュと
同じ経験的な割り切り。上限に達した場合はLRUで最も長く使われていないエントリから
自然に破棄される）。
"""

from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.routing import LazyRoadGraph, NodeSpatialIndex

# bbox全体ぶんの結合済みグラフ・索引を保持するエントリのため、タイル単位キャッシュより
# 小さい上限にする（モジュールdocstring参照）。
DEFAULT_MAX_ENTRIES = 64

TileSet = frozenset[tuple[int, int, int]]
RoutableIndexKey = tuple[TileSet, "frozenset[str] | None", "float | None"]

_lazy_graph_cache: "OrderedDict[TileSet, LazyRoadGraph]" = OrderedDict()
_routable_index_cache: "OrderedDict[RoutableIndexKey, NodeSpatialIndex]" = OrderedDict()
_max_entries = DEFAULT_MAX_ENTRIES


def get_lazy_graph(tile_set: TileSet) -> "LazyRoadGraph | None":
    value = _lazy_graph_cache.get(tile_set)
    if value is not None:
        _lazy_graph_cache.move_to_end(tile_set)
    return value


def set_lazy_graph(tile_set: TileSet, lazy_graph: "LazyRoadGraph") -> None:
    _lazy_graph_cache[tile_set] = lazy_graph
    _lazy_graph_cache.move_to_end(tile_set)
    if len(_lazy_graph_cache) > _max_entries:
        _lazy_graph_cache.popitem(last=False)


def get_routable_index(key: RoutableIndexKey) -> "NodeSpatialIndex | None":
    value = _routable_index_cache.get(key)
    if value is not None:
        _routable_index_cache.move_to_end(key)
    return value


def set_routable_index(key: RoutableIndexKey, index: "NodeSpatialIndex") -> None:
    _routable_index_cache[key] = index
    _routable_index_cache.move_to_end(key)
    if len(_routable_index_cache) > _max_entries:
        _routable_index_cache.popitem(last=False)


def clear() -> None:
    """テスト用。キャッシュを全消去する（本番コードパスからは呼ばない）。"""
    _lazy_graph_cache.clear()
    _routable_index_cache.clear()


def lazy_graph_cache_size() -> int:  # テストの検証用
    return len(_lazy_graph_cache)


def routable_index_cache_size() -> int:  # テストの検証用
    return len(_routable_index_cache)
