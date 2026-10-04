"""`infrastructure/tile_persistent_cache.py`——呼び出し元が設計したタプルの鍵でPythonオブジェクトを置くディスク。

ここで見ないもの:
- 鍵をどう組み立てるか・いつ失効させるか → 呼び出し元（`test_dynamic_way_value_cache.py`等）
- 違う鍵が別のエントリになること・同じ鍵の上書き・`expire`での失効 → `diskcache`へ鍵と`expire`をそのまま渡すだけで、
  自前の判断が無い
- 生バイトの置き場 → `test_tile_cache.py`

置き場は`conftest.py`のautouseフィクスチャがテストごとの一時ディレクトリへ差し替える。
"""

from app.infrastructure import tile_persistent_cache

KEY = ("way_values", 7, "material_a", 12, 3630, 1612, "09", None, None)
TTL = 3600


def _boom(*_args, **_kwargs):
    raise RuntimeError("sqlite")


class TestKeepingAnObject:
    def test_a_key_never_written_is_a_miss(self):
        assert tile_persistent_cache.get_by_key(KEY) is None

    def test_an_object_comes_back_as_it_went_in(self):
        value = {"w1": (1, 2.5), "missing": None}

        tile_persistent_cache.set_by_key(KEY, value, expire=TTL)

        assert tile_persistent_cache.get_by_key(KEY) == value


class TestWhenTheDiskRefuses:
    def test_a_value_that_cannot_be_stored_is_dropped_rather_than_raised(self):
        """書き込みの失敗で応答を止めない。読み手からは未キャッシュと同じに見える。"""
        tile_persistent_cache.set_by_key(KEY, lambda: None, expire=TTL)

        assert tile_persistent_cache.get_by_key(KEY) is None

    def test_a_read_that_blows_up_is_a_miss(self, monkeypatch):
        """壊れたエントリ・SQLiteの障害で止めると、キャッシュの不調がそのまま機能停止になる。"""
        tile_persistent_cache.set_by_key(KEY, "value", expire=TTL)
        monkeypatch.setattr(tile_persistent_cache, "cache", _boom)

        assert tile_persistent_cache.get_by_key(KEY) is None
