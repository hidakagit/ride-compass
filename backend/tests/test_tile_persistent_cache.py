"""`infrastructure/tile_persistent_cache.py`——呼び出し元が設計したタプルの鍵でPythonオブジェクトを置くディスク。

ここで見ないもの:
- 鍵をどう組み立てるか・いつ失効させるか → 呼び出し元（`test_dynamic_way_value_cache.py`等）
- 生バイトの置き場 → `test_tile_cache.py`

置き場は`conftest.py`のautouseフィクスチャがテストごとの一時ディレクトリへ差し替える。
"""

import pytest

from app.infrastructure import tile_persistent_cache

KEY = ("way_values", 7, "material_a", 12, 3630, 1612, "09", None, None)


def _boom(*_args, **_kwargs):
    raise RuntimeError("sqlite")


class TestKeepingAnObject:
    def test_a_key_never_written_is_a_miss(self):
        assert tile_persistent_cache.get_by_key(KEY) is None

    def test_an_object_comes_back_as_it_went_in(self):
        value = {"w1": (1, 2.5), "missing": None}

        tile_persistent_cache.set_by_key(KEY, value)

        assert tile_persistent_cache.get_by_key(KEY) == value

    def test_an_empty_value_is_not_the_same_as_never_having_written_it(self):
        """値の無い範囲も実在する。空を未キャッシュへ倒すと、その範囲だけ毎回作り直す。"""
        tile_persistent_cache.set_by_key(KEY, {})

        assert tile_persistent_cache.get_by_key(KEY) == {}

    def test_writing_the_same_key_again_replaces_what_was_there(self):
        tile_persistent_cache.set_by_key(KEY, "old")

        tile_persistent_cache.set_by_key(KEY, "new")

        assert tile_persistent_cache.get_by_key(KEY) == "new"


class TestWhatMakesTwoEntriesDifferent:
    @pytest.mark.parametrize("part", [1, 2, 3])
    def test_changing_any_part_of_the_key_is_another_entry(self, part):
        """世代を上げても前の値が読めるなら、形の変わったキャッシュを新しいコードが読む。"""
        tile_persistent_cache.set_by_key(KEY, "value")
        other = list(KEY)
        other[part] = "other" if isinstance(other[part], str) else other[part] + 1

        assert tile_persistent_cache.get_by_key(tuple(other)) is None


class TestWhenTheDiskRefuses:
    def test_a_value_that_cannot_be_stored_is_dropped_rather_than_raised(self):
        """書き込みの失敗で応答を止めない。読み手からは未キャッシュと同じに見える。"""
        tile_persistent_cache.set_by_key(KEY, lambda: None)

        assert tile_persistent_cache.get_by_key(KEY) is None

    def test_a_read_that_blows_up_is_a_miss(self, monkeypatch):
        """壊れたエントリ・SQLiteの障害で止めると、キャッシュの不調がそのまま機能停止になる。"""
        tile_persistent_cache.set_by_key(KEY, "value")
        monkeypatch.setattr(tile_persistent_cache, "cache", _boom)

        assert tile_persistent_cache.get_by_key(KEY) is None


class TestEntriesThatExpire:
    def test_an_entry_still_within_its_time_is_read(self):
        tile_persistent_cache.set_by_key(KEY, "value", expire=600)

        assert tile_persistent_cache.get_by_key(KEY) == "value"

    def test_an_entry_whose_time_has_passed_is_a_miss(self):
        tile_persistent_cache.set_by_key(KEY, "value", expire=-1)

        assert tile_persistent_cache.get_by_key(KEY) is None
