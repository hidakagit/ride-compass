"""`domain/axis_display.py`——軸を地図にどう塗るか（塗れるか・タイルのどの値を・どこで段を切るか）。

ここで見ないもの:
- ルート線側の境界への写し（`map_value_thresholds`） → `test_dynamic_way_values.py`
- 軸の宣言そのものの検査・評価 → `test_axis_definitions.py`
- 管理APIが下書きの段を問い合わせる口 → `test_axis_admin_routes.py`

**材料カタログと軸の集合は差し替える。** 地図に出せるかは材料の性質（タイルに焼き込み済みか・
向きで値が変わるか・欠損の意味）だけで決まるので、その性質だけを持つ架空の材料を与える。
"""

import pytest

from app.domain import axis_display, material_catalog
from app.domain.axis_definitions import (
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    PriorityCondition,
)

TileInput = axis_display.TileInputSpec


def material(material_id, dtype="numeric", tile_property=None, missing_semantics="unknown", **fields):
    return material_catalog.MaterialSpec(
        material_id=material_id,
        label=material_id,
        description=material_id,
        dtype=dtype,
        tile_property=tile_property,
        coverage=material_catalog.CoverageExcluded(reason="テスト用", missing_semantics=missing_semantics),
        **fields,
    )


BOOL_TERM_IDS = [f"bool_{i}" for i in range(13)]


@pytest.fixture
def catalog(monkeypatch):
    specs = {
        "num_a": material("num_a", tile_property="p_num_a"),
        "num_b": material("num_b", tile_property="p_num_b"),
        "num_scaled": material("num_scaled", tile_property="p_scaled", tile_property_needs_runtime_scale=True),
        "num_dir": material("num_dir", tile_property="p_dir", tile_property_direction_dependent=True),
        "num_notile": material("num_notile"),
        "bool_unknown": material("bool_unknown", dtype="boolean", tile_property="p_bu"),
        "bool_false": material("bool_false", dtype="boolean", tile_property="p_bf", missing_semantics="definite"),
        "cat_a": material("cat_a", dtype="categorical", tile_property="p_cat"),
        "cat_notile": material("cat_notile", dtype="categorical"),
        **{
            m: material(m, dtype="boolean", tile_property=f"p_{m}", missing_semantics="definite") for m in BOOL_TERM_IDS
        },
    }
    monkeypatch.setattr(axis_display, "MATERIAL_CATALOG", specs)
    return specs


@pytest.fixture
def axes(monkeypatch):
    def install(*definitions: AxisDefinition) -> None:
        monkeypatch.setattr(axis_display, "AXIS_DEFINITIONS", {d.axis_id: d for d in definitions})

    install()
    return install


def term(material_id, weight=1.0):
    return MaterialTerm(material=material_id, weight=weight)


def linear(*terms, breakpoints=((0.0, 0.0), (10.0, 100.0)), preprocess="identity"):
    return BreakpointLinearShape(
        terms=[t if isinstance(t, MaterialTerm) else term(t) for t in terms],
        breakpoints=list(breakpoints),
        preprocess=preprocess,
    )


def categorical(material_id, mapping):
    return CategoricalShape(material=material_id, mapping=mapping)


def axis(axis_id, shape, **fields):
    return AxisDefinition(axis_id=axis_id, label=f"{axis_id}の表示名", default_weight=1.0, shape=shape, **fields)


def display(shape, **fields):
    return axis_display.axis_display_for(axis("a", shape, **fields))


def ramp(tile_inputs, thresholds):
    return axis_display.AxisDisplaySpec(kind="ramp", label="aの表示名", tile_inputs=tile_inputs, thresholds=thresholds)


NONE = axis_display.AxisDisplaySpec(kind="none", label="aの表示名")


