"""`infrastructure/tile_cache.py`——取得済みのタイル・フォントの生バイトを置くディスク。

ここで見ないもの:
- タイル座標をキーにしたPythonオブジェクトの置き場 → `test_tile_persistent_cache.py`
- どのパスを引くか・どのContent-Typeを付けるか → 取得側のテスト
  （`test_basemap_client.py`・`test_gsi_tile_client.py`・`test_region_service.py`等）

**置き場はテストごとの一時ディレクトリへ差し替える。** 実体は`backend/data/tile_cache`で、
差し替えないと本物の配信物を消す。
"""

import os
from pathlib import Path

import pytest

from app.infrastructure import tile_cache

PATH = "planet/14/1234/5678.pbf"


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch) -> Path:
    directory = tmp_path / "tile_cache"
    monkeypatch.setattr(tile_cache, "CACHE_DIR", directory)
    return directory


def _boom(*_args, **_kwargs):
    raise OSError("disk")


class TestNamingTheFileOnDisk:
    def test_the_same_path_always_lands_on_the_same_file(self):
        assert tile_cache.cache_key(PATH) == tile_cache.cache_key(PATH)

    def test_two_paths_do_not_share_a_file(self):
        assert tile_cache.cache_key("planet") != tile_cache.cache_key(PATH)

    @pytest.mark.parametrize("path", [PATH, "../../secrets.json", "地図/1.pbf"])
    def test_nothing_in_the_path_survives_into_the_file_name(self, path):
        """パスを階層へ写すと、`planet`がファイルとディレクトリの両方になってWindowsで
        書けなくなり、`..`が混ざれば置き場の外へ書く。
        """
        assert tile_cache.cache_key(path).isalnum()


class TestKeepingABodyAndItsType:
    def test_a_path_that_was_never_fetched_is_a_miss(self):
        assert tile_cache.get(PATH) is None

    def test_what_was_stored_comes_back_byte_for_byte(self):
        tile_cache.set(PATH, b"\x00\xff\x1f", "application/x-protobuf")

        assert tile_cache.get(PATH) == (b"\x00\xff\x1f", "application/x-protobuf")

    def test_the_first_write_is_created_even_if_the_place_does_not_exist_yet(self, cache_dir):
        assert not cache_dir.exists()

        tile_cache.set(PATH, b"body", "image/png")

        assert tile_cache.get(PATH) is not None

    def test_writing_the_same_path_again_replaces_what_was_there(self):
        tile_cache.set(PATH, b"old", "image/png")

        tile_cache.set(PATH, b"new", "image/webp")

        assert tile_cache.get(PATH) == (b"new", "image/webp")

    def test_a_body_whose_type_is_missing_is_served_as_raw_bytes(self, cache_dir):
        """型ごと未キャッシュへ倒すと、取り直すまでその1枚が出なくなる。"""
        tile_cache.set(PATH, b"body", "image/png")
        (cache_dir / f"{tile_cache.cache_key(PATH)}.meta").unlink()

        assert tile_cache.get(PATH) == (b"body", "application/octet-stream")

    def test_a_finished_write_leaves_nothing_beside_the_two_files(self, cache_dir):
        """書きかけの一時ファイルが残ると、`*.bin`しか見ない掃除の対象にならないまま積む。"""
        tile_cache.set(PATH, b"body", "image/png")

        assert sorted(p.suffix for p in cache_dir.iterdir()) == [".bin", ".meta"]


class TestWhenTheDiskRefuses:
    def test_a_write_that_fails_halfway_leaves_a_miss_rather_than_an_error(self, monkeypatch):
        """実体を最後に書くので、途中で落ちた項目は「無い」として読める。キャッシュの
        書き込み失敗で配信そのものを止めない。
        """
        monkeypatch.setattr(Path, "write_bytes", _boom)

        tile_cache.set(PATH, b"body", "image/png")

        assert tile_cache.get(PATH) is None

    def test_a_body_that_cannot_be_read_is_a_miss(self, monkeypatch):
        """全消しと競ると読み出しの途中で実体が消える。例外のまま返すと、掃除と同時に
        来た要求だけが500になる。
        """
        tile_cache.set(PATH, b"body", "image/png")
        monkeypatch.setattr(Path, "read_bytes", _boom)

        assert tile_cache.get(PATH) is None


