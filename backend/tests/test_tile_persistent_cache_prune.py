"""ディスク永続キャッシュの旧世代掃除と容量上限。

世代番号は参照先を切り替えるだけで、古い実体は残り続ける。掃除が効いていないと世代を
上げるたびに積み上がるため、ここで振る舞いを固定する。容量上限（`diskcache`の
`size_limit`）による自動退避も、ディスクが無制限に増えないことの担保として確認する。
"""

import pytest

from app.infrastructure import tile_persistent_cache


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    tile_persistent_cache.use_directory(tmp_path)
    return tmp_path


def _write(namespace: str, version: str, zoom: int, x: int, y: int, value) -> None:
    tile_persistent_cache.set(namespace, version, zoom, x, y, value)


def test_prune_removes_other_generations_and_keeps_current(cache_dir):
    _write("materials", "4", 12, 1, 1, {"old": True})
    _write("materials", "5", 12, 1, 1, {"current": True})

    removed = tile_persistent_cache.prune_stale_generations("materials", "5")

    assert removed == 1
    assert tile_persistent_cache.get("materials", "4", 12, 1, 1) is None
    assert tile_persistent_cache.get("materials", "5", 12, 1, 1) == {"current": True}


def test_prune_removes_every_stale_generation(cache_dir):
    for version in ("2", "3", "4"):
        _write("materials", version, 12, 1, 1, {"v": version})
    _write("materials", "5", 12, 1, 1, {"v": "5"})

    removed = tile_persistent_cache.prune_stale_generations("materials", "5")

    assert removed == 3
    assert all(tile_persistent_cache.get("materials", v, 12, 1, 1) is None for v in ("2", "3", "4"))
    assert tile_persistent_cache.get("materials", "5", 12, 1, 1) == {"v": "5"}


def test_prune_does_not_touch_other_namespaces(cache_dir):
    _write("materials", "4", 12, 1, 1, {"v": "4"})
    _write("score_matrix", "4", 12, 1, 1, {"v": "4"})

    tile_persistent_cache.prune_stale_generations("materials", "5")

    assert tile_persistent_cache.get("score_matrix", "4", 12, 1, 1) == {"v": "4"}


def test_prune_is_noop_when_namespace_is_absent(cache_dir):
    assert tile_persistent_cache.prune_stale_generations("materials", "5") == 0


def test_prune_is_noop_when_only_current_generation_exists(cache_dir):
    _write("materials", "5", 12, 1, 1, {"v": "5"})

    assert tile_persistent_cache.prune_stale_generations("materials", "5") == 0
    assert tile_persistent_cache.get("materials", "5", 12, 1, 1) == {"v": "5"}


def test_size_limit_evicts_old_entries_instead_of_growing_without_bound(tmp_path, monkeypatch):
    """容量上限を超えたら古いものから退避され、ディスクが無制限に増えない。"""
    import diskcache

    from app.infrastructure import tile_persistent_cache as tpc

    tpc.use_directory(tmp_path / "small")
    monkeypatch.setattr(
        tpc, "_cache", diskcache.Cache(str(tmp_path / "small"), size_limit=1024 * 1024, eviction_policy="least-recently-used")
    )
    payload = "x" * 200_000  # 1エントリ約200KB（上限1MBに対し5〜6件で頭打ちになる想定）

    for i in range(20):
        tpc.set("materials", "1", 12, i, 0, payload)

    volume = tpc.cache().volume()
    assert volume <= 1024 * 1024 * 1.2, f"上限を超えて増え続けている: {volume}"
    assert len(tpc.cache()) < 20
