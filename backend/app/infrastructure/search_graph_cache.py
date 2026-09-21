"""探索用グラフ・索引（LazyRoadGraph／routable Node空間索引）のプロセス内メモリキャッシュ。

`RoadGraphEngine.prepare`/`preview_segment`は、リクエストごとに`build_lazy_road_graph`・
`compute_routable_node_ids`・`build_node_spatial_index`をbbox全体（数十万Edge規模）に
対して毎回作り直すと、温パスのprepare所要時間のほぼ全てを占めてしまう。
これらはタイル集合と0次フィルタ（`hard_filters`・`max_average_grade_percent`）だけで
決まる純粋な派生物のため、`graph_material_cache`と同じ「タイル集合キーのプロセス内
LRU」でキャッシュする。

**キャッシュキーは`frozenset[tuple[zoom, x, y]]`（bboxを覆うz12タイル集合）**。
`GraphService.get_search_materials_for_bbox`が「bboxを覆う全z12タイルの材料キャッシュを
そのまま結合したグラフ」を返した場合のみこの集合が得られる（`_build_search_materials_
from_tile_cache`経由）。split鮮度が古くbbox限定で再構築した場合（`_build_search_materials_
uncached`）はタイル集合がNoneになり、呼び出し側はこのキャッシュを経由しない——タイル境界と
一致しない不完全な集合を書き込むと、後続の正規リクエストへ不完全な結果を返しかねないため
（`graph_material_cache`が同じ理由でこのbboxを書き込まないのと同じ設計）。

無効化はプロセス寿命とLRUだけで、軸定義の変更とは無関係（静的スコア行列
[`tile_score_matrix_cache`]と違い、探索コストの値自体を持たないため）。
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Generic, TypeVar

from cachetools import LRUCache

if TYPE_CHECKING:
    from app.domain.routing import (
        LazyRoadGraph,
        NodeSpatialIndex,
        SearchGraphStatics,
        TurnCostSpec,
        TurnExpandedStructure,
    )

# 1エントリは「bbox全体を結合した後のグラフ・索引」で、`graph_material_cache`の
# タイル単位エントリよりずっと粗い。同時にホットな探索エリアはタイル数より少ないため、
# 上限も小さくてよい。
DEFAULT_MAX_ENTRIES = 64

# CSR構造一式（indptr/indices/entry_edge_index）や遷移数ぶんの配列を抱えるエントリは
# `LazyRoadGraph`より重いため、別の小さい上限で持つ。
SEARCH_STATICS_MAX_ENTRIES = 16

TileSet = frozenset[tuple[int, int, int]]
RoutableIndexKey = tuple[TileSet, "frozenset[str] | None", "float | None"]
# ターン展開構造のキー。遷移はタイル集合だけで決まるが、ターンの費用（秒）が変われば
# `turn_seconds`も変わるため、費用そのものをキーへ含める。
TurnStructureKey = tuple[TileSet, "TurnCostSpec"]

_K = TypeVar("_K")
_V = TypeVar("_V")


class _TileKeyedLru(Generic[_K, _V]):
    """タイル集合キー（またはそれを含むタプル）のプロセス内LRU。

    立ち退き自体は`cachetools.LRUCache`が担う。包みが要るのは、キーの条件一致でまとめて
    捨てる`pop_matching`のため。

    上限件数は`set`呼び出しのたびに引数で受け取り、変わっていたら内部のLRUを作り直す。
    """

    def __init__(self) -> None:
        self._entries: LRUCache = LRUCache(maxsize=1)

    def get(self, key: _K) -> "_V | None":
        return self._entries.get(key)

    def set(self, key: _K, value: _V, max_entries: int) -> None:
        if self._entries.maxsize != max_entries:
            kept = list(self._entries.items())[-max_entries:]
            self._entries = LRUCache(maxsize=max_entries)
            for kept_key, kept_value in kept:
                self._entries[kept_key] = kept_value
        self._entries[key] = value

    def pop(self, key: _K) -> None:
        self._entries.pop(key, None)

    def pop_matching(self, predicate: Callable[[_K], bool]) -> None:
        for key in [k for k in self._entries if predicate(k)]:
            self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()

    def size(self) -> int:
        return len(self._entries)


_lazy_graph_cache: "_TileKeyedLru[TileSet, LazyRoadGraph]" = _TileKeyedLru()
_search_statics_cache: "_TileKeyedLru[TileSet, SearchGraphStatics]" = _TileKeyedLru()
_routable_index_cache: "_TileKeyedLru[RoutableIndexKey, NodeSpatialIndex]" = _TileKeyedLru()
_turn_structure_cache: "_TileKeyedLru[TurnStructureKey, TurnExpandedStructure]" = _TileKeyedLru()
# 探索範囲ごとに学習した迂回率（往路木で測った「道なり距離÷直線距離」の中央値）。同じ
# タイル集合への次のリクエストが、往路レグの通過予定時刻の推定に使う。
_detour_ratio_cache: "_TileKeyedLru[TileSet, float]" = _TileKeyedLru()

# 上限はモジュール変数に持つ（テストがmonkeypatchして立ち退きを検証する）。
_max_entries = DEFAULT_MAX_ENTRIES
_search_statics_max_entries = SEARCH_STATICS_MAX_ENTRIES


def get_lazy_graph(tile_set: TileSet) -> "LazyRoadGraph | None":
    return _lazy_graph_cache.get(tile_set)


def set_lazy_graph(tile_set: TileSet, lazy_graph: "LazyRoadGraph") -> None:
    _lazy_graph_cache.set(tile_set, lazy_graph, _max_entries)


def get_search_statics(tile_set: TileSet) -> "SearchGraphStatics | None":
    return _search_statics_cache.get(tile_set)


def set_search_statics(tile_set: TileSet, statics: "SearchGraphStatics") -> None:
    _search_statics_cache.set(tile_set, statics, _search_statics_max_entries)


def get_detour_ratio(tile_set: TileSet) -> float | None:
    return _detour_ratio_cache.get(tile_set)


def set_detour_ratio(tile_set: TileSet, ratio: float) -> None:
    _detour_ratio_cache.set(tile_set, ratio, _max_entries)


def get_turn_structure(key: "TurnStructureKey") -> "TurnExpandedStructure | None":
    return _turn_structure_cache.get(key)


def set_turn_structure(key: "TurnStructureKey", structure: "TurnExpandedStructure") -> None:
    _turn_structure_cache.set(key, structure, _search_statics_max_entries)


def get_routable_index(key: RoutableIndexKey) -> "NodeSpatialIndex | None":
    return _routable_index_cache.get(key)


def set_routable_index(key: RoutableIndexKey, index: "NodeSpatialIndex") -> None:
    _routable_index_cache.set(key, index, _max_entries)


def invalidate_tile_set(tile_set: TileSet) -> None:
    """指定タイル集合のエントリを、このモジュールが持つキャッシュすべてから破棄する。

    各キャッシュはLRU上限に達すると独立に最古のエントリを追い出すため、同じ`tile_set`が
    一方には残り他方からは既に消えている状態になりうる。この状態で再splitが
    挟まると、残った側の`LazyRoadGraph`（古いedge_id集合）と新しく取得した`graph`
    （新edge_id集合）の組み合わせで`domain/routing.py: build_search_graph_statics`が
    KeyError相当（`LazyGraphEdgeMismatchError`）を起こす。検出したら本関数で該当
    `tile_set`を全キャッシュから破棄し、`RoadGraphEngine`側が`lazy_graph`ごと再構築する。
    タイル集合だけではないキーを持つキャッシュ（`_routable_index_cache`はハードフィルタ等、
    `_turn_structure_cache`はターン費用を併せて鍵にする）は、先頭要素が一致するものを
    すべて破棄する——区間idの集合そのものが変わるため、残りの鍵が何であれ再利用できない。
    """
    _lazy_graph_cache.pop(tile_set)
    _search_statics_cache.pop(tile_set)
    _routable_index_cache.pop_matching(lambda key: key[0] == tile_set)
    _turn_structure_cache.pop_matching(lambda key: key[0] == tile_set)
    _detour_ratio_cache.pop(tile_set)


def clear() -> None:
    """テスト用。キャッシュを全消去する（本番コードパスからは呼ばない）。"""
    _lazy_graph_cache.clear()
    _search_statics_cache.clear()
    _routable_index_cache.clear()
    _turn_structure_cache.clear()
    _detour_ratio_cache.clear()


def lazy_graph_cache_size() -> int:  # テストの検証用
    return _lazy_graph_cache.size()


def routable_index_cache_size() -> int:  # テストの検証用
    return _routable_index_cache.size()
