import pytest

from app.infrastructure import tile_cache


@pytest.fixture(autouse=True)
def use_temp_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tile_cache, "CACHE_DIR", tmp_path / "tile_cache")
    yield


def test_get_returns_none_when_not_cached():
    assert tile_cache.get("styles/liberty") is None


def test_set_then_get_roundtrip():
    tile_cache.set("styles/liberty", b'{"version":8}', "application/json")

    result = tile_cache.get("styles/liberty")

    assert result == (b'{"version":8}', "application/json")


def test_set_does_not_collide_when_one_path_is_a_prefix_of_another():
    # "planet"（TileJSON本体）と"planet/2026/12/3232/1450.pbf"（実タイル）のように、
    # 一方が他方のディレクトリ接頭辞になるケースでも衝突しない（Windowsで実際に
    # FileExistsErrorとしてクラッシュしたことがある回帰テスト）
    tile_cache.set("planet", b"tilejson", "application/json")
    tile_cache.set("planet/2026/12/3232/1450.pbf", b"tile-bytes", "application/x-protobuf")

    assert tile_cache.get("planet") == (b"tilejson", "application/json")
    assert tile_cache.get("planet/2026/12/3232/1450.pbf") == (b"tile-bytes", "application/x-protobuf")


def test_set_handles_path_traversal_style_input_without_raising():
    tile_cache.set("../../outside", b"data", "text/plain")

    assert tile_cache.get("../../outside") == (b"data", "text/plain")


def test_clear_all_removes_cached_entries():
    tile_cache.set("planet/1/2/3.pbf", b"\x00\x01", "application/x-protobuf")

    tile_cache.clear_all()

    assert tile_cache.get("planet/1/2/3.pbf") is None


# 改善計画T463: set()の後、キャッシュディレクトリに.tmp-*の一時ファイルが残っていない
# ことを確認する（os.replaceによるアトミック差し替えが正しく完了していることの回帰）。
def test_set_leaves_no_temp_files_behind():
    tile_cache.set("styles/liberty", b'{"version":8}', "application/json")

    leftover_tmp_files = list(tile_cache.CACHE_DIR.glob("*.tmp-*"))
    assert leftover_tmp_files == []


# 改善計画T463: .metaを.binより先に書くため、.binが見えた時点で.metaは必ず既に
# 完全に書き終わっている（get()が誤ったContent-Typeへフォールバックする窓が無い）。
def test_set_writes_meta_before_bin_so_get_never_sees_default_content_type():
    tile_cache.set("styles/liberty", b'{"version":8}', "application/json")

    result = tile_cache.get("styles/liberty")

    assert result is not None
    assert result[1] == "application/json"
    assert result[1] != "application/octet-stream"
