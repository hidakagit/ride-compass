"""tile_persistent_cache.pyの単体テスト（改善計画T538）。

タイル単位の複雑なPythonオブジェクトをディスクへpickle永続化する汎用キャッシュ本体を
検証する。境界ケース（キャッシュ不在・ファイル破損/部分書き込み・世代不一致・
namespace分離）を通常のroundtripケースと同じ優先度でカバーする（改善計画T536・T537で
本番実測まで発覚しなかった不具合の教訓、docs/tasks/T538.md参照）。
"""

import pickle

import pytest

from app.infrastructure import tile_persistent_cache


class _DummyForRoundtrip:
    """`SearchMaterials`・`StaticEdgeScoreMatrix`のような任意のPythonオブジェクトの
    pickle roundtripを確認するための最小のテスト用クラス（モジュール直下に置く必要が
    ある。pickleはトップレベル定義のクラスしか復元できないため）。"""

    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return isinstance(other, _DummyForRoundtrip) and other.value == self.value


@pytest.fixture(autouse=True)
def use_temp_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tile_persistent_cache, "CACHE_DIR", tmp_path / "tile_persistent_cache")


def test_get_returns_none_when_not_cached():
    assert tile_persistent_cache.get("materials", "1", 12, 1, 1) is None


def test_set_then_get_roundtrip():
    tile_persistent_cache.set("materials", "1", 12, 5, 6, {"edges": ["e1", "e2"]})

    result = tile_persistent_cache.get("materials", "1", 12, 5, 6)

    assert result == {"edges": ["e1", "e2"]}


def test_roundtrip_preserves_arbitrary_picklable_object_not_just_plain_types():
    # pickleはモジュールトップレベルで定義されたクラスのみ復元できる（テスト関数内の
    # ローカルクラスはpickle化不能なため、_DummyForRoundtripはモジュール直下に置く）。
    tile_persistent_cache.set("materials", "1", 12, 1, 1, _DummyForRoundtrip("payload"))

    assert tile_persistent_cache.get("materials", "1", 12, 1, 1) == _DummyForRoundtrip("payload")


def test_different_tile_coordinates_are_independent():
    tile_persistent_cache.set("materials", "1", 12, 5, 6, "a")
    tile_persistent_cache.set("materials", "1", 12, 5, 7, "b")

    assert tile_persistent_cache.get("materials", "1", 12, 5, 6) == "a"
    assert tile_persistent_cache.get("materials", "1", 12, 5, 7) == "b"


def test_different_namespaces_are_independent_even_for_the_same_tile():
    # graph_material_cache（"materials"）とtile_score_matrix_cache（"score_matrix"）が
    # 同じタイル座標を使っても互いのキャッシュを踏まないことを確認する。
    tile_persistent_cache.set("materials", "1", 12, 1, 1, "materials-value")
    tile_persistent_cache.set("score_matrix", "1", 12, 1, 1, "score-matrix-value")

    assert tile_persistent_cache.get("materials", "1", 12, 1, 1) == "materials-value"
    assert tile_persistent_cache.get("score_matrix", "1", 12, 1, 1) == "score-matrix-value"


# --- 境界ケース: 世代不一致（PBF再取込・precomputeバッチ実行後の無効化）---

def test_version_mismatch_is_treated_as_cache_miss():
    # region_service.py: ROAD_SURFACE_TILE_VERSIONと同じ流儀。バージョン文字列が違えば
    # 別のファイルパスとして扱われ、旧世代の内容は新世代からは見えない。
    tile_persistent_cache.set("materials", "1", 12, 1, 1, "old-generation-value")

    assert tile_persistent_cache.get("materials", "2", 12, 1, 1) is None
    # 旧世代のパスからは引き続き読める（明示的な削除は行わない設計）。
    assert tile_persistent_cache.get("materials", "1", 12, 1, 1) == "old-generation-value"


def test_bumping_version_after_batch_rerun_makes_old_cache_invisible():
    # PBF再取込・precomputeバッチを実行した運用を模す: 旧世代で書き込み済みのキャッシュが
    # あっても、バージョンを上げた後は新しい値を書き込むまでミスとして扱われる。
    tile_persistent_cache.set("materials", "1", 12, 1, 1, "before-batch")
    assert tile_persistent_cache.get("materials", "1", 12, 1, 1) == "before-batch"

    new_version = "2"
    assert tile_persistent_cache.get("materials", new_version, 12, 1, 1) is None

    tile_persistent_cache.set("materials", new_version, 12, 1, 1, "after-batch")
    assert tile_persistent_cache.get("materials", new_version, 12, 1, 1) == "after-batch"


# --- 境界ケース: ファイル破損・部分書き込み ---

