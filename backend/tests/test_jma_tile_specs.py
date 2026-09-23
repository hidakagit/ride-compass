"""`domain/jma_tile_specs.py`——気象庁タイルの、実データが在るズームを決める。

タイルの取得と補間の実行は`test_jma_tile_client.py`・`test_jma_tile_interpolation.py`が持つ。
"""

from app.domain import jma_tile_specs
from app.domain.jma_tile_specs import (
    JMA_TILE_SPECS,
    JmaTileSpec,
    effective_max_zoom,
    has_native_tile,
    source_zoom_for_interpolation,
)


def _spec(zoom_use: str, max_native_zoom: int, min_zoom: int = 4) -> JmaTileSpec:
    return JmaTileSpec(path_group="risk", zoom_use=zoom_use, max_native_zoom=max_native_zoom, min_zoom=min_zoom)


class TestEffectiveMaxZoom:

    def test_even_element_keeps_an_even_maximum(self):
        assert effective_max_zoom(_spec("even", 10)) == 10

    def test_even_element_steps_down_from_an_odd_maximum(self):
        assert effective_max_zoom(_spec("even", 11)) == 10

    def test_odd_element_keeps_an_odd_maximum(self):
        assert effective_max_zoom(_spec("odd", 11)) == 11

    def test_odd_element_steps_down_from_an_even_maximum(self):
        assert effective_max_zoom(_spec("odd", 10)) == 9

    def test_unconstrained_element_uses_the_maximum_as_is(self):
        assert effective_max_zoom(_spec("all", 11)) == 11


class TestHasNativeTile:

    def test_below_the_minimum_zoom_has_no_tile(self):
        assert has_native_tile(_spec("even", 10, min_zoom=4), 3) is False

    def test_above_the_effective_maximum_has_no_tile(self):
        assert has_native_tile(_spec("even", 11), 11) is False

    def test_even_element_has_tiles_only_on_even_zooms(self):
        spec = _spec("even", 10)

        assert [z for z in range(4, 11) if has_native_tile(spec, z)] == [4, 6, 8, 10]

    def test_odd_element_has_tiles_only_on_odd_zooms(self):
        spec = _spec("odd", 11)

        assert [z for z in range(4, 12) if has_native_tile(spec, z)] == [5, 7, 9, 11]

    def test_unconstrained_element_has_tiles_on_every_zoom_in_range(self):
        spec = _spec("all", 7)

        assert [z for z in range(3, 9) if has_native_tile(spec, z)] == [4, 5, 6, 7]


class TestSourceZoomForInterpolation:

    def test_a_zoom_without_native_data_is_interpolated_from_the_zoom_below(self):
        assert source_zoom_for_interpolation("hrpns", 5) == 4

    def test_a_zoom_that_has_native_data_needs_no_interpolation(self):
        assert source_zoom_for_interpolation("hrpns", 6) is None

    def test_the_minimum_zoom_has_no_parent_to_enlarge_from(self):
        spec = JMA_TILE_SPECS["hrpns"]

        assert source_zoom_for_interpolation("hrpns", spec.min_zoom - 1) is None

    def test_an_unregistered_element_has_nothing_to_interpolate(self):
        """知らない要素で親を返すと、存在しないタイルを取りに行く。"""
        assert source_zoom_for_interpolation("no_such_element", 5) is None

    def test_an_element_without_a_parity_constraint_never_interpolates(self, monkeypatch):
        """偶奇を限らない要素は全ズームに実データがあるため、拡大で埋める必要が無い。
        今のレジストリは全要素が偶数ズームのみだが、`zoom_use`は`"all"`も取る。
        """
        monkeypatch.setattr(jma_tile_specs, "JMA_TILE_SPECS", {"synthetic": _spec("all", 10)})

        assert source_zoom_for_interpolation("synthetic", 5) is None

    def test_above_the_maximum_is_left_to_the_client_overzoom(self):
        """ここで親を返すと、二重に拡大される。"""
        spec = JMA_TILE_SPECS["hrpns"]

        assert source_zoom_for_interpolation("hrpns", effective_max_zoom(spec) + 1) is None

