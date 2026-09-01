"""tile_score_matrix_cache.pyの単体テスト（改善計画T536のキャッシュ本体、T538でディスク
永続化を追加）。

プロセス内メモリLRU・ディスク永続化フォールバック（プロセス再起動を模した境界ケース）・
軸定義編集時の即時無効化（clear()がメモリ・ディスク両方を削除すること）を検証する。
"""

import numpy as np
import pytest

from app.domain.evaluation import StaticEdgeScoreMatrix
from app.infrastructure import tile_persistent_cache, tile_score_matrix_cache


def _sample_matrix(edge_id: str = "edge-1", score: float = 50.0) -> StaticEdgeScoreMatrix:
    return StaticEdgeScoreMatrix(
        edge_ids=[edge_id],
        axis_ids=["gradient"],
        axis_scores=np.array([[score]]),
        distance_m=np.array([100.0]),
        bearing_deg=np.array([np.nan]),
        is_motorway=np.array([False]),
        is_trunk=np.array([False]),
        no_bicycle=np.array([False]),
        gradient_percent=np.array([np.nan]),
    )


def _empty_matrix() -> StaticEdgeScoreMatrix:
    # T536本番実測で判明した「bbox内の1タイルがEdge0件」ケース（docs/tasks/T536.md）の
    # 土台となる、Edge0件タイルの静的スコア行列自体の形状。
    return StaticEdgeScoreMatrix(
        edge_ids=[],
        axis_ids=["gradient"],
        axis_scores=np.zeros((0, 1)),
        distance_m=np.zeros(0),
        bearing_deg=np.zeros(0),
        is_motorway=np.zeros(0, dtype=bool),
        is_trunk=np.zeros(0, dtype=bool),
        no_bicycle=np.zeros(0, dtype=bool),
        gradient_percent=np.zeros(0),
    )


@pytest.fixture(autouse=True)
def _clear_around_each_test():
    tile_score_matrix_cache.clear()
    yield
    tile_score_matrix_cache.clear()


class TestModuleLevelApi:
    def test_get_missing_returns_none(self):
        assert tile_score_matrix_cache.get(12, 1, 1) is None

    def test_set_then_get_roundtrip(self):
        matrix = _sample_matrix()
        tile_score_matrix_cache.set(12, 5, 6, matrix)

        assert tile_score_matrix_cache.get(12, 5, 6) is matrix

    def test_tiles_are_keyed_by_zoom_x_y(self):
        matrix_a = _sample_matrix("edge-a")
        matrix_b = _sample_matrix("edge-b")
        tile_score_matrix_cache.set(12, 5, 6, matrix_a)
        tile_score_matrix_cache.set(12, 5, 7, matrix_b)

        assert tile_score_matrix_cache.get(12, 5, 6) is matrix_a
        assert tile_score_matrix_cache.get(12, 5, 7) is matrix_b

    def test_size_reflects_memory_entry_count(self):
        assert tile_score_matrix_cache.size() == 0
        tile_score_matrix_cache.set(12, 1, 1, _sample_matrix())
        assert tile_score_matrix_cache.size() == 1

    def test_clear_empties_memory_cache(self):
        tile_score_matrix_cache.set(12, 1, 1, _sample_matrix())
        tile_score_matrix_cache.clear()
        assert tile_score_matrix_cache.get(12, 1, 1) is None
        assert tile_score_matrix_cache.size() == 0

    def test_lru_eviction_when_over_capacity(self, monkeypatch):
        monkeypatch.setattr(tile_score_matrix_cache, "_max_entries", 2)
        tile_score_matrix_cache.set(12, 1, 1, _sample_matrix("e1"))
        tile_score_matrix_cache.set(12, 1, 2, _sample_matrix("e2"))
        tile_score_matrix_cache.set(12, 1, 3, _sample_matrix("e3"))  # (12,1,1)が立ち退く

        assert tile_score_matrix_cache.size() == 2
        # メモリからは立ち退いたが、ディスクには残っているため取得はできる
        # （立ち退き=消去ではないことの確認。get_tile_materialsと対称の設計）。
        assert tile_score_matrix_cache.get(12, 1, 1) is not None


