"""search_graph_cache.pyの単体テスト（改善計画T537）。

タイル集合キーLRU（LazyRoadGraph用・NodeSpatialIndex用の2本）のget/set/LRU立ち退き・
clearを検証する。road_graph_engine.py経由のエンドツーエンド確認（キャッシュヒット時に
実際に構築関数が呼ばれないこと等）はtest_road_graph_engine.py側で行う。
"""

from app.infrastructure import search_graph_cache

_TILE_SET_A = frozenset({(12, 1, 1)})
_TILE_SET_B = frozenset({(12, 1, 2)})
_TILE_SET_C = frozenset({(12, 1, 3)})


class TestLazyGraphCache:
    def setup_method(self):
        search_graph_cache.clear()

    def teardown_method(self):
        search_graph_cache.clear()

    def test_get_missing_key_returns_none(self):
        assert search_graph_cache.get_lazy_graph(_TILE_SET_A) is None

    def test_set_then_get_roundtrip(self):
        lazy_graph = object()
        search_graph_cache.set_lazy_graph(_TILE_SET_A, lazy_graph)
        assert search_graph_cache.get_lazy_graph(_TILE_SET_A) is lazy_graph

    def test_entries_are_keyed_by_tile_set_not_by_membership_order(self):
        # frozensetはハッシュが要素順序に依存しないため、同じタイル集合を異なる順序で
        # 構築しても同一キーとして扱われることを確認する（GraphServiceが
        # frozenset((zoom,x,y) for x,y in tiles)を都度新規構築するため重要）。
        lazy_graph = object()
        key_built_one_way = frozenset([(12, 1, 1), (12, 1, 2)])
        key_built_other_way = frozenset([(12, 1, 2), (12, 1, 1)])
        search_graph_cache.set_lazy_graph(key_built_one_way, lazy_graph)
        assert search_graph_cache.get_lazy_graph(key_built_other_way) is lazy_graph

    def test_different_tile_sets_do_not_collide(self):
        graph_a, graph_b = object(), object()
        search_graph_cache.set_lazy_graph(_TILE_SET_A, graph_a)
        search_graph_cache.set_lazy_graph(_TILE_SET_B, graph_b)
        assert search_graph_cache.get_lazy_graph(_TILE_SET_A) is graph_a
        assert search_graph_cache.get_lazy_graph(_TILE_SET_B) is graph_b

    def test_size_tracks_entry_count(self):
        search_graph_cache.set_lazy_graph(_TILE_SET_A, object())
        search_graph_cache.set_lazy_graph(_TILE_SET_B, object())
        assert search_graph_cache.lazy_graph_cache_size() == 2

    def test_eviction_removes_least_recently_used_when_over_capacity(self, monkeypatch):
        monkeypatch.setattr(search_graph_cache, "_max_entries", 2)
        search_graph_cache.set_lazy_graph(_TILE_SET_A, "a")
        search_graph_cache.set_lazy_graph(_TILE_SET_B, "b")
        search_graph_cache.set_lazy_graph(_TILE_SET_C, "c")  # 最も古いAが立ち退く

        assert search_graph_cache.get_lazy_graph(_TILE_SET_A) is None
        assert search_graph_cache.get_lazy_graph(_TILE_SET_B) == "b"
        assert search_graph_cache.get_lazy_graph(_TILE_SET_C) == "c"
        assert search_graph_cache.lazy_graph_cache_size() == 2

    def test_get_marks_entry_as_recently_used_and_protects_from_eviction(self, monkeypatch):
        monkeypatch.setattr(search_graph_cache, "_max_entries", 2)
        search_graph_cache.set_lazy_graph(_TILE_SET_A, "a")
        search_graph_cache.set_lazy_graph(_TILE_SET_B, "b")
        search_graph_cache.get_lazy_graph(_TILE_SET_A)  # Aを直近使用扱いに更新
        search_graph_cache.set_lazy_graph(_TILE_SET_C, "c")  # 次に古いBが立ち退く

        assert search_graph_cache.get_lazy_graph(_TILE_SET_A) == "a"
        assert search_graph_cache.get_lazy_graph(_TILE_SET_B) is None
        assert search_graph_cache.get_lazy_graph(_TILE_SET_C) == "c"

    def test_clear_empties_cache(self):
        search_graph_cache.set_lazy_graph(_TILE_SET_A, object())
        search_graph_cache.clear()
        assert search_graph_cache.lazy_graph_cache_size() == 0
        assert search_graph_cache.get_lazy_graph(_TILE_SET_A) is None


