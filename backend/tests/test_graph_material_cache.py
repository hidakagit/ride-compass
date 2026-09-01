"""graph_material_cache.pyの単体テスト（改善計画T331）。

LRU立ち退きロジック（_LRUCache）本体と、tile単位キャッシュ・accident_years_coveredの
モジュールレベルAPIを検証する。改善計画T538（ディスク永続化）以降は、プロセス再起動を
模した境界ケース（メモリだけ空にした状態からのディスク経由フォールバック）も検証する。
"""

from app.domain.attributes import SearchMaterials
from app.domain.graph import LeanRoadGraph
from app.infrastructure import graph_material_cache, tile_persistent_cache
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


class TestDiskPersistence:
    """改善計画T538: プロセス内メモリLRUだけでなく、ディスク永続化キャッシュ
    （infrastructure/tile_persistent_cache.py）を経由するフォールバック経路を検証する。

    本番の実態（デプロイでコンテナが再起動する）は「メモリキャッシュは空だが、前回の
    プロセスが書き込んだディスクキャッシュは残っている」状態のため、各テストは
    メモリLRUだけを空にしてディスクは温存する形で「プロセス再起動」を模す。
    """

    def setup_method(self):
        graph_material_cache.clear()

    def teardown_method(self):
        graph_material_cache.clear()

    def _sample_materials(self) -> SearchMaterials:
        return SearchMaterials(
            graph=LeanRoadGraph(graph_version="tile-cache", nodes={}, edges={}),
            materials={},
        )

    def test_get_falls_back_to_disk_when_memory_cache_is_empty(self):
        materials = self._sample_materials()
        graph_material_cache.set_tile_materials(12, 5, 6, materials)
        # メモリLRUだけを空にする（プロセス再起動直後の状態を模す。ディスクは温存）。
        graph_material_cache._tile_materials_cache.clear()

        restored = graph_material_cache.get_tile_materials(12, 5, 6)

        assert restored is not None
        assert restored.graph.graph_version == "tile-cache"

    def test_disk_hit_repopulates_memory_cache(self):
        materials = self._sample_materials()
        graph_material_cache.set_tile_materials(12, 5, 6, materials)
        graph_material_cache._tile_materials_cache.clear()

        graph_material_cache.get_tile_materials(12, 5, 6)

        # ディスクヒット後は、以後のアクセスがメモリLRUだけで完結する
        # （同一プロセス内で同じタイルへ再度ディスクI/Oを経由しない）。
        assert graph_material_cache._tile_materials_cache.get((12, 5, 6)) is not None

    def test_get_returns_none_when_neither_memory_nor_disk_has_the_tile(self):
        assert graph_material_cache.get_tile_materials(12, 9, 9) is None

    def test_clear_removes_disk_cache_too_not_only_memory(self):
        # clear()がメモリだけをクリアしディスクを残すと、次のget_tile_materialsが
        # ディスク経由で古い値を復元してしまう（軸編集直後・テスト間汚染と同種の不具合）。
        materials = self._sample_materials()
        graph_material_cache.set_tile_materials(12, 5, 6, materials)

        graph_material_cache.clear()

        assert graph_material_cache.get_tile_materials(12, 5, 6) is None

    def test_disk_cache_survives_across_two_independent_memory_lifetimes(self):
        # 2回連続でメモリだけを空にしても（複数回のデプロイ再起動を模す）、
        # ディスクキャッシュは明示的なclear()を挟まない限り生き続ける。
        materials = self._sample_materials()
        graph_material_cache.set_tile_materials(12, 5, 6, materials)

        graph_material_cache._tile_materials_cache.clear()
        assert graph_material_cache.get_tile_materials(12, 5, 6) is not None

        graph_material_cache._tile_materials_cache.clear()
        assert graph_material_cache.get_tile_materials(12, 5, 6) is not None

    def test_version_bump_makes_previously_persisted_tile_a_miss(self):
        # PBF再取込・precomputeバッチ実行後にTILE_MATERIALS_CACHE_VERSIONを手動で
        # 上げる運用（region_service.py: ROAD_SURFACE_TILE_VERSIONと同じ流儀）を模す。
        materials = self._sample_materials()
        graph_material_cache.set_tile_materials(12, 5, 6, materials)
        graph_material_cache._tile_materials_cache.clear()
        assert graph_material_cache.get_tile_materials(12, 5, 6) is not None

        old_version = graph_material_cache.TILE_MATERIALS_CACHE_VERSION
        try:
            graph_material_cache.TILE_MATERIALS_CACHE_VERSION = "999-simulated-next-generation"
            graph_material_cache._tile_materials_cache.clear()

            assert graph_material_cache.get_tile_materials(12, 5, 6) is None
        finally:
            graph_material_cache.TILE_MATERIALS_CACHE_VERSION = old_version

    def test_corrupted_disk_cache_file_falls_back_to_miss_without_raising(self):
        # T536・T537で「ローカルの単体テストは全green、本番の実際のデータで初めて例外」
        # という手戻りが発生した教訓（docs/tasks/T538.md）を踏まえ、ディスクキャッシュ
        # ファイルの破損もgraph_material_cache経由で例外を出さないことを確認する。
        materials = self._sample_materials()
        graph_material_cache.set_tile_materials(12, 5, 6, materials)
        graph_material_cache._tile_materials_cache.clear()
        path = tile_persistent_cache._tile_path(
            graph_material_cache._CACHE_NAMESPACE, graph_material_cache.TILE_MATERIALS_CACHE_VERSION, 12, 5, 6
        )
        path.write_bytes(b"\x00corrupted")

        assert graph_material_cache.get_tile_materials(12, 5, 6) is None

    def test_empty_tile_materials_round_trip_through_disk(self):
        # T536本番実測で判明した「bbox内の1タイルがEdge0件」ケース（combine_static_edge_
        # score_matricesの例外修正、docs/tasks/T536.md）の土台となる、Edge0件タイル自体の
        # 永続化・復元が正しく機能することを確認する。
        empty_materials = SearchMaterials(
            graph=LeanRoadGraph(graph_version="tile-cache-empty", nodes={}, edges={}),
            materials={},
        )
        graph_material_cache.set_tile_materials(12, 3, 3, empty_materials)
        graph_material_cache._tile_materials_cache.clear()

        restored = graph_material_cache.get_tile_materials(12, 3, 3)

        assert restored is not None
        assert restored.graph.edges == {}
        assert restored.graph.graph_version == "tile-cache-empty"
