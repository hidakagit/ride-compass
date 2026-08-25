"""graph_material_cache.pyの単体テスト（改善計画T331）。

LRU立ち退きロジック（_LRUCache）本体と、tile単位キャッシュ・accident_years_coveredの
モジュールレベルAPIを検証する。
"""

from app.infrastructure import graph_material_cache
from app.infrastructure.graph_material_cache import _LRUCache


class TestLRUCache:
    def test_set_and_get_roundtrip(self):
        cache = _LRUCache(max_size=2)
        cache.set((12, 1, 1), "a")
        assert cache.get((12, 1, 1)) == "a"

    def test_get_missing_key_returns_none(self):
        cache = _LRUCache(max_size=2)
        assert cache.get((12, 0, 0)) is None

    def test_len_tracks_entry_count(self):
        cache = _LRUCache(max_size=5)
        cache.set((12, 1, 1), "a")
        cache.set((12, 1, 2), "b")
        assert len(cache) == 2

    def test_within_capacity_keeps_all_entries(self):
        cache = _LRUCache(max_size=3)
        cache.set((12, 1, 1), "a")
        cache.set((12, 1, 2), "b")
        cache.set((12, 1, 3), "c")
        assert len(cache) == 3
        assert cache.get((12, 1, 1)) == "a"

    def test_eviction_removes_least_recently_used_when_over_capacity(self):
        cache = _LRUCache(max_size=2)
        cache.set((12, 1, 1), "a")
        cache.set((12, 1, 2), "b")
        cache.set((12, 1, 3), "c")  # 最も古い(12,1,1)が立ち退く
        assert cache.get((12, 1, 1)) is None
        assert cache.get((12, 1, 2)) == "b"
        assert cache.get((12, 1, 3)) == "c"
        assert len(cache) == 2

    def test_get_marks_entry_as_recently_used_and_protects_from_eviction(self):
        cache = _LRUCache(max_size=2)
        cache.set((12, 1, 1), "a")
        cache.set((12, 1, 2), "b")
        cache.get((12, 1, 1))  # (12,1,1)を直近使用扱いに更新
        cache.set((12, 1, 3), "c")  # 次に古い(12,1,2)が立ち退く
        assert cache.get((12, 1, 1)) == "a"
        assert cache.get((12, 1, 2)) is None
        assert cache.get((12, 1, 3)) == "c"

    def test_set_existing_key_updates_value_and_recency(self):
        cache = _LRUCache(max_size=2)
        cache.set((12, 1, 1), "a")
        cache.set((12, 1, 2), "b")
        cache.set((12, 1, 1), "a2")  # 上書きも直近使用扱いになる
        cache.set((12, 1, 3), "c")  # (12,1,2)が立ち退く
        assert cache.get((12, 1, 1)) == "a2"
        assert cache.get((12, 1, 2)) is None
        assert cache.get((12, 1, 3)) == "c"

    def test_max_size_one_evicts_previous_entry_immediately(self):
        cache = _LRUCache(max_size=1)
        cache.set((12, 1, 1), "a")
        cache.set((12, 1, 2), "b")
        assert cache.get((12, 1, 1)) is None
        assert cache.get((12, 1, 2)) == "b"
        assert len(cache) == 1

    def test_clear_empties_cache(self):
        cache = _LRUCache(max_size=2)
        cache.set((12, 1, 1), "a")
        cache.clear()
        assert len(cache) == 0
        assert cache.get((12, 1, 1)) is None


class TestModuleLevelTileCacheApi:
    def setup_method(self):
        graph_material_cache.clear()

    def teardown_method(self):
        graph_material_cache.clear()

    def test_get_tile_materials_missing_returns_none(self):
        assert graph_material_cache.get_tile_materials(12, 1, 1) is None

    def test_set_then_get_tile_materials_roundtrip(self):
        materials = object()
        graph_material_cache.set_tile_materials(12, 5, 6, materials)
        assert graph_material_cache.get_tile_materials(12, 5, 6) is materials

    def test_tile_materials_are_keyed_by_zoom_x_y(self):
        materials_a = object()
        materials_b = object()
        graph_material_cache.set_tile_materials(12, 5, 6, materials_a)
        graph_material_cache.set_tile_materials(12, 5, 7, materials_b)
        assert graph_material_cache.get_tile_materials(12, 5, 6) is materials_a
        assert graph_material_cache.get_tile_materials(12, 5, 7) is materials_b

    def test_accident_years_covered_defaults_to_none(self):
        assert graph_material_cache.get_accident_years_covered() is None

    def test_set_then_get_accident_years_covered_roundtrip(self):
        graph_material_cache.set_accident_years_covered(5)
        assert graph_material_cache.get_accident_years_covered() == 5

    def test_clear_resets_tile_cache_and_accident_years(self):
        graph_material_cache.set_tile_materials(12, 1, 1, object())
        graph_material_cache.set_accident_years_covered(3)
        graph_material_cache.clear()
        assert graph_material_cache.get_tile_materials(12, 1, 1) is None
        assert graph_material_cache.get_accident_years_covered() is None
