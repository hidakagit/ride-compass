"""`infrastructure/tile_cache.py`——取得・生成したタイル・フォントの生バイトを置くディスク。

ここで見ないもの:
- タイル座標をキーにしたPythonオブジェクトの置き場 → `test_tile_persistent_cache.py`
- どのパスを引くか・どのContent-Typeを付けるか → 取得側のテスト
  （`test_basemap_client.py`・`test_gsi_tile_client.py`・`test_region_service.py`等）
- 全消去 → `test_basemap_routes.py`（管理APIの入口で見る）
- 容量上限を超えたときの退避 → `diskcache`の持ち物で、ここでは書き写さない

置き場はテストごとの一時ディレクトリ（`conftest.py`が差し替える）。
"""

import diskcache

from app.infrastructure import tile_cache

PATH = "planet/14/1234/5678.pbf"


def _boom(*_args, **_kwargs):
    raise OSError("disk")


def test_a_path_that_was_never_fetched_is_a_miss():
    assert tile_cache.get(PATH) is None


def test_what_was_stored_comes_back_byte_for_byte_with_its_type():
    tile_cache.set(PATH, b"\x00\xff\x1f", "application/x-protobuf")

    assert tile_cache.get(PATH) == (b"\x00\xff\x1f", "application/x-protobuf")


def test_a_write_the_disk_refuses_leaves_a_miss_rather_than_an_error(monkeypatch):
    """キャッシュの書き込み失敗で配信そのものを止めない。"""
    monkeypatch.setattr(diskcache.Cache, "set", _boom)

    tile_cache.set(PATH, b"body", "image/png")

    assert tile_cache.get(PATH) is None


def test_a_read_the_disk_refuses_is_a_miss(monkeypatch):
    """例外のまま返すと、ディスクの障害がそのままタイル要求の500になる。取り直せば配れる。"""
    tile_cache.set(PATH, b"body", "image/png")
    monkeypatch.setattr(diskcache.Cache, "get", _boom)

    assert tile_cache.get(PATH) is None
