"""`domain/dynamic_way_values.py`——専用way値レイヤーを持つ軸の宣言と、地図が塗る値。

ここで見るのは**軸の宣言から何が導かれるか**だけ。軸そのものの評価は
`test_axis_definitions.py`、ramp表示の導出は`test_axis_display.py`、配信サービスの実装は
`test_wind_way_service.py`・`test_gradient_way_service.py`が持つ。
"""

from contextlib import contextmanager

from app.domain import dynamic_way_values as module
from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
)
from app.domain.axis_display import axis_display_for
from app.domain.registry import AxisDisplaySpec
from app.domain.dynamic_way_values import (
    dedicated_way_value_axes,
    map_value_kind,
    map_value_thresholds,
    map_value_unit,
    transform_dedicated_way_values,
)
from tests.axis_system_fixture import axis_definitions_snapshot

# 材料は「どれか実在のid」でよく、どれを選ぶかに意味を持たせない——**この軸が地図に出るか
# どうかは`axis_display.py`の判断で、ここでは差し替えて与える**。
A = "gradient_percent"
B = "trees_percent"

LINE = [(0.0, 0.0), (10.0, 100.0)]


@contextmanager
def _display(kind: str, thresholds: list[float] | None = None):
    """`axis_display_for`が返す表示スペックを差し替える。

    ramp表示を導出できるかは`axis_display.py`の責務で、実在材料の組み合わせで作り出すと
    あちらが変わるたびにここが落ちる。
    """
    original = module.axis_display_for
    module.axis_display_for = lambda definition: AxisDisplaySpec(
        kind=kind, label=definition.label, thresholds=list(thresholds or [])
    )
    try:
        yield
    finally:
        module.axis_display_for = original


def _linear(
    terms: list[MaterialTerm],
    breakpoints: list[tuple[float, float]],
    preprocess: str = "identity",
    thresholds: list[float] | None = None,
    **overrides,
) -> AxisDefinition:
    return AxisDefinition(
        axis_id="synthetic_linear",
        shape=BreakpointLinearShape(terms=terms, preprocess=preprocess, breakpoints=breakpoints),
        default_weight=0.1,
        label="テスト軸",
        display_thresholds_override=thresholds,
        **overrides,
    )


class TestDedicatedWayValueAxes:

    def test_only_axes_that_declare_the_layer_are_listed(self):
        with axis_definitions_snapshot():
            AXIS_DEFINITIONS.clear()
            AXIS_DEFINITIONS["with_layer"] = _linear(
                [MaterialTerm(material=A)], LINE, dedicated_way_value_layer=True
            )
            AXIS_DEFINITIONS["without_layer"] = _linear([MaterialTerm(material=A)], LINE)

            assert set(dedicated_way_value_axes()) == {"with_layer"}

    def test_required_parameters_are_copied_from_the_axis(self):
        with axis_definitions_snapshot():
            AXIS_DEFINITIONS.clear()
            AXIS_DEFINITIONS["a"] = _linear(
                [MaterialTerm(material=A)],
                LINE,
                dedicated_way_value_layer=True,
                dynamic_way_value_needs_time=True,
                dynamic_way_value_needs_bearing=False,
                dynamic_way_value_needs_speed=True,
            )

            axis = dedicated_way_value_axes()["a"]

            assert (axis.needs_time, axis.needs_bearing, axis.needs_speed) == (True, False, True)
            assert axis.label == "テスト軸"

    def test_the_set_is_derived_on_every_call(self):
        """軸は実行中に増減する（起動時の読み込み・管理APIの書き込み）。定数へ畳むと、
        書き込んだ直後の呼び出しが古い集合を返す。"""
        with axis_definitions_snapshot():
            AXIS_DEFINITIONS.clear()
            assert dedicated_way_value_axes() == {}

            AXIS_DEFINITIONS["late"] = _linear(
                [MaterialTerm(material=A)], LINE, dedicated_way_value_layer=True
            )

            assert set(dedicated_way_value_axes()) == {"late"}


class TestMapValueKind:
    """地図が塗るのは得点か、材料の生値か。"""

    def test_single_term_with_abs_paints_the_signed_material(self):
        """絶対値で評価する単一材料の軸は符号が意味を持つ（登り／下り）。地図は得点では
        なく生値を塗り、符号を残す。"""
        axis = _linear([MaterialTerm(material=A)], LINE, preprocess="abs")

        assert map_value_kind(axis) == "signed_material"

    def test_single_term_without_abs_paints_the_difficulty(self):
        axis = _linear([MaterialTerm(material=A)], LINE)

        assert map_value_kind(axis) == "difficulty"

    def test_several_terms_paint_the_difficulty_even_with_abs(self):
        """項が増えると、和の符号は個々の材料の向きを表さない。"""
        axis = _linear(
            [MaterialTerm(material=B), MaterialTerm(material=B)], LINE, preprocess="abs"
        )

        assert map_value_kind(axis) == "difficulty"

    def test_categorical_axis_paints_the_difficulty(self):
        axis = AxisDefinition(
            axis_id="synthetic_categorical",
            shape=CategoricalShape(material="surface_good", mapping={True: 0.0, False: 80.0}),
            default_weight=0.1,
            label="テスト軸",
        )

        assert map_value_kind(axis) == "difficulty"