class TestDiskPersistence:
    """改善計画T538: プロセス再起動を模した境界ケース（メモリだけを空にした状態からの
    ディスク経由フォールバック）を検証する。"""

    def test_get_falls_back_to_disk_when_memory_cache_is_empty(self):
        matrix = _sample_matrix()
        tile_score_matrix_cache.set(12, 5, 6, matrix)
        tile_score_matrix_cache._cache.clear()  # メモリだけ空にする（プロセス再起動を模す）

        restored = tile_score_matrix_cache.get(12, 5, 6)

        assert restored is not None
        assert restored.edge_ids == ["edge-1"]
        assert restored is not matrix  # ディスク経由はデシリアライズされた別オブジェクト

    def test_disk_hit_repopulates_memory_cache(self):
        tile_score_matrix_cache.set(12, 5, 6, _sample_matrix())
        tile_score_matrix_cache._cache.clear()

        tile_score_matrix_cache.get(12, 5, 6)

        assert tile_score_matrix_cache.size() == 1

    def test_clear_removes_disk_cache_too_not_only_memory(self):
        tile_score_matrix_cache.set(12, 5, 6, _sample_matrix())

        tile_score_matrix_cache.clear()

        assert tile_score_matrix_cache.get(12, 5, 6) is None

    def test_version_bump_makes_previously_persisted_tile_a_miss(self):
        # PBF再取込・precomputeバッチ・build_static_edge_score_matrix自体の計算式変更後に
        # TILE_SCORE_MATRIX_CACHE_VERSIONを手動で上げる運用を模す。
        tile_score_matrix_cache.set(12, 5, 6, _sample_matrix())
        tile_score_matrix_cache._cache.clear()
        assert tile_score_matrix_cache.get(12, 5, 6) is not None

        old_version = tile_score_matrix_cache.TILE_SCORE_MATRIX_CACHE_VERSION
        try:
            tile_score_matrix_cache.TILE_SCORE_MATRIX_CACHE_VERSION = "999-simulated-next-generation"
            tile_score_matrix_cache._cache.clear()

            assert tile_score_matrix_cache.get(12, 5, 6) is None
        finally:
            tile_score_matrix_cache.TILE_SCORE_MATRIX_CACHE_VERSION = old_version

    def test_corrupted_disk_cache_file_falls_back_to_miss_without_raising(self):
        tile_score_matrix_cache.set(12, 5, 6, _sample_matrix())
        tile_score_matrix_cache._cache.clear()
        path = tile_persistent_cache._tile_path(
            tile_score_matrix_cache._CACHE_NAMESPACE,
            tile_score_matrix_cache.TILE_SCORE_MATRIX_CACHE_VERSION,
            12, 5, 6,
        )
        path.write_bytes(b"\x00corrupted")

        assert tile_score_matrix_cache.get(12, 5, 6) is None

    def test_empty_edge_score_matrix_round_trips_through_disk(self):
        # T536本番実測で判明した空タイル（Edge0件）ケースの土台。
        tile_score_matrix_cache.set(12, 3, 3, _empty_matrix())
        tile_score_matrix_cache._cache.clear()

        restored = tile_score_matrix_cache.get(12, 3, 3)

        assert restored is not None
        assert restored.edge_ids == []
        assert restored.axis_scores.shape == (0, 1)

    def test_axis_definition_edit_invalidates_disk_cache_not_just_memory(self):
        # test_axis_registry_service.py::test_refresh_clears_tile_score_matrix_cacheが
        # refresh_axis_definitions経由でclear()が呼ばれることを検証している。ここでは
        # 「メモリだけでなくディスクも消える」という本モジュール固有の契約を直接検証する
        # （clear()だけがメモリのみだった場合、軸編集後もプロセス再起動を挟むと編集前の
        # スコアがディスクから復元されてしまう不具合の回帰）。
        tile_score_matrix_cache.set(12, 1, 1, _sample_matrix())

        tile_score_matrix_cache.clear()  # 軸定義編集を模す

        tile_score_matrix_cache._cache.clear()  # さらにプロセス再起動を模す
        assert tile_score_matrix_cache.get(12, 1, 1) is None
