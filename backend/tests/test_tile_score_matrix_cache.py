"""tile_score_matrix_cache.pyの単体テスト（改善計画T536のキャッシュ本体、T538でディスク
永続化を追加）。

プロセス内メモリLRU・ディスク永続化フォールバック（プロセス再起動を模した境界ケース）・
軸定義編集時の即時無効化（clear()がメモリ・ディスク両方を削除すること）を検証する。
"""

import numpy as np
import pytest

from cachetools import LRUCache

from app.domain.evaluation import (
    StaticEdgeScoreMatrix,
    route_facing_categorical_material_ids,
    route_facing_material_ids,
    route_facing_raw_axis_ids,
)
from app.infrastructure import graph_material_cache, tile_persistent_cache, tile_score_matrix_cache


def _columns(rows: int) -> dict:
    """可変長の列を、いまの述語どおりに揃える。

    読み出し時の検証（`_columns_match_current_predicates`）が現在の述語と突き合わせるため、
    ここを固定値で書くと「述語が変わった」のか「フィクスチャが古い」のか区別できなくなる。
    """
    raw_ids = route_facing_raw_axis_ids()
    material_ids = route_facing_material_ids()
    categorical_ids = route_facing_categorical_material_ids()
    return dict(
        raw_axis_ids=raw_ids,
        axis_raw_values=np.zeros((rows, len(raw_ids))),
        material_ids=material_ids,
        material_values=np.zeros((rows, len(material_ids))),
        categorical_material_ids=categorical_ids,
        categorical_material_values=np.empty((rows, len(categorical_ids)), dtype=object),
    )


def _sample_matrix(edge_id: str = "edge-1", score: float = 50.0) -> StaticEdgeScoreMatrix:
    return StaticEdgeScoreMatrix(
        **_columns(1),
        edge_ids=[edge_id],
        axis_ids=["gradient"],
        axis_scores=np.array([[score]]),
        distance_m=np.array([100.0]),
        bearing_deg=np.array([np.nan]),
        highway_filter_flags={"motorway": np.array([False]), "trunk": np.array([False])},
        no_bicycle=np.array([False]),
        gradient_percent=np.array([np.nan]),
        mid_lat=np.array([35.0]),
        mid_lon=np.array([139.0]),
    )


