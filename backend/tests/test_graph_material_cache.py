"""graph_material_cache.pyの単体テスト（改善計画T331）。

tile単位キャッシュ・accident_years_coveredのモジュールレベルAPIを検証する
（LRUの立ち退き自体は`cachetools.LRUCache`の責務のためここでは検証しない）。改善計画T538（ディスク永続化）以降は、プロセス再起動を
模した境界ケース（メモリだけ空にした状態からのディスク経由フォールバック）も検証する。
"""

from app.domain.attributes import SearchMaterials
from app.domain.graph import LeanRoadGraph
from app.infrastructure import graph_material_cache, tile_persistent_cache


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

    def test_disk_read_failure_falls_back_to_miss_without_raising(self, monkeypatch):
        # 破損エントリ・SQLite障害のいずれも「未キャッシュ」へ倒し、呼び出し元へ例外を
        # 伝播させないという契約を固定する（ローカルでは全greenでも本番の実データで
        # 初めて例外、という手戻りを防ぐ）。
        materials = self._sample_materials()
        graph_material_cache.set_tile_materials(12, 5, 6, materials)
        graph_material_cache._tile_materials_cache.clear()

        def broken_get(*args, **kwargs):
            raise ValueError("corrupted entry")

        monkeypatch.setattr(tile_persistent_cache.cache(), "get", broken_get)

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


class TestReadStats:
    """改善計画T546（対応方針項目6）: get_tile_materialsの`read_stats`引数が、
    メモリ/ディスクいずれを経由したかと、ディスク経由時のread_msを
    正しく書き込むことを確認する。"""

    def setup_method(self):
        graph_material_cache.clear()

    def teardown_method(self):
        graph_material_cache.clear()

    def _sample_materials(self) -> SearchMaterials:
        return SearchMaterials(
            graph=LeanRoadGraph(graph_version="tile-cache", nodes={}, edges={}), materials={},
        )

    def test_memory_hit_records_source_memory_without_disk_fields(self):
        graph_material_cache.set_tile_materials(12, 5, 6, self._sample_materials())

        stats: dict[str, object] = {}
        result = graph_material_cache.get_tile_materials(12, 5, 6, stats)

        assert result is not None
        assert stats == {"source": "memory"}

    def test_disk_hit_records_source_disk_with_read_ms(self):
        graph_material_cache.set_tile_materials(12, 5, 6, self._sample_materials())
        graph_material_cache._tile_materials_cache.clear()

        stats: dict[str, object] = {}
        result = graph_material_cache.get_tile_materials(12, 5, 6, stats)

        assert result is not None
        assert stats["source"] == "disk"
        assert stats["read_ms"] >= 0

    def test_miss_leaves_stats_untouched(self):
        stats: dict[str, object] = {}

        result = graph_material_cache.get_tile_materials(12, 9, 9, stats)

        assert result is None
        assert stats == {}

    def test_read_stats_argument_is_optional(self):
        graph_material_cache.set_tile_materials(12, 5, 6, self._sample_materials())

        assert graph_material_cache.get_tile_materials(12, 5, 6) is not None


def test_cached_table_signature_matches_current_columns():
    """`EdgeMaterialTable`の列構成を変えたら`TILE_MATERIALS_CACHE_VERSION`を上げる。

    このテーブルは`@dataclass(frozen=True, slots=True)`で、pickleの状態を**列の位置**で
    持つ（`dataclasses._dataclass_setstate`がfieldsとstateをzipする）。列を1つ足すと
    状態の長さが1つ足りなくなり、zipが短い方で止まるため**最後の列が設定されないまま**
    インスタンスが復元される。ディスクキャッシュはデプロイをまたいで残るので、版を
    上げ忘れると本番で最初にその列へ触れた場所がAttributeErrorで落ちる。
    """
    import dataclasses
    import hashlib

    from app.domain.attributes import EdgeMaterialTable
    from app.infrastructure.graph_material_cache import CACHED_TABLE_SIGNATURE

    names = ",".join(f.name for f in dataclasses.fields(EdgeMaterialTable))
    signature = hashlib.sha1(names.encode()).hexdigest()[:12]
    assert signature == CACHED_TABLE_SIGNATURE, (
        "EdgeMaterialTableの列構成が変わっている。"
        "TILE_MATERIALS_CACHE_VERSIONを上げ、CACHED_TABLE_SIGNATUREを"
        f"'{signature}'へ更新すること（古いディスクキャッシュを復元できなくなるため）。"
    )


def test_old_pickle_with_fewer_columns_loses_the_last_column():
    """列が1つ足りない状態から復元すると最後の列が欠ける、という壊れ方の実証。

    版を上げ忘れたときに何が起きるかを固定する（上のテストが守っている前提そのもの）。
    """
    import dataclasses

    from app.domain.attributes import EdgeMaterialTable

    fields = dataclasses.fields(EdgeMaterialTable)
    table = EdgeMaterialTable.from_bundles([], {})
    truncated = table.__getstate__()[:-1]  # 旧版のpickle状態（列が1つ少ない）を模す

    restored = object.__new__(EdgeMaterialTable)
    restored.__setstate__(truncated)

    assert not hasattr(restored, fields[-1].name)