def test_corrupted_pickle_file_is_treated_as_cache_miss_not_raised():
    tile_persistent_cache.set("materials", "1", 12, 1, 1, "valid-value")
    path = tile_persistent_cache._tile_path("materials", "1", 12, 1, 1)
    path.write_bytes(b"not a valid pickle stream \x00\x01\xff")

    # 例外を送出せずNoneへフォールバックする（tile_cache.pyのget()と同じ方針）。
    assert tile_persistent_cache.get("materials", "1", 12, 1, 1) is None


def test_truncated_pickle_file_from_partial_write_is_treated_as_cache_miss():
    # プロセスが書き込み途中で落ちた場合を模す（アトミック差し替え自体は壊れないが、
    # 何らかの理由で不完全なファイルが最終パスに存在するケースへの防御）。
    tile_persistent_cache.set("materials", "1", 12, 1, 1, {"key": "value" * 100})
    path = tile_persistent_cache._tile_path("materials", "1", 12, 1, 1)
    full_bytes = path.read_bytes()
    path.write_bytes(full_bytes[: len(full_bytes) // 2])

    assert tile_persistent_cache.get("materials", "1", 12, 1, 1) is None


def test_empty_file_is_treated_as_cache_miss():
    path = tile_persistent_cache._tile_path("materials", "1", 12, 1, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")

    assert tile_persistent_cache.get("materials", "1", 12, 1, 1) is None


# --- 境界ケース: 書き込み失敗のno-opフォールバック ---

def test_set_swallows_unpicklable_value_and_logs_instead_of_raising():
    unpicklable = lambda: None  # noqa: E731 関数オブジェクトは既定でpickle化できない

    # 例外を送出せずno-opにフォールバックする（呼び出し元のレスポンスを止めない）。
    tile_persistent_cache.set("materials", "1", 12, 1, 1, unpicklable)

    assert tile_persistent_cache.get("materials", "1", 12, 1, 1) is None


# --- 一部タイルが空（Edge0件）のケースに相当する境界値 ---

def test_roundtrip_preserves_falsy_and_empty_values():
    # 空グラフ相当（Edge0件のタイル、T536本番実測で発覚した混在ケースの土台）。
    # 空dict/空listはNoneと区別されなければならない（getのNone=未キャッシュと衝突しない）。
    tile_persistent_cache.set("materials", "1", 12, 9, 9, {})

    result = tile_persistent_cache.get("materials", "1", 12, 9, 9)

    assert result == {}
    assert result is not None


# --- clear_namespace / clear_all ---

def test_clear_namespace_removes_only_that_namespace():
    tile_persistent_cache.set("materials", "1", 12, 1, 1, "materials-value")
    tile_persistent_cache.set("score_matrix", "1", 12, 1, 1, "score-matrix-value")

    tile_persistent_cache.clear_namespace("materials")

    assert tile_persistent_cache.get("materials", "1", 12, 1, 1) is None
    assert tile_persistent_cache.get("score_matrix", "1", 12, 1, 1) == "score-matrix-value"


def test_clear_namespace_on_absent_namespace_does_not_raise():
    tile_persistent_cache.clear_namespace("never-written")


def test_clear_all_removes_every_namespace():
    tile_persistent_cache.set("materials", "1", 12, 1, 1, "a")
    tile_persistent_cache.set("score_matrix", "1", 12, 1, 1, "b")

    tile_persistent_cache.clear_all()

    assert tile_persistent_cache.get("materials", "1", 12, 1, 1) is None
    assert tile_persistent_cache.get("score_matrix", "1", 12, 1, 1) is None


# --- アトミック書き込みの回帰（tile_cache.py: T464相当）---

def test_set_leaves_no_temp_files_behind():
    tile_persistent_cache.set("materials", "1", 12, 1, 1, "value")

    path = tile_persistent_cache._tile_path("materials", "1", 12, 1, 1)
    leftover_tmp_files = list(path.parent.glob("*.tmp-*"))
    assert leftover_tmp_files == []


def test_set_overwrite_replaces_previous_value_atomically():
    tile_persistent_cache.set("materials", "1", 12, 1, 1, "first")
    tile_persistent_cache.set("materials", "1", 12, 1, 1, "second")

    assert tile_persistent_cache.get("materials", "1", 12, 1, 1) == "second"


def test_pickle_error_on_read_is_caught_broadly(monkeypatch):
    # UnpicklingError以外（AttributeError/ImportError等クラス定義変更相当）も拾えることを
    # 直接確認する。pickle.loadをエラーが起きるものへ差し替えて検証する。
    tile_persistent_cache.set("materials", "1", 12, 1, 1, "value")

    def _boom(_file):
        raise AttributeError("class moved")

    monkeypatch.setattr(pickle, "load", _boom)

    assert tile_persistent_cache.get("materials", "1", 12, 1, 1) is None