def _empty_matrix() -> StaticEdgeScoreMatrix:
    # T536本番実測で判明した「bbox内の1タイルがEdge0件」ケース（docs/tasks/T536.md）の
    # 土台となる、Edge0件タイルの静的スコア行列自体の形状。
    return StaticEdgeScoreMatrix(
        **_columns(0),
        edge_ids=[],
        axis_ids=["gradient"],
        axis_scores=np.zeros((0, 1)),
        distance_m=np.zeros(0),
        bearing_deg=np.zeros(0),
        highway_filter_flags={"motorway": np.zeros(0, dtype=bool), "trunk": np.zeros(0, dtype=bool)},
        no_bicycle=np.zeros(0, dtype=bool),
        gradient_percent=np.zeros(0),
        mid_lat=np.zeros(0),
        mid_lon=np.zeros(0),
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
        monkeypatch.setattr(tile_score_matrix_cache, "_cache", LRUCache(maxsize=2))
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

    def test_disk_read_failure_falls_back_to_miss_without_raising(self, monkeypatch):
        # 破損エントリ・SQLite障害のいずれも「未キャッシュ」へ倒し、呼び出し元へ例外を
        # 伝播させないという契約を固定する。
        matrix = _sample_matrix()
        tile_score_matrix_cache.set(12, 5, 6, matrix)
        tile_score_matrix_cache._cache.clear()

        def broken_get(*args, **kwargs):
            raise ValueError("corrupted entry")

        monkeypatch.setattr(tile_persistent_cache.cache(), "get", broken_get)

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


class TestReadStats:
    """改善計画T546（対応方針項目6）: getの`read_stats`引数がgraph_material_cacheと
    同じ意味論で動くことを確認する。"""

    def test_memory_hit_records_source_memory(self):
        tile_score_matrix_cache.set(12, 5, 6, _sample_matrix())

        stats: dict[str, object] = {}
        result = tile_score_matrix_cache.get(12, 5, 6, stats)

        assert result is not None
        assert stats == {"source": "memory"}

    def test_disk_hit_records_source_disk_with_read_ms(self):
        tile_score_matrix_cache.set(12, 5, 6, _sample_matrix())
        tile_score_matrix_cache._cache.clear()

        stats: dict[str, object] = {}
        result = tile_score_matrix_cache.get(12, 5, 6, stats)

        assert result is not None
        assert stats["source"] == "disk"
        assert stats["read_ms"] >= 0

    def test_miss_leaves_stats_untouched(self):
        stats: dict[str, object] = {}

        result = tile_score_matrix_cache.get(12, 9, 9, stats)

        assert result is None
        assert stats == {}


class TestSyncDiskCacheWithAxisRevision:
    """改善計画T546フォローアップ: 本番の使い捨てコンテナ検証で発覚した不具合
    （`refresh_axis_definitions`がアプリ起動のたびに軸定義が変わっていなくても
    `tile_score_matrix_cache`のディスクキャッシュを無条件で丸ごと再構築していた
    ——materials（ディスクヒット）とscore_matrix（毎回db）の非対称が生じ、
    `materials_ms`の大半を占めていた）の回帰テスト。`sync_disk_cache_with_axis_revision`が
    「revisionが前回ディスク永続化時と同じなら温存、違えば無効化」を正しく行うことを
    直接検証する。"""

    def test_first_call_with_no_prior_marker_clears_and_records_revision(self):
        # 初回デプロイ相当（ディスクにrevisionマーカーがまだ無い）。安全側でclear()し、
        # 新しいrevisionを記録する。
        tile_score_matrix_cache.set(12, 5, 6, _sample_matrix())

        tile_score_matrix_cache.sync_disk_cache_with_axis_revision(1)

        assert tile_score_matrix_cache.get(12, 5, 6) is None
        assert tile_score_matrix_cache._read_persisted_axis_revision() == 1

    def test_same_revision_across_simulated_restart_preserves_disk_cache(self):
        # 実際のコンテナ再起動を模す: revision記録→ディスクへ書き込み→メモリだけ空にする
        # （プロセス再起動）→同じrevisionでsync呼び出し（次の起動時のrefresh_axis_
        # definitions相当）→ディスクキャッシュがそのまま復元できること。
        tile_score_matrix_cache.sync_disk_cache_with_axis_revision(5)
        tile_score_matrix_cache.set(12, 5, 6, _sample_matrix())
        tile_score_matrix_cache._cache.clear()  # プロセス再起動（メモリだけ空になる）を模す

        tile_score_matrix_cache.sync_disk_cache_with_axis_revision(5)  # 次回起動時のrefresh

        restored = tile_score_matrix_cache.get(12, 5, 6)
        assert restored is not None
        assert restored.edge_ids == ["edge-1"]

    def test_changed_revision_clears_disk_cache_and_records_new_revision(self):
        # 実際の軸編集を模す: revision=5で書き込み済みのディスクキャッシュが、
        # revision=6（軸定義が実際に変わった）でのsync呼び出し後は見えなくなる。
        tile_score_matrix_cache.sync_disk_cache_with_axis_revision(5)
        tile_score_matrix_cache.set(12, 5, 6, _sample_matrix())
        tile_score_matrix_cache._cache.clear()

        tile_score_matrix_cache.sync_disk_cache_with_axis_revision(6)

        assert tile_score_matrix_cache.get(12, 5, 6) is None
        assert tile_score_matrix_cache._read_persisted_axis_revision() == 6

    def test_rebuilt_cache_after_revision_change_persists_across_next_restart(self):
        # revision変更で無効化された後、新しいrevisionのもとで再構築されたキャッシュは、
        # 以後の（revision不変の）再起動では正しく温存される。
        tile_score_matrix_cache.sync_disk_cache_with_axis_revision(5)
        tile_score_matrix_cache.set(12, 5, 6, _sample_matrix())
        tile_score_matrix_cache._cache.clear()

        tile_score_matrix_cache.sync_disk_cache_with_axis_revision(6)  # 軸編集
        tile_score_matrix_cache.set(12, 5, 6, _sample_matrix("edge-1", score=99.0))  # 再構築
        tile_score_matrix_cache._cache.clear()  # 次の再起動

        tile_score_matrix_cache.sync_disk_cache_with_axis_revision(6)  # revision不変の再起動
        restored = tile_score_matrix_cache.get(12, 5, 6)

        assert restored is not None
        assert restored.axis_scores[0, 0] == 99.0

    def test_none_revision_is_conservative_and_always_clears(self):
        # axis_registry_metaに行が無い等の想定外の状態ではrevisionがNoneになりうる。
        # 安全側に倒し、毎回clear()する（マーカーも記録しない）。
        tile_score_matrix_cache.set(12, 5, 6, _sample_matrix())

        tile_score_matrix_cache.sync_disk_cache_with_axis_revision(None)

        assert tile_score_matrix_cache.get(12, 5, 6) is None
        assert tile_score_matrix_cache._read_persisted_axis_revision() is None

    def test_revision_marker_does_not_collide_with_real_tile_coordinates(self):
        # 予約座標(zoom=-1, x=0, y=0)が実タイル(zoom=12等)と独立して扱われることの確認。
        tile_score_matrix_cache.sync_disk_cache_with_axis_revision(3)
        tile_score_matrix_cache.set(12, 0, 0, _sample_matrix("edge-real"))

        assert tile_score_matrix_cache.get(12, 0, 0) is not None
        assert tile_score_matrix_cache.get(12, 0, 0).edge_ids == ["edge-real"]
        assert tile_score_matrix_cache._read_persisted_axis_revision() == 3


# --- キャッシュ世代の従属関係（材料世代が変わればスコア行列も無効になる） ---


def test_cache_version_changes_when_materials_version_changes(monkeypatch):
    # この行列は材料（graph_material_cache）からの派生物のため、材料世代が変われば必ず
    # 無効になる必要がある。片方だけ変わると「graphには在るがscore_matrix.edge_idsには
    # 無いedge_id」が生じ、そのbboxのルート生成がディスクキャッシュを手で消すまで復旧しない。
    import importlib

    before = tile_score_matrix_cache.TILE_SCORE_MATRIX_CACHE_VERSION
    monkeypatch.setattr(graph_material_cache, "TILE_MATERIALS_CACHE_VERSION", "999-zzz")
    reloaded = importlib.reload(tile_score_matrix_cache)
    try:
        assert reloaded.TILE_SCORE_MATRIX_CACHE_VERSION != before
    finally:
        monkeypatch.undo()
        importlib.reload(tile_score_matrix_cache)


class TestColumnValidationOnRead:
    """可変長の列（raw_axis_ids/material_ids/categorical_material_ids）は
    `dataclasses.fields()`に現れない**中身で決まる列**で、鍵の署名では捕まえられない。
    列を決める述語はこのモジュールを触らずに変えられるため、読み出し時に突き合わせる。
    """

    def test_stale_columns_are_treated_as_a_miss(self, monkeypatch):
        tile_score_matrix_cache.set(12, 5, 6, _sample_matrix())
        tile_score_matrix_cache._cache.clear()
        assert tile_score_matrix_cache.get(12, 5, 6) is not None

        # 述語が列を1つ増やした状況（＝保存済みは1つ足りない）。
        tile_score_matrix_cache._cache.clear()
        monkeypatch.setattr(
            tile_score_matrix_cache, "route_facing_material_ids",
            lambda: [*route_facing_material_ids(), "zzz_added_material"],
        )

        stats: dict[str, object] = {}
        assert tile_score_matrix_cache.get(12, 5, 6, stats) is None
        assert stats["source"] == "stale_columns"

    def test_matching_columns_still_hit(self):
        tile_score_matrix_cache.set(12, 5, 6, _sample_matrix())
        tile_score_matrix_cache._cache.clear()

        assert tile_score_matrix_cache.get(12, 5, 6) is not None
