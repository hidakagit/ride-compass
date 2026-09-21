"""`domain/dynamic_way_values.py`——専用way値レイヤーを持つ軸の宣言と、地図が塗る値。

ここで見るのは**軸の宣言から何が導かれるか**だけ。軸そのものの評価は
`test_axis_definitions.py`、ramp表示の導出は`test_axis_display.py`、配信サービスの実装は
`test_wind_way_service.py`・`test_gradient_way_service.py`が持つ。
"""

from app.domain import dynamic_way_values as module
from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
)
from app.domain.dynamic_way_values import (
    dedicated_way_value_axes,
    map_value_kind,
    map_value_thresholds,
    map_value_unit,
    transform_dedicated_way_values,
)
from tests.axis_system_fixture import axis_definitions_snapshot

# 地図へ焼き込める材料（tile_propertyを持つ）と、焼き込めない材料。後者だけを使う軸は
# ramp表示を導出できない。
ON_TILE = "trees_percent"
ON_TILE_2 = "built_percent"
OFF_TILE = "gradient_percent"

LINE = [(0.0, 0.0), (10.0, 100.0)]


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
    """どの軸が専用way値レイヤーを持つかは、軸の宣言だけで決まる。"""

    def test_only_axes_that_declare_the_layer_are_listed(self):
        with axis_definitions_snapshot():
            AXIS_DEFINITIONS.clear()
            AXIS_DEFINITIONS["with_layer"] = _linear(
                [MaterialTerm(material=OFF_TILE)], LINE, dedicated_way_value_layer=True
            )
            AXIS_DEFINITIONS["without_layer"] = _linear([MaterialTerm(material=OFF_TILE)], LINE)

            assert set(dedicated_way_value_axes()) == {"with_layer"}

    def test_required_parameters_are_copied_from_the_axis(self):
        with axis_definitions_snapshot():
            AXIS_DEFINITIONS.clear()
            AXIS_DEFINITIONS["a"] = _linear(
                [MaterialTerm(material=OFF_TILE)],
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
                [MaterialTerm(material=OFF_TILE)], LINE, dedicated_way_value_layer=True
            )

            assert set(dedicated_way_value_axes()) == {"late"}