@pytest.mark.usefixtures("catalog", "axes")
class TestCategoricalAxis:
    @pytest.mark.parametrize(
        ("material_id", "tile_property", "unknown_is_its_own_band"),
        [("bool_unknown", "p_bu", True), ("bool_false", "p_bf", False)],
    )
    def test_a_flag_is_drawn_with_both_scores_split_at_their_midpoint(
        self, material_id, tile_property, unknown_is_its_own_band
    ):
        """欠損が「不明」を意味する材料だけ、値の無い道を不明として塗る。"""
        result = display(categorical(material_id, {True: 20.0, False: 80.0}))

        tile_input = TileInput(
            property=tile_property,
            boolean=True,
            true_value=20.0,
            false_value=80.0,
            has_unknown_fallback=unknown_is_its_own_band,
        )
        assert result == ramp([tile_input], [50.0])

    def test_a_flag_mapping_without_both_values_is_not_drawn(self):
        assert display(categorical("bool_unknown", {True: 10.0})) == NONE

    def test_named_values_are_drawn_with_unregistered_values_as_unknown(self):
        result = display(categorical("cat_a", {"x": 0.0, "v": 50.0, "z": 50.0, "w": 100.0}))

        tile_input = TileInput(
            property="p_cat", categories={"w": 100.0, "x": 0.0, "v": 50.0, "z": 50.0}, has_unknown_fallback=True
        )
        assert result == ramp([tile_input], [25.0, 75.0])

    def test_named_values_that_all_score_the_same_have_no_band_to_draw(self):
        assert display(categorical("cat_a", {"x": 10.0, "v": 10.0})) == NONE

    @pytest.mark.parametrize("material_id", ["cat_notile", "ref"], ids=["タイルに無い材料", "軸の参照"])
    def test_a_value_the_tile_does_not_carry_is_not_drawn(self, axes, material_id):
        axes(axis("ref", linear("num_a")))

        assert display(categorical(material_id, {"x": 0.0, "v": 100.0})) == NONE


@pytest.mark.usefixtures("catalog", "axes")
class TestLinearAxis:
    def test_numeric_terms_are_summed_on_the_map_and_cut_at_the_breakpoints(self):
        """タイルの生値が実行時の係数を要する材料も塗る（係数はフロントが掛ける）。"""
        result = display(linear("num_a", term("num_scaled", 0.5), breakpoints=[(0.0, 0.0), (5.0, 50.0), (10.0, 100.0)]))

        assert result == ramp(
            [TileInput(property="p_num_a"), TileInput(property="p_scaled", weight=0.5, needs_runtime_scale=True)],
            [5.0, 10.0],
        )

    def test_a_flag_among_numeric_terms_contributes_its_weight_when_set(self):
        result = display(linear("num_a", term("bool_false", 30.0)))

        assert result == ramp(
            [TileInput(property="p_num_a"), TileInput(property="p_bf", boolean=True, true_value=30.0)], [10.0]
        )

    def test_flags_only_are_cut_between_the_sums_they_can_reach_capped_at_the_last_breakpoint(self):
        """重み20・50の2つのフラグが取れる和は0・20・50・70で、70は折れ線の端60で頭打ちになる。"""
        result = display(
            linear(term("bool_unknown", 20.0), term("bool_false", 50.0), breakpoints=[(0.0, 0.0), (60.0, 100.0)])
        )

        assert result.thresholds == [10.0, 35.0, 55.0]

    @pytest.mark.parametrize(("count", "drawn"), [(12, True), (13, False)])
    def test_flags_only_are_drawn_up_to_twelve_terms(self, count, drawn):
        result = display(linear(*BOOL_TERM_IDS[:count]))

        assert (result.kind == "ramp") is drawn

    @pytest.mark.parametrize(
        "shape",
        [
            linear("num_a", preprocess="abs"),
            linear("num_a", "ghost"),
            linear("num_a", "num_notile"),
            linear("num_a", "num_dir"),
        ],
        ids=["符号を畳む", "カタログにも軸にも無いid", "タイルに無い材料", "向きで値が変わる材料"],
    )
    def test_shapes_the_map_cannot_reproduce_are_not_drawn(self, shape):
        assert display(shape) == NONE

    def test_an_override_material_the_tile_does_not_carry_keeps_the_axis_off_the_map(self):
        result = display(
            linear("num_a"), priority_overrides=[PriorityCondition(material="num_notile", equals="1", value=0.0)]
        )

        assert result == NONE


