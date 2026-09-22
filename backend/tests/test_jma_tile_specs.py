"""`domain/jma_tile_specs.py`——気象庁タイルの、実データが在るズームを決める。

配信元は要素ごとに「使うズームの偶奇」と「画像が実在する最大ズーム」を持つ。どちらか
一方だけを見ると実データの無いズームを指し、配信元は200を返すのに中身が空になる。
"""

from app.domain.jma_tile_specs import (
    JMA_TILE_SPECS,
    JmaTileSpec,
    effective_max_zoom,
    has_native_tile,
    max_zoom_for,
    source_zoom_for_interpolation,
)


def _spec(zoom_use: str, max_native_zoom: int, min_zoom: int = 4) -> JmaTileSpec:
    return JmaTileSpec(
        element_id="synthetic", zoom_use=zoom_use, max_native_zoom=max_native_zoom, min_zoom=min_zoom
    )


class TestEffectiveMaxZoom:
    """偶奇の合わないズームには画像が無い。合う側へ1段下げたところが本当の上限。"""

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


class TestMaxZoomFor:
    def test_registered_element_reports_its_effective_maximum(self):
        element_id, spec = next(iter(JMA_TILE_SPECS.items()))

        assert max_zoom_for(element_id) == effective_max_zoom(spec)

    def test_unregistered_element_is_none(self):
        """未登録を既定値へ倒さない——知らない要素のタイルを要求し続けることになる。"""
        assert max_zoom_for("no_such_element") is None


class TestHasNativeTile:
    """配信元が200を返しても中身が空のことがある。要求する前にここで落とす。"""

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
    """実データが1つおきにしか無い要素は、間のズームを親から拡大して埋める。"""

    def test_a_zoom_without_native_data_is_interpolated_from_the_zoom_below(self):
        """親は常に`zoom - 1`——偶奇が限られているため、1つ下は必ず反対の偶奇になる。"""
        assert source_zoom_for_interpolation("hrpns", 5) == 4

    def test_a_zoom_that_has_native_data_needs_no_interpolation(self):
        assert source_zoom_for_interpolation("hrpns", 6) is None

    def test_the_minimum_zoom_has_no_parent_to_enlarge_from(self):
        spec = JMA_TILE_SPECS["hrpns"]

        assert source_zoom_for_interpolation("hrpns", spec.min_zoom - 1) is None

    def test_above_the_maximum_is_left_to_the_client_overzoom(self):
        """上限より上はMapLibreが拡大する。ここで親を返すと二重に拡大される。"""
        spec = JMA_TILE_SPECS["hrpns"]

        assert source_zoom_for_interpolation("hrpns", effective_max_zoom(spec) + 1) is None

    def test_unconstrained_element_never_needs_interpolation(self):
        assert source_zoom_for_interpolation("no_such_element", 5) is None


def test_every_registered_element_has_data_at_its_own_maximum():
    """全要素に対する不変条件。`zoom_use`と`max_native_zoom`の組み合わせが食い違うと、
    上限として配った値のタイルが空になる。要素が1つ増えたときに発火する。
    """
    assert JMA_TILE_SPECS, "レジストリが空なら、下のループは何も確かめていない"

    for element_id, spec in JMA_TILE_SPECS.items():
        top = effective_max_zoom(spec)

        assert spec.min_zoom <= top, element_id
        assert has_native_tile(spec, top), element_id