class TestMapValueKind:
    """地図が塗るのは得点か、材料の生値か。"""

    def test_single_term_with_abs_paints_the_signed_material(self):
        """絶対値で評価する単一材料の軸は符号が意味を持つ（登り／下り）。地図は得点では
        なく生値を塗り、符号を残す。"""
        axis = _linear([MaterialTerm(material=OFF_TILE)], LINE, preprocess="abs")

        assert map_value_kind(axis) == "signed_material"

    def test_single_term_without_abs_paints_the_difficulty(self):
        axis = _linear([MaterialTerm(material=OFF_TILE)], LINE)

        assert map_value_kind(axis) == "difficulty"

    def test_several_terms_paint_the_difficulty_even_with_abs(self):
        """項が増えると、和の符号は個々の材料の向きを表さない。"""
        axis = _linear(
            [MaterialTerm(material=ON_TILE), MaterialTerm(material=ON_TILE_2)], LINE, preprocess="abs"
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
    """ルート確定前の全道路の塗りと、確定後のルート線は同じ段で塗る。前者は材料の目盛り、
    後者は0〜100の目盛りなので、同じ段を言い直す必要がある。"""

    def test_axis_without_ramp_display_returns_its_override_as_is(self):
        """地図へ焼けない材料の軸はramp表示を持たない。上書きがあればそのまま返す——塗る値
        そのものに対する境界で、写す相手が無い。"""
        axis = _linear([MaterialTerm(material=OFF_TILE)], LINE, thresholds=[1.0, 2.0])

        assert map_value_thresholds(axis) == [1.0, 2.0]

    def test_axis_without_ramp_display_and_without_override_is_none(self):
        """読む側が種類ごとの既定を使う。ここで既定を作らない。"""
        axis = _linear([MaterialTerm(material=OFF_TILE)], LINE)

        assert map_value_thresholds(axis) is None

    def test_axis_that_folds_the_sign_never_gets_a_ramp_display(self):
        """`preprocess="abs"`の軸に地図側の式は無い（axis_display.py）。つまり生値を塗る軸
        （signed_material）はramp表示を持たず、境界は常に上書きがそのまま出る。"""
        axis = _linear(
            [MaterialTerm(material=ON_TILE)],
            [(0.0, 0.0), (50.0, 100.0)],
            preprocess="abs",
            thresholds=[10.0, 20.0],
        )

        assert map_value_kind(axis) == "signed_material"
        # 写していれば[20.0, 40.0]になる。
        assert map_value_thresholds(axis) == [10.0, 20.0]

    def test_categorical_ramp_thresholds_are_not_mapped(self):
        """分類の軸の段はもともと得点の目盛りで書かれている。折れ線が無く、写す相手も無い。"""
        axis = AxisDefinition(
            axis_id="synthetic_categorical",
            shape=CategoricalShape(material="surface_good", mapping={True: 0.0, False: 80.0}),
            default_weight=0.1,
            label="テスト軸",
            display_thresholds_override=[30.0, 60.0],
        )

        assert map_value_thresholds(axis) == [30.0, 60.0]

    def test_difficulty_thresholds_are_mapped_through_the_axis_line(self):
        axis = _linear(
            [MaterialTerm(material=ON_TILE), MaterialTerm(material=ON_TILE_2)],
            [(0.0, 0.0), (50.0, 100.0)],
            thresholds=[10.0, 20.0],
        )

        assert map_value_thresholds(axis) == [20.0, 40.0]

    def test_negative_material_scale_thresholds_are_mapped_with_their_sign(self):
        """材料の目盛りは負にもなる（重みが負の項）。符号を保ったまま折れ線へ通す。"""
        axis = _linear(
            [
                MaterialTerm(material=ON_TILE, weight=-1.0),
                MaterialTerm(material=ON_TILE_2, weight=-1.0),
            ],
            [(-50.0, 0.0), (0.0, 100.0)],
            thresholds=[-40.0, -10.0],
        )

        assert map_value_thresholds(axis) == [20.0, 80.0]


class TestMapValueUnit:
    """凡例に添える単位。"""

    def test_difficulty_axis_has_no_unit(self):
        """得点は無次元。材料の単位を借りない。"""
        axis = _linear([MaterialTerm(material=OFF_TILE)], LINE)

        assert map_value_unit(axis) == ""

    def test_signed_material_axis_takes_the_unit_from_the_material_catalog(self):
        axis = _linear([MaterialTerm(material=OFF_TILE)], LINE, preprocess="abs")

        assert map_value_unit(axis) == "%"


class TestTransformDedicatedWayValues:
    """配信サービスが返した材料の生値を、地図が塗る値へ変える。"""

    def test_signed_material_values_pass_through(self):
        axis = _linear([MaterialTerm(material=OFF_TILE)], LINE, preprocess="abs")
        values = {"1": -4.2, "2": 3.1}

        assert transform_dedicated_way_values(axis, OFF_TILE, values) == values

    def test_difficulty_values_are_evaluated_through_the_axis(self):
        axis = _linear([MaterialTerm(material=OFF_TILE)], [(0.0, 0.0), (4.0, 100.0)])

        assert transform_dedicated_way_values(axis, OFF_TILE, {"1": 1.0, "2": 9.0}) == {"1": 25.0, "2": 100.0}

    def test_roads_the_axis_cannot_evaluate_are_dropped(self):
        """軸が他の材料も必須にしていると、配信された材料だけでは評価できない。その道路は
        結果から落とす——0点で塗ると最良の色になってしまう。"""
        axis = _linear(
            [
                MaterialTerm(material=OFF_TILE, required=True),
                MaterialTerm(material=ON_TILE, required=True),
            ],
            LINE,
        )

        assert transform_dedicated_way_values(axis, OFF_TILE, {"1": 1.0}) == {}

    def test_the_same_material_value_is_evaluated_once(self):
        """タイル内が全て同値になる軸（風）があるため、値ごとに1回だけ評価する。"""
        axis = _linear([MaterialTerm(material=OFF_TILE)], [(0.0, 0.0), (4.0, 100.0)])
        seen: list[float] = []
        original = module.evaluate_axis_scalar

        def counting(definition, materials):
            seen.append(materials[OFF_TILE])
            return original(definition, materials)

        module.evaluate_axis_scalar = counting
        try:
            result = transform_dedicated_way_values(axis, OFF_TILE, {"1": 2.0, "2": 2.0, "3": 3.0})
        finally:
            module.evaluate_axis_scalar = original

        assert result == {"1": 50.0, "2": 50.0, "3": 75.0}
        assert seen == [2.0, 3.0]
