"""`infrastructure/tile_persistent_cache.py`——置いたものを捨てる側。

世代番号は参照先を切り替えるだけで、ディスクの旧実体は残る。ここはそれを消す側を見る。

ここで見ないもの:
- 読み書き・キーの同一性・失効 → `test_tile_persistent_cache.py`
- どの世代を残すかの決め方 → `test_graph_material_cache.py`・`test_tile_score_matrix_cache.py`

置き場は`conftest.py`のautouseフィクスチャがテストごとの一時ディレクトリへ差し替える。
"""

from app.infrastructure import tile_persistent_cache

CURRENT = "v2"
STALE = "v1"


def _boom(*_args, **_kwargs):
    raise RuntimeError("sqlite")


def _store(namespace: str, version: str, x: int = 0) -> tuple:
    tile_persistent_cache.set(namespace, version, 12, x, 0, "value")
    return (namespace, version, 12, x, 0)


class TestDroppingTheGenerationsNobodyReadsAnymore:
    def test_an_entry_from_another_generation_is_removed(self):
        """上限に達するまで居座るため、世代交代の時点で捨てる。"""
        stale = _store("materials", STALE)

        tile_persistent_cache.prune_stale_generations("materials", CURRENT)

        assert tile_persistent_cache.get_by_key(stale) is None

    def test_the_generation_being_kept_survives(self):
        current = _store("materials", CURRENT)

        tile_persistent_cache.prune_stale_generations("materials", CURRENT)

        assert tile_persistent_cache.get_by_key(current) == "value"

    def test_another_namespace_is_never_touched(self):
        """材料の世代を上げたときにスコア行列まで消えると、どちらの再計算も払い直す。"""
        other = _store("scores", STALE)

        tile_persistent_cache.prune_stale_generations("materials", CURRENT)

        assert tile_persistent_cache.get_by_key(other) == "value"

    def test_the_number_of_entries_removed_is_reported(self):
        _store("materials", STALE, x=0)
        _store("materials", STALE, x=1)

        assert tile_persistent_cache.prune_stale_generations("materials", CURRENT) == 2

    def test_a_place_with_nothing_stale_removes_nothing(self):
        _store("materials", CURRENT)

        assert tile_persistent_cache.prune_stale_generations("materials", CURRENT) == 0

    def test_a_failure_while_pruning_is_reported_as_nothing_removed(self, monkeypatch):
        """例外にすると、掃除を並べて呼ぶ側が2つ目以降を捨て損ねる。消せなかったぶんは
        容量上限の退避が引き受ける。
        """
        monkeypatch.setattr(tile_persistent_cache, "cache", _boom)

        assert tile_persistent_cache.prune_stale_generations("materials", CURRENT) == 0


class TestThrowingAwayAWholeNamespace:
    def test_every_generation_of_that_namespace_goes(self):
        """材料そのものが作り直されたら、どの世代の写しも正しくない。"""
        stale = _store("materials", STALE)
        current = _store("materials", CURRENT)

        tile_persistent_cache.clear_namespace("materials")

        assert tile_persistent_cache.get_by_key(stale) is None
        assert tile_persistent_cache.get_by_key(current) is None

    def test_another_namespace_stays(self):
        other = _store("scores", CURRENT)

        tile_persistent_cache.clear_namespace("materials")

        assert tile_persistent_cache.get_by_key(other) == "value"


class TestKeysThatAreNotTileCoordinates:
    """タイル座標の形をしていない鍵は、世代・namespaceの掃除の対象ではない——持ち主が
    知らないうちに消えると、その持ち主だけが作り直しを払う。
    """

    KEY = ("way_values", 7, "material_a", 12, 3630, 1612, "09", None, None)

    def test_a_generation_prune_leaves_it_alone(self):
        tile_persistent_cache.set_by_key(self.KEY, "value")

        tile_persistent_cache.prune_stale_generations("way_values", CURRENT)

        assert tile_persistent_cache.get_by_key(self.KEY) == "value"

    def test_clearing_a_namespace_leaves_it_alone(self):
        tile_persistent_cache.set_by_key(self.KEY, "value")

        tile_persistent_cache.clear_namespace("way_values")

        assert tile_persistent_cache.get_by_key(self.KEY) == "value"


class TestThrowingEverythingAway:
    def test_nothing_of_any_shape_is_left(self):
        tile_coordinates = _store("materials", CURRENT)
        other_shape = ("way_values", 7, "material_a")
        tile_persistent_cache.set_by_key(other_shape, "value")

        tile_persistent_cache.clear_all()

        assert tile_persistent_cache.get_by_key(tile_coordinates) is None
        assert tile_persistent_cache.get_by_key(other_shape) is None
