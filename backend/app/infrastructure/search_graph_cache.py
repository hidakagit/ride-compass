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
from collections.abc import Callable
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from app.domain.routing import LazyRoadGraph, NodeSpatialIndex, SearchGraphStatics

# bbox全体ぶんの結合済みグラフ・索引を保持するエントリのため、タイル単位キャッシュより
# 小さい上限にする（モジュールdocstring参照）。
DEFAULT_MAX_ENTRIES = 64

TileSet = frozenset[tuple[int, int, int]]
RoutableIndexKey = tuple[TileSet, "frozenset[str] | None", "float | None"]

_K = TypeVar("_K")
_V = TypeVar("_V")


class _TileKeyedLru(Generic[_K, _V]):
    """タイル集合キー（またはそれを含むタプル）のプロセス内LRU。get/set/pop/clear/sizeの
    定型実装を4キャッシュ（lazy_graph・search_statics・reverse_search_statics・
    routable_index）で共通化する（改善計画T557、項目18）。上限件数はモジュール変数`_max_entries`をテストが
    monkeypatchできるよう、`set`呼び出しのたびに引数で受け取る（インスタンスに固定値を
    持たせない）。
    """

    def __init__(self) -> None:
        self._entries: OrderedDict[_K, _V] = OrderedDict()

    def get(self, key: _K) -> "_V | None":
        value = self._entries.get(key)
        if value is not None:
            self._entries.move_to_end(key)
        return value

    def set(self, key: _K, value: _V, max_entries: int) -> None:
        self._entries[key] = value
        self._entries.move_to_end(key)
        if len(self._entries) > max_entries:
            self._entries.popitem(last=False)

    def pop(self, key: _K) -> None:
        self._entries.pop(key, None)

    def pop_matching(self, predicate: Callable[[_K], bool]) -> None:
        for key in [k for k in self._entries if predicate(k)]:
            self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()

    def size(self) -> int:
        return len(self._entries)


# 改善計画T531: 一対全最短経路木用のCSR構造＋Edge実距離配列（`domain/routing.py:
# SearchGraphStatics`）。LazyRoadGraphと同じくタイル集合だけで決まる派生物のため、
# 同じキー・同じ寿命で保持する。
_lazy_graph_cache: "_TileKeyedLru[TileSet, LazyRoadGraph]" = _TileKeyedLru()
_search_statics_cache: "_TileKeyedLru[TileSet, SearchGraphStatics]" = _TileKeyedLru()
# 目的地からの後ろ向き木（転置CSR）用。`_search_statics_cache`と同じタイル集合キー・
# 寿命だが、`csr`が転置されている点だけが異なる別インスタンスのため別キャッシュに分ける
# （目的地ルート生成時のみ構築、周回生成では使わない）。
_reverse_search_statics_cache: "_TileKeyedLru[TileSet, SearchGraphStatics]" = _TileKeyedLru()
_routable_index_cache: "_TileKeyedLru[RoutableIndexKey, NodeSpatialIndex]" = _TileKeyedLru()
_max_entries = DEFAULT_MAX_ENTRIES


def get_lazy_graph(tile_set: TileSet) -> "LazyRoadGraph | None":
    return _lazy_graph_cache.get(tile_set)


def set_lazy_graph(tile_set: TileSet, lazy_graph: "LazyRoadGraph") -> None:
    _lazy_graph_cache.set(tile_set, lazy_graph, _max_entries)


def get_search_statics(tile_set: TileSet) -> "SearchGraphStatics | None":
    return _search_statics_cache.get(tile_set)


def set_search_statics(tile_set: TileSet, statics: "SearchGraphStatics") -> None:
    _search_statics_cache.set(tile_set, statics, _max_entries)


def get_reverse_search_statics(tile_set: TileSet) -> "SearchGraphStatics | None":
    return _reverse_search_statics_cache.get(tile_set)


def set_reverse_search_statics(tile_set: TileSet, statics: "SearchGraphStatics") -> None:
    _reverse_search_statics_cache.set(tile_set, statics, _max_entries)


def get_routable_index(key: RoutableIndexKey) -> "NodeSpatialIndex | None":
    return _routable_index_cache.get(key)


def set_routable_index(key: RoutableIndexKey, index: "NodeSpatialIndex") -> None:
    _routable_index_cache.set(key, index, _max_entries)


def invalidate_tile_set(tile_set: TileSet) -> None:
    """指定タイル集合のエントリを4キャッシュ（`_lazy_graph_cache`・`_search_statics_cache`・
    `_reverse_search_statics_cache`・`_routable_index_cache`）すべてから破棄する
    （改善計画T557、項目4）。

    `_lazy_graph_cache`/`_search_statics_cache`/`_reverse_search_statics_cache`は
    LRU上限に達すると独立にpopitem(last=False)で最古のエントリを追い出すため、同じ
    `tile_set`が一方には残り他方からは既に消えている状態になりうる。この状態で再splitが
    挟まると、残った側の`LazyRoadGraph`（古いedge_id集合）と新しく取得した`graph`
    （新edge_id集合）の組み合わせで`domain/routing.py: build_search_graph_statics`が
    KeyError相当（`LazyGraphEdgeMismatchError`）を起こす。検出したら本関数で4キャッシュ
    とも該当`tile_set`を破棄し、`RoadGraphEngine`側が`lazy_graph`ごと再構築する。
    `_routable_index_cache`のキーは`(tile_set, hard_filters, max_average_grade_percent)`
    のタプルのため、先頭要素で一致するものをすべて破棄する。
    """
    _lazy_graph_cache.pop(tile_set)
    _search_statics_cache.pop(tile_set)
    _reverse_search_statics_cache.pop(tile_set)
    _routable_index_cache.pop_matching(lambda key: key[0] == tile_set)


def clear() -> None:
    """テスト用。キャッシュを全消去する（本番コードパスからは呼ばない）。"""
    _lazy_graph_cache.clear()
    _search_statics_cache.clear()
    _reverse_search_statics_cache.clear()
    _routable_index_cache.clear()


def lazy_graph_cache_size() -> int:  # テストの検証用
    return _lazy_graph_cache.size()


def search_statics_cache_size() -> int:  # テストの検証用
    return _search_statics_cache.size()


def reverse_search_statics_cache_size() -> int:  # テストの検証用
    return _reverse_search_statics_cache.size()


def routable_index_cache_size() -> int:  # テストの検証用
    return _routable_index_cache.size()
