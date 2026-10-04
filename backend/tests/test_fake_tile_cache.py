"""`tests/fake_tile_cache.py`——`tile_cache`（ディスクのキャッシュ）の代役。

同じ読み書きを本物と代役の両方へ流し、読んだものが揃うことを見る。本物の置き場は`tests/conftest.py`が
テストごとの一時ディレクトリへ向けてある。

ここで見ないもの: 読み書きしたスレッドの記録（代役にだけある観測点で、使う側の`test_tile_serving.py`が読む）
"""

import pytest

from app.infrastructure import tile_cache
from tests.fake_tile_cache import FakeTileCache


@pytest.fixture(params=["本物", "代役"])
def cache(request):
    return tile_cache if request.param == "本物" else FakeTileCache()


def test_what_was_stored_last_under_a_path_is_read_back_and_other_paths_are_misses(cache):
    cache.set("a.png", b"old", "image/png")
    cache.set("a.png", b"new", "image/webp")

    assert cache.get("a.png") == (b"new", "image/webp")
    assert cache.get("b.png") is None