class TestMapValueThresholds:
    """**どの軸がramp表示を持つかは`axis_display.py`が決める。** ここではその判断を
    差し替えて与え、与えられた種類に対して何を返すかだけを見る。
    """

    def test_an_axis_without_a_ramp_display_returns_its_override_as_is(self):
        """塗る値そのものに対する境界で、写す相手が無い。"""
        axis = _linear([MaterialTerm(material=A)], LINE, thresholds=[1.0, 2.0])

        with _display("none"):
            assert map_value_thresholds(axis) == [1.0, 2.0]

    def test_an_axis_without_a_ramp_display_and_without_an_override_is_none(self):
        """ここで既定を作らない。"""
        axis = _linear([MaterialTerm(material=A)], LINE)

        with _display("none"):
            assert map_value_thresholds(axis) is None

    def test_a_categorical_axis_is_not_mapped(self):
        """分類の軸の段はもともと得点の目盛りで書かれている。通す折れ線が無い。"""
        axis = AxisDefinition(
            axis_id="synthetic_categorical",
            shape=CategoricalShape(material="surface_good", mapping={True: 0.0, False: 80.0}),
            default_weight=0.1,
            label="テスト軸",
        )

        with _display("ramp", thresholds=[30.0, 60.0]):
            assert map_value_thresholds(axis) == [30.0, 60.0]

    def test_a_difficulty_axis_is_mapped_through_its_own_line(self):
        axis = _linear([MaterialTerm(material=A), MaterialTerm(material=B)], [(0.0, 0.0), (50.0, 100.0)])

        with _display("ramp", thresholds=[10.0, 20.0]):
            assert map_value_thresholds(axis) == [20.0, 40.0]

    def test_a_negative_material_scale_keeps_its_sign_through_the_line(self):
        """材料の目盛りは負にもなる（重みが負の項）。符号を落とすと折れ線の下端へ張り付き、
        全段が同じ値になる。
        """
        axis = _linear(
            [MaterialTerm(material=A, weight=-1.0), MaterialTerm(material=B, weight=-1.0)],
            [(-50.0, 0.0), (0.0, 100.0)],
        )

        with _display("ramp", thresholds=[-40.0, -10.0]):
            assert map_value_thresholds(axis) == [20.0, 80.0]

    def test_an_axis_that_folds_the_sign_is_never_asked_to_map(self):
        """この前提が崩れたら、写す側に絶対値を取る処理が要る。"""
        axis = _linear([MaterialTerm(material=A)], LINE, preprocess="abs")

        assert map_value_kind(axis) == "signed_material"
        assert axis_display_for(axis).kind == "none"


class TestMapValueUnit:
    """凡例に添える単位。**材料カタログの中身には踏み込まない**——差し替えて与える。"""

    @staticmethod
    @contextmanager
    def _catalog(unit: str | None):
        original = module.MATERIAL_CATALOG
        spec = None if unit is None else type("Spec", (), {"unit": unit})()
        module.MATERIAL_CATALOG = {A: spec} if spec is not None else {}
        try:
            yield
        finally:
            module.MATERIAL_CATALOG = original

    def test_a_difficulty_axis_has_no_unit(self):
        """得点は無次元。材料の単位を借りない。"""
        axis = _linear([MaterialTerm(material=A)], LINE)

        with self._catalog("%"):
            assert map_value_unit(axis) == ""

    def test_a_signed_material_axis_takes_the_unit_of_its_material(self):
        axis = _linear([MaterialTerm(material=A)], LINE, preprocess="abs")

        with self._catalog("%"):
            assert map_value_unit(axis) == "%"

    def test_a_material_the_catalog_does_not_know_has_no_unit(self):
        """カタログに無い材料を参照する軸で例外にせず、空へ倒す。"""
        axis = _linear([MaterialTerm(material=A)], LINE, preprocess="abs")

        with self._catalog(None):
            assert map_value_unit(axis) == ""


class TestTransformDedicatedWayValues:

    def test_signed_material_values_pass_through(self):
        axis = _linear([MaterialTerm(material=A)], LINE, preprocess="abs")
        values = {"1": -4.2, "2": 3.1}

        assert transform_dedicated_way_values(axis, A, values) == values

    def test_difficulty_values_are_evaluated_through_the_axis(self):
        axis = _linear([MaterialTerm(material=A)], [(0.0, 0.0), (4.0, 100.0)])

        assert transform_dedicated_way_values(axis, A, {"1": 1.0, "2": 9.0}) == {"1": 25.0, "2": 100.0}

    def test_roads_the_axis_cannot_evaluate_are_dropped(self):
        """0点で塗ると、最良の色になってしまう。"""
        axis = _linear(
            [
                MaterialTerm(material=A, required=True),
                MaterialTerm(material=B, required=True),
            ],
            LINE,
        )

        assert transform_dedicated_way_values(axis, A, {"1": 1.0}) == {}

    def test_the_same_material_value_is_evaluated_once(self):
        """タイル内が全て同値になる軸（風）があるため、値ごとに1回だけ評価する。"""
        axis = _linear([MaterialTerm(material=A)], [(0.0, 0.0), (4.0, 100.0)])
        seen: list[float] = []
        original = module.evaluate_axis_scalar

        def counting(definition, materials):
            seen.append(materials[A])
            return original(definition, materials)

        module.evaluate_axis_scalar = counting
        try:
            result = transform_dedicated_way_values(axis, A, {"1": 2.0, "2": 2.0, "3": 3.0})
        finally:
            module.evaluate_axis_scalar = original

        assert result == {"1": 50.0, "2": 50.0, "3": 75.0}
        assert seen == [2.0, 3.0]
