"""`infrastructure/tile_persistent_cache.py`——タイル単位のPythonオブジェクトを置くディスク。

ここで見ないもの:
- 置いたものを捨てる側（世代の掃除・namespace単位の削除）→ `test_tile_persistent_cache_prune.py`
- DBの世代との突き合わせ → `test_cache_generation.py`
- namespaceと世代文字列をどう決めるか → `test_graph_material_cache.py`・`test_tile_score_matrix_cache.py`
- 生バイトの置き場 → `test_tile_cache.py`

置き場は`conftest.py`のautouseフィクスチャがテストごとの一時ディレクトリへ差し替える。
"""

import pytest

from app.infrastructure import tile_persistent_cache

ENTRY = ("materials", "v1", 12, 3630, 1612)


def _boom(*_args, **_kwargs):
    raise RuntimeError("sqlite")


class TestKeepingAnObjectForATile:
    def test_a_tile_that_was_never_computed_is_a_miss(self):
        assert tile_persistent_cache.get(*ENTRY) is None

    def test_an_object_comes_back_as_it_went_in(self):
        value = {"edges": (1, 2.5), "missing": None}

        tile_persistent_cache.set(*ENTRY, value)

        assert tile_persistent_cache.get(*ENTRY) == value

    def test_an_empty_value_is_not_the_same_as_never_having_computed_it(self):
        """Edgeが1本も無いタイルは実在する。空を未キャッシュへ倒すと、そのタイルだけ
        毎回DBから作り直す。
        """
        tile_persistent_cache.set(*ENTRY, {})

        assert tile_persistent_cache.get(*ENTRY) == {}

    def test_writing_the_same_tile_again_replaces_what_was_there(self):
        tile_persistent_cache.set(*ENTRY, "old")

        tile_persistent_cache.set(*ENTRY, "new")

        assert tile_persistent_cache.get(*ENTRY) == "new"


class TestWhatMakesTwoEntriesDifferent:
    @pytest.mark.parametrize("part", range(len(ENTRY)))
    def test_changing_any_part_of_the_key_is_another_entry(self, part):
        """世代を上げても前の値が読めるなら、形の変わったキャッシュを新しいコードが読む。"""
        tile_persistent_cache.set(*ENTRY, "value")
        other = list(ENTRY)
        other[part] = "other" if isinstance(other[part], str) else other[part] + 1

        assert tile_persistent_cache.get(*other) is None


class TestTellingTheCallerHowLongTheReadTook:
    def test_a_hit_reports_the_time_spent_reading(self):
        tile_persistent_cache.set(*ENTRY, "value")
        stats: dict[str, object] = {}

        tile_persistent_cache.get(*ENTRY, stats)

        assert isinstance(stats["read_ms"], float)

    def test_a_miss_leaves_the_stats_untouched(self):
        """ミスでも数字が入ると、要求ごとのサマリが「ディスクから読めた」ことになる。"""
        stats: dict[str, object] = {}

        tile_persistent_cache.get(*ENTRY, stats)

        assert stats == {}


class TestWhenTheDiskRefuses:
    def test_a_value_that_cannot_be_stored_is_dropped_rather_than_raised(self):
        """書き込みの失敗で応答を止めない。読み手からは未キャッシュと同じに見える。"""
        tile_persistent_cache.set(*ENTRY, lambda: None)

        assert tile_persistent_cache.get(*ENTRY) is None

    def test_a_read_that_blows_up_is_a_miss(self, monkeypatch):
        """壊れたエントリ・SQLiteの障害で止めると、キャッシュの不調がそのまま機能停止になる。"""
        tile_persistent_cache.set(*ENTRY, "value")
        monkeypatch.setattr(tile_persistent_cache, "cache", _boom)

        assert tile_persistent_cache.get(*ENTRY) is None


class TestEntriesThatExpire:
    def test_an_entry_still_within_its_time_is_read(self):
        tile_persistent_cache.set_by_key(ENTRY, "value", expire=600)

        assert tile_persistent_cache.get_by_key(ENTRY) == "value"

    def test_an_entry_whose_time_has_passed_is_a_miss(self):
        tile_persistent_cache.set_by_key(ENTRY, "value", expire=-1)

        assert tile_persistent_cache.get_by_key(ENTRY) is None


class TestKeysTheCallerDesigns:
    def test_a_key_of_another_shape_round_trips(self):
        """タイル座標に収まらない鍵（材料・時刻帯・方位…）を持つ呼び出し元がある。"""
        key = ("way_values", 7, "material_a", 12, 3630, 1612, "09", None, None)

        tile_persistent_cache.set_by_key(key, {"w1": 1.5})

        assert tile_persistent_cache.get_by_key(key) == {"w1": 1.5}