class TestThrowingEverythingAway:
    def test_after_clearing_nothing_is_cached(self):
        tile_cache.set(PATH, b"body", "image/png")
        tile_cache.set("other", b"body", "image/png")

        tile_cache.clear_all()

        assert tile_cache.get(PATH) is None
        assert tile_cache.get("other") is None

    def test_clearing_a_place_that_was_never_written_is_not_an_error(self):
        tile_cache.clear_all()


class TestKeepingTheDirectoryWithinItsLimit:
    """**書いた時刻は`os.utime`で明示する**——続けて書くとmtimeが同値になり、古い順が決まらない。"""

    @staticmethod
    def _store(path: str, body: bytes, *, written_at: float) -> Path:
        tile_cache.set(path, body, "image/png")
        content = tile_cache.CACHE_DIR / f"{tile_cache.cache_key(path)}.bin"
        for target in (content, content.with_suffix(".meta")):
            os.utime(target, (written_at, written_at))
        return content

    def test_a_place_that_is_within_its_limit_is_left_alone(self):
        self._store(PATH, b"x" * 100, written_at=1.0)

        assert tile_cache.prune_to_size_limit(10_000) == 0
        assert tile_cache.get(PATH) is not None

    def test_pruning_before_anything_was_fetched_does_nothing(self):
        assert tile_cache.prune_to_size_limit(0) == 0

    def test_the_entry_written_longest_ago_goes_first(self):
        self._store("old", b"x" * 100, written_at=1.0)
        self._store("new", b"y" * 100, written_at=2.0)

        assert tile_cache.prune_to_size_limit(150) > 0
        assert tile_cache.get("old") is None
        assert tile_cache.get("new") is not None

    def test_the_type_file_is_removed_together_with_its_body(self, cache_dir):
        """実体だけ消すと、対の型ファイルが掃除の対象にならないまま積み続ける。"""
        self._store("old", b"x" * 100, written_at=1.0)
        self._store("new", b"y" * 100, written_at=2.0)

        tile_cache.prune_to_size_limit(150)

        assert len(list(cache_dir.glob("*.meta"))) == 1

    def test_what_was_freed_is_reported_in_bytes(self):
        """件数を返すと、掃除の結果を出すログが常に0.0MBになる。"""
        content = self._store(PATH, b"x" * 100, written_at=1.0)
        stored = content.stat().st_size + content.with_suffix(".meta").stat().st_size

        assert tile_cache.prune_to_size_limit(0) == stored

    def test_a_body_that_lost_its_type_file_is_still_removed(self):
        content = self._store(PATH, b"x" * 100, written_at=1.0)
        content.with_suffix(".meta").unlink()

        assert tile_cache.prune_to_size_limit(0) == 100
        assert tile_cache.get(PATH) is None

    def test_an_entry_that_vanished_while_listing_does_not_stop_the_rest(self, monkeypatch):
        """全消しと競ると、数え上げの途中で実体が消える。そこで落ちると上限が二度と
        効かなくなり、置き場は伸び続ける。
        """
        self._store("gone", b"x" * 100, written_at=1.0)
        self._store("stays", b"y" * 100, written_at=2.0)
        vanished = f"{tile_cache.cache_key('gone')}.bin"
        real_stat = Path.stat

        def flaky(self, *args, **kwargs):
            if self.name == vanished:
                raise OSError("vanished")
            return real_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", flaky)

        assert tile_cache.prune_to_size_limit(0) > 0
        assert tile_cache.get("stays") is None
