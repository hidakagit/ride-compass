"""ディスク永続キャッシュの旧世代掃除（tile_persistent_cache.prune_stale_generations）。

世代番号は参照先を切り替えるだけで、ディスク上の古い実体は残り続ける。掃除が効いて
いないと世代を上げるたびに実体が積み上がるため、ここで振る舞いを固定する。
"""

import pytest

from app.infrastructure import tile_persistent_cache


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tile_persistent_cache, "CACHE_DIR", tmp_path)
    return tmp_path


def _write(namespace: str, version: str, zoom: int, x: int, y: int, value) -> None:
    tile_persistent_cache.set(namespace, version, zoom, x, y, value)


def test_prune_removes_other_generations_and_keeps_current(cache_dir):
    _write("materials", "4", 12, 1, 1, {"old": True})
    _write("materials", "5", 12, 1, 1, {"current": True})

    freed = tile_persistent_cache.prune_stale_generations("materials", "5")

    assert freed > 0
    assert not (cache_dir / "materials" / "v4").exists()
    assert tile_persistent_cache.get("materials", "5", 12, 1, 1) == {"current": True}


def test_prune_removes_every_stale_generation(cache_dir):
    for version in ("2", "3", "4"):
        _write("materials", version, 12, 1, 1, {"v": version})
    _write("materials", "5", 12, 1, 1, {"v": "5"})

    tile_persistent_cache.prune_stale_generations("materials", "5")

    remaining = sorted(p.name for p in (cache_dir / "materials").iterdir())
    assert remaining == ["v5"]


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