class TestRoutableIndexCache:
    def setup_method(self):
        search_graph_cache.clear()

    def teardown_method(self):
        search_graph_cache.clear()

    def test_get_missing_key_returns_none(self):
        key = (_TILE_SET_A, None, None)
        assert search_graph_cache.get_routable_index(key) is None

    def test_set_then_get_roundtrip(self):
        index = object()
        key = (_TILE_SET_A, frozenset({"motorway"}), 8.0)
        search_graph_cache.set_routable_index(key, index)
        assert search_graph_cache.get_routable_index(key) is index

    def test_same_tile_set_with_different_hard_filters_are_separate_entries(self):
        # 改善計画T537: LazyRoadGraph（タイル集合のみ）と異なり、NodeSpatialIndexは
        # hard_filters/max_average_grade_percentも込みでキャッシュキーにする
        # （road_graph_engine.py: _get_or_build_node_index参照）。
        index_default = object()
        index_motorway_only = object()
        key_default = (_TILE_SET_A, None, None)
        key_motorway_only = (_TILE_SET_A, frozenset({"motorway"}), None)
        search_graph_cache.set_routable_index(key_default, index_default)
        search_graph_cache.set_routable_index(key_motorway_only, index_motorway_only)

        assert search_graph_cache.get_routable_index(key_default) is index_default
        assert search_graph_cache.get_routable_index(key_motorway_only) is index_motorway_only
        assert search_graph_cache.routable_index_cache_size() == 2

    def test_none_is_a_valid_cached_value_distinguishable_from_cache_miss(self):
        # 境界ケース: 0次フィルタで全Edgeが除外されるとNodeSpatialIndexはbucketsが
        # 空のまま構築される（Noneそのものではない、正当な「空だが実在する」結果）。
        # キャッシュ機構自体がこの区別を壊していないことを直接確認する
        # （「キー自体が無い」→get()はNone、「空の索引がキャッシュ済み」→get()は
        # その空オブジェクトを返す、の2つが取り違えられていないか）。
        empty_index = object()  # 空bucketsのNodeSpatialIndexの代わりに識別可能なsentinel
        key = (_TILE_SET_A, None, None)
        assert search_graph_cache.get_routable_index(key) is None  # 未キャッシュ

        search_graph_cache.set_routable_index(key, empty_index)
        assert search_graph_cache.get_routable_index(key) is empty_index  # キャッシュ済み

    def test_eviction_removes_least_recently_used_when_over_capacity(self, monkeypatch):
        monkeypatch.setattr(search_graph_cache, "_max_entries", 2)
        key_a = (_TILE_SET_A, None, None)
        key_b = (_TILE_SET_B, None, None)
        key_c = (_TILE_SET_C, None, None)
        search_graph_cache.set_routable_index(key_a, "a")
        search_graph_cache.set_routable_index(key_b, "b")
        search_graph_cache.set_routable_index(key_c, "c")

        assert search_graph_cache.get_routable_index(key_a) is None
        assert search_graph_cache.get_routable_index(key_b) == "b"
        assert search_graph_cache.get_routable_index(key_c) == "c"

    def test_clear_empties_cache(self):
        key = (_TILE_SET_A, None, None)
        search_graph_cache.set_routable_index(key, object())
        search_graph_cache.clear()
        assert search_graph_cache.routable_index_cache_size() == 0
        assert search_graph_cache.get_routable_index(key) is None

    def test_clear_empties_both_caches_together(self):
        search_graph_cache.set_lazy_graph(_TILE_SET_A, object())
        search_graph_cache.set_routable_index((_TILE_SET_A, None, None), object())
        search_graph_cache.clear()
        assert search_graph_cache.lazy_graph_cache_size() == 0
        assert search_graph_cache.routable_index_cache_size() == 0