@pytest.mark.usefixtures("catalog")
class TestReferencedAxis:
    """参照先の軸を、地図が同じ値を再現できる1件のタイル入力へ畳めるときだけ塗る。"""

    def outer(self, weight=0.5):
        return linear(term("ref", weight), breakpoints=[(0.0, 0.0), (100.0, 100.0)])

    def test_a_referenced_flag_axis_contributes_its_scores_times_the_weight(self, axes):
        axes(axis("ref", categorical("bool_unknown", {True: 80.0, False: 0.0})))

        assert display(self.outer()).tile_inputs == [
            TileInput(property="p_bu", boolean=True, true_value=40.0, has_unknown_fallback=True)
        ]

    def test_a_referenced_named_value_axis_contributes_its_scores_times_the_weight(self, axes):
        axes(axis("ref", categorical("cat_a", {"x": 10.0, "v": 30.0})))

        assert display(self.outer(2.0)).tile_inputs == [
            TileInput(property="p_cat", categories={"x": 20.0, "v": 60.0}, has_unknown_fallback=True)
        ]

    def test_a_referenced_single_material_curve_is_applied_to_the_tile_value(self, axes):
        axes(axis("ref", linear("num_a", breakpoints=[(0.0, 0.0), (4.0, 100.0)])))

        assert display(self.outer()).tile_inputs == [
            TileInput(property="p_num_a", breakpoints=[(0.0, 0.0), (4.0, 100.0)], weight=0.5)
        ]

    @pytest.mark.parametrize(
        "referenced",
        [
            categorical("cat_notile", {"x": 0.0, "v": 1.0}),
            linear("num_a", preprocess="abs"),
            linear("num_a", "num_b"),
            linear(term("num_a", 2.0)),
            linear("inner"),
            linear("num_notile"),
            linear("num_dir"),
            linear("num_scaled"),
            linear("bool_false"),
        ],
        ids=[
            "塗れない分類",
            "符号を畳む",
            "複数の項",
            "内側の重みが1でない",
            "さらに軸を参照する",
            "タイルに無い材料",
            "向きで値が変わる材料",
            "実行時の係数が要る材料",
            "フラグ",
        ],
    )
    def test_referenced_axes_the_tile_form_cannot_express_keep_the_outer_axis_off_the_map(self, axes, referenced):
        axes(axis("ref", referenced), axis("inner", linear("num_a")))

        assert display(self.outer()) == NONE


@pytest.mark.usefixtures("catalog", "axes")
class TestBands:
    """段の境界は、折れ線が写した得点が直前の境界の得点を上回らないものを落とす。上書きした境界も
    同じ扱い。"""

    PLATEAU = [(0.0, 0.0), (5.0, 50.0), (6.0, 50.0), (10.0, 100.0)]

    def test_a_breakpoint_on_a_plateau_is_not_a_band_boundary(self):
        assert display(linear("num_a", breakpoints=self.PLATEAU)).thresholds == [5.0, 10.0]

    def test_scores_that_round_to_the_same_tenth_are_the_same_score(self):
        breakpoints = [(0.0, 0.0), (5.0, 50.0), (6.0, 50.04), (10.0, 100.0)]

        assert display(linear("num_a", breakpoints=breakpoints)).thresholds == [5.0, 10.0]

    def test_a_curve_whose_score_falls_keeps_only_its_first_boundary(self):
        """ルート線は難易度の昇順でしか段を切れないため、得点が下がる境界を地図にも作らない。"""
        breakpoints = [(0.0, 100.0), (5.0, 50.0), (10.0, 0.0)]

        assert display(linear("num_a", breakpoints=breakpoints)).thresholds == [5.0]

    def test_overridden_thresholds_replace_the_breakpoints_and_lose_those_on_a_plateau(self):
        result = display(linear("num_a", breakpoints=self.PLATEAU), display_thresholds_override=[2.0, 5.5, 6.0, 8.0])

        assert result.thresholds == [2.0, 5.5, 8.0]

    def test_overridden_thresholds_of_a_named_value_axis_are_kept_as_given(self):
        result = display(categorical("cat_a", {"x": 0.0, "v": 100.0}), display_thresholds_override=[10.0, 20.0])

        assert result.thresholds == [10.0, 20.0]

    def test_bands_the_map_keeps_are_numbered_by_the_input_band_they_start_with(self):
        """境界5.5が落ちると、5〜5.5と5.5〜6の段が1つにまとまり、下側（入力の段1）として扱われる。"""
        args = ("a", linear("num_a", breakpoints=self.PLATEAU), [], [5.0, 5.5, 8.0])

        assert axis_display.bands_the_map_keeps(*args) == [0, 1, 3]
        assert axis_display.thresholds_the_map_drops(*args) == [5.5]

    def test_an_axis_the_map_does_not_draw_keeps_every_input_band(self):
        args = ("a", linear("num_a", preprocess="abs"), [], [1.0, 2.0])

        assert axis_display.bands_the_map_keeps(*args) == [0, 1, 2]
        assert axis_display.thresholds_the_map_drops(*args) == []

    def test_band_labels_follow_the_bands_the_map_keeps(self):
        definition = axis(
            "a",
            linear("num_a", breakpoints=self.PLATEAU),
            display_thresholds_override=[5.0, 5.5, 8.0],
            display_band_labels_override=["低", "中", "中2", "高"],
        )

        assert axis_display.map_band_labels(definition) == ["低", "中", "高"]

    def test_an_axis_without_band_labels_has_none(self):
        assert axis_display.map_band_labels(axis("a", linear("num_a"))) is None