class TestReverseSearchStaticsCache:
    """目的地ルートのvia-node方式（改善計画T551）が使う後ろ向き木用の転置CSRキャッシュ。
    エンドツーエンドの構築・キャッシュヒット確認はtest_road_graph_engine.py側で行う
    （search_statics_cacheと同じ役割分担）。"""

    def setup_method(self):
        search_graph_cache.clear()

    def teardown_method(self):
        search_graph_cache.clear()

    def test_get_missing_key_returns_none(self):
        assert search_graph_cache.get_reverse_search_statics(_TILE_SET_A) is None

    def test_set_then_get_roundtrip(self):
        statics = object()
        search_graph_cache.set_reverse_search_statics(_TILE_SET_A, statics)
        assert search_graph_cache.get_reverse_search_statics(_TILE_SET_A) is statics

    def test_forward_and_reverse_statics_are_separate_entries_for_the_same_tile_set(self):
        forward, reverse = object(), object()
        search_graph_cache.set_search_statics(_TILE_SET_A, forward)
        search_graph_cache.set_reverse_search_statics(_TILE_SET_A, reverse)

        assert search_graph_cache.get_search_statics(_TILE_SET_A) is forward
        assert search_graph_cache.get_reverse_search_statics(_TILE_SET_A) is reverse

    def test_size_tracks_entry_count(self):
        search_graph_cache.set_reverse_search_statics(_TILE_SET_A, object())
        search_graph_cache.set_reverse_search_statics(_TILE_SET_B, object())
        assert search_graph_cache.reverse_search_statics_cache_size() == 2

    def test_clear_empties_cache(self):
        search_graph_cache.set_reverse_search_statics(_TILE_SET_A, object())
        search_graph_cache.clear()
        assert search_graph_cache.reverse_search_statics_cache_size() == 0
        assert search_graph_cache.get_reverse_search_statics(_TILE_SET_A) is None


class TestSearchStaticsSeparateLruLimit:
    """`_search_statics_cache`/`_reverse_search_statics_cache`は`_lazy_graph_cache`/
    `_routable_index_cache`と別の上限（`_search_statics_max_entries`）を持つ
    （改善計画T568、1エントリがCSR構造一式でより重いため）。"""

    def setup_method(self):
        search_graph_cache.clear()

    def teardown_method(self):
        search_graph_cache.clear()

    def test_search_statics_eviction_uses_its_own_limit_independent_of_lazy_graph(self, monkeypatch):
        # lazy_graph用の上限（_max_entries）は緩いままでも、search_statics用の上限
        # （_search_statics_max_entries）だけを絞れば、search_statics側だけ立ち退く。
        monkeypatch.setattr(search_graph_cache, "_max_entries", 10)
        monkeypatch.setattr(search_graph_cache, "_search_statics_max_entries", 1)
        search_graph_cache.set_lazy_graph(_TILE_SET_A, "lazy-a")
        search_graph_cache.set_lazy_graph(_TILE_SET_B, "lazy-b")
        search_graph_cache.set_search_statics(_TILE_SET_A, "statics-a")
        search_graph_cache.set_search_statics(_TILE_SET_B, "statics-b")  # 上限1のためAが立ち退く

        assert search_graph_cache.get_lazy_graph(_TILE_SET_A) == "lazy-a"
        assert search_graph_cache.get_lazy_graph(_TILE_SET_B) == "lazy-b"
        assert search_graph_cache.get_search_statics(_TILE_SET_A) is None
        assert search_graph_cache.get_search_statics(_TILE_SET_B) == "statics-b"

    def test_reverse_search_statics_eviction_uses_the_same_separate_limit(self, monkeypatch):
        monkeypatch.setattr(search_graph_cache, "_search_statics_max_entries", 1)
        search_graph_cache.set_reverse_search_statics(_TILE_SET_A, "a")
        search_graph_cache.set_reverse_search_statics(_TILE_SET_B, "b")

        assert search_graph_cache.get_reverse_search_statics(_TILE_SET_A) is None
        assert search_graph_cache.get_reverse_search_statics(_TILE_SET_B) == "b"

    def test_invalidate_tile_set_discards_reverse_statics_alongside_other_caches(self):
        search_graph_cache.set_lazy_graph(_TILE_SET_A, object())
        search_graph_cache.set_search_statics(_TILE_SET_A, object())
        search_graph_cache.set_reverse_search_statics(_TILE_SET_A, object())
        search_graph_cache.set_reverse_search_statics(_TILE_SET_B, object())

        search_graph_cache.invalidate_tile_set(_TILE_SET_A)

        assert search_graph_cache.get_lazy_graph(_TILE_SET_A) is None
        assert search_graph_cache.get_search_statics(_TILE_SET_A) is None
        assert search_graph_cache.get_reverse_search_statics(_TILE_SET_A) is None
        assert search_graph_cache.reverse_search_statics_cache_size() == 1  # Bは影響を受けない
