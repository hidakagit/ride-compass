"""`domain/axis_display.py`——軸を地図にどう塗るか（タイルから読む値の式と段の境界）を、軸の形と材料の性質から決める。

入口は`axis_display_for`（軸カタログが配る表示）と、軸スタジオが保存前の下書きで問う`bands_the_map_keeps`・
`thresholds_the_map_drops`、凡例の体感ラベルを地図の段へ引き直す`map_band_labels`。

材料カタログと軸の集合は本番の正本を読まず、性質だけを持つ架空の材料・軸へ差し替える（`MATERIAL_CATALOG`・
`AXIS_DEFINITIONS`）。

ここで見ないもの:
- 地図表示の宣言の型の検証（形の重複・`kind`と中身の食い違い・境界の昇順） → `test_registry.py`
- 折れ線の得点そのもの（`domain/axis_definitions.py: BreakpointLinearShape.score_at`） → `test_axis_definitions.py`
- ルート線の段の境界（`domain/map_paint.py: map_paint`） → `test_map_paint.py`
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain import axis_display
from app.domain.axis_definitions import (
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    PriorityCondition,
)
from app.domain.axis_display import (
    axis_display_for,
    bands_the_map_keeps,
    map_band_labels,
    thresholds_the_map_drops,
)
from app.domain.material_catalog import CoverageExcluded, MaterialSpec
from app.domain.registry import TileInputSpec


def _material(material_id, dtype, *, tile=True, unknown=False, **fields) -> MaterialSpec:
    return MaterialSpec(
        material_id=material_id,
        label=material_id,
        description="架空の材料",
        dtype=dtype,
        tile_property=f"{material_id}_tile" if tile else None,
        value_sql=f"w.{material_id}",
        coverage=CoverageExcluded(reason="架空", missing_semantics="unknown" if unknown else "definite"),
        **fields,
    )


CATALOG = {
    spec.material_id: spec
    for spec in [
        _material("num_a", "numeric"),
        _material("num_per_year", "numeric", tile_property_runtime_scale="per_accident_year"),
        _material("num_directional", "numeric", tile_property_direction_dependent=True),
        _material("num_untiled", "numeric", tile=False),
        _material("flag", "boolean"),
        _material("flag_unknown", "boolean", unknown=True),
        _material("kind", "categorical"),
        _material("kind_untiled", "categorical", tile=False),
    ]
}


@pytest.fixture
def axes(monkeypatch) -> dict[str, AxisDefinition]:
    """保存済みの軸の集合（空から）。参照先の軸が要るテストはここへ足す。"""
    saved: dict[str, AxisDefinition] = {}
    monkeypatch.setattr(axis_display, "MATERIAL_CATALOG", CATALOG)
    monkeypatch.setattr(axis_display, "AXIS_DEFINITIONS", saved)
    return saved


pytestmark = pytest.mark.usefixtures("axes")


def _line(*terms, breakpoints=((0.0, 0.0), (10.0, 100.0)), preprocess="identity") -> BreakpointLinearShape:
    return BreakpointLinearShape(
        terms=[term if isinstance(term, MaterialTerm) else MaterialTerm(material=term) for term in terms],
        breakpoints=list(breakpoints),
        preprocess=preprocess,
    )


def _axis(shape, axis_id="axis_a", **fields) -> AxisDefinition:
    return AxisDefinition(axis_id=axis_id, shape=shape, default_weight=1.0, label="軸A", **fields)


def _drawn(shape, **fields):
    display = axis_display_for(_axis(shape, **fields))
    assert display.kind == "ramp"
    return display


NOT_ON_THE_MAP = {
    "0次条件を持つ": _axis(_line("num_a"), priority_overrides=[PriorityCondition(material="flag", equals="true", value=0)]),
    "タイルに無い材料": _axis(_line("num_a", "num_untiled")),
    "向きで値が変わる材料": _axis(_line("num_directional")),
    "どこにも無い材料": _axis(_line("nowhere")),
    "符号を畳む前処理": _axis(_line("num_a", preprocess="abs")),
    "得点が1つしかない分類": _axis(CategoricalShape(material="kind", mapping={"x": 50.0, "y": 50.0})),
    "真偽の片方しか無い対応表": _axis(CategoricalShape(material="flag", mapping={True: 100.0})),
}


@pytest.mark.parametrize("definition", NOT_ON_THE_MAP.values(), ids=NOT_ON_THE_MAP.keys())
def test_an_axis_the_tile_cannot_reproduce_is_not_drawn(definition):
    """地図の色がルート選び・区間の内訳と食い違うくらいなら、地図に出さない。"""
    display = axis_display_for(definition)

    assert (display.kind, display.label, display.tile_inputs, display.thresholds) == ("none", "軸A", [], [])


def test_a_categorical_axis_over_another_axis_is_not_drawn(axes):
    axes["inner"] = _axis(_line("num_a"), axis_id="inner")

    assert axis_display_for(_axis(CategoricalShape(material="inner", mapping={"x": 0.0, "y": 100.0}))).kind == "none"


@pytest.mark.parametrize(("material", "unknown"), [("flag", False), ("flag_unknown", True)])
def test_a_flag_axis_paints_its_two_scores_and_splits_them_in_the_middle(material, unknown):
    """タイルに値が無いことを「不明」とする材料だけ、地図も灰色の不明へ倒す。"""
    display = _drawn(CategoricalShape(material=material, mapping={True: 80.0, False: 20.0}))

    assert display.tile_inputs == [
        TileInputSpec(
            property=f"{material}_tile", boolean=True, true_value=80.0, false_value=20.0, has_unknown_fallback=unknown
        )
    ]
    assert display.thresholds == [50.0]


def test_a_named_value_axis_paints_its_table_and_splits_between_distinct_scores():
    """表に無い値は評価側で評価不能なので、地図も寄与0ではなく不明へ倒す。"""
    mapping = {"x": 10.0, "y": 50.0, "z": 50.0, "w": 90.0}

    display = _drawn(CategoricalShape(material="kind", mapping=mapping))

    assert display.tile_inputs == [TileInputSpec(property="kind_tile", categories=mapping, has_unknown_fallback=True)]
    assert display.thresholds == [30.0, 70.0]


def test_a_line_axis_paints_the_weighted_sum_and_splits_at_its_breakpoints():
    """実行時にしか決まらない係数が要る材料も、印を付けて地図に出す（係数は画面の式が掛ける）。"""
    display = _drawn(
        _line(
            MaterialTerm(material="num_a", weight=2.0),
            MaterialTerm(material="num_per_year", weight=0.5),
            MaterialTerm(material="flag_unknown", weight=30.0),
            breakpoints=[(0.0, 0.0), (5.0, 40.0), (10.0, 100.0)],
        )
    )

    assert display.tile_inputs == [
        TileInputSpec(property="num_a_tile", weight=2.0),
        TileInputSpec(property="num_per_year_tile", weight=0.5, needs_runtime_scale=True),
        TileInputSpec(
            property="flag_unknown_tile", boolean=True, true_value=30.0, false_value=0.0, has_unknown_fallback=True
        ),
    ]
    assert display.thresholds == [5.0, 10.0]


def test_a_line_axis_of_flags_splits_between_the_sums_it_can_take():
    """真偽の項だけの和は部分和しか取らないので、境界はその間に引く。和は折れ線の右端で止まる。"""
    display = _drawn(
        _line(
            MaterialTerm(material="flag", weight=10.0),
            MaterialTerm(material="flag_unknown", weight=20.0),
            breakpoints=[(0.0, 0.0), (25.0, 100.0)],
        )
    )

    # 取りうる和は 0・10・20・30（右端25で止まる）。
    assert display.thresholds == [5.0, 15.0, 22.5]


def test_a_line_axis_of_up_to_twelve_flags_is_drawn_and_more_is_not():
    """部分和は2のN乗通りあるため、項の数で止める。"""

    def flags(count):
        return _axis(_line(*["flag"] * count, breakpoints=[(0.0, 0.0), (float(count), 100.0)]))

    assert len(axis_display_for(flags(12)).thresholds) == 12
    assert axis_display_for(flags(13)).kind == "none"


def test_a_term_over_a_named_value_axis_folds_the_outer_weight_into_its_scores(axes):
    axes["inner"] = _axis(CategoricalShape(material="kind", mapping={"x": 0.0, "y": 100.0}), axis_id="inner")

    display = _drawn(_line(MaterialTerm(material="inner", weight=0.5), breakpoints=[(0.0, 0.0), (50.0, 100.0)]))

    assert display.tile_inputs == [
        TileInputSpec(property="kind_tile", categories={"x": 0.0, "y": 50.0}, has_unknown_fallback=True)
    ]
    assert display.thresholds == [50.0]


def test_a_term_over_a_flag_axis_folds_the_outer_weight_into_its_two_scores(axes):
    axes["inner"] = _axis(CategoricalShape(material="flag", mapping={True: 100.0, False: 20.0}), axis_id="inner")

    display = _drawn(_line(MaterialTerm(material="inner", weight=0.5), breakpoints=[(0.0, 0.0), (50.0, 100.0)]))

    assert display.tile_inputs == [TileInputSpec(property="flag_tile", boolean=True, true_value=50.0, false_value=10.0)]
    assert display.thresholds == [50.0]


def test_a_term_over_a_line_axis_of_one_material_paints_that_line_on_the_tile_value(axes):
    axes["inner"] = _axis(_line("num_a", breakpoints=[(0.0, 0.0), (8.0, 100.0)]), axis_id="inner")

    display = _drawn(_line(MaterialTerm(material="inner", weight=0.5), breakpoints=[(0.0, 0.0), (50.0, 100.0)]))

    assert display.tile_inputs == [TileInputSpec(property="num_a_tile", breakpoints=[(0.0, 0.0), (8.0, 100.0)], weight=0.5)]


INNER_AXES_THAT_DO_NOT_FOLD = {
    "0次条件を持つ": _axis(
        _line("num_a"), axis_id="inner", priority_overrides=[PriorityCondition(material="flag", equals="true", value=0)]
    ),
    "符号を畳む": _axis(_line("num_a", preprocess="abs"), axis_id="inner"),
    "項が2つ": _axis(_line("num_a", "num_per_year"), axis_id="inner"),
    "内側の重みが1でない": _axis(_line(MaterialTerm(material="num_a", weight=2.0)), axis_id="inner"),
    "さらに軸を読む": _axis(_line("deeper"), axis_id="inner"),
    "向きで値が変わる材料": _axis(_line("num_directional"), axis_id="inner"),
    "実行時の係数が要る材料": _axis(_line("num_per_year"), axis_id="inner"),
    "真偽の材料": _axis(_line("flag"), axis_id="inner"),
    "塗れない分類": _axis(CategoricalShape(material="kind_untiled", mapping={"x": 0.0, "y": 100.0}), axis_id="inner"),
}


@pytest.mark.parametrize("inner", INNER_AXES_THAT_DO_NOT_FOLD.values(), ids=INNER_AXES_THAT_DO_NOT_FOLD.keys())
def test_an_axis_reading_an_axis_the_tile_cannot_reproduce_is_not_drawn(axes, inner):
    """内側の折れ線をタイルの値へ当てる形は、1つの材料をそのまま折れ線へ通すものしか書けない。"""
    axes["inner"] = inner
    axes["deeper"] = _axis(_line("num_a"), axis_id="deeper")

    assert axis_display_for(_axis(_line("num_a", "inner"))).kind == "none"


def test_a_draft_reading_its_own_saved_version_is_not_on_the_map_and_keeps_every_band(axes):
    """保存前の下書きは自分自身を読めてしまう（保存は循環として断られる）。保存済みの自分を材料として畳まない。"""
    axes["axis_a"] = _axis(_line("num_a"))

    assert bands_the_map_keeps("axis_a", _line("axis_a"), [], [1.0, 2.0]) == [0, 1, 2]


def test_a_named_value_axis_takes_the_overriding_boundaries_as_they_are():
    display = _drawn(
        CategoricalShape(material="kind", mapping={"x": 0.0, "y": 100.0}), display_thresholds_override=[10.0, 20.0, 30.0]
    )

    assert display.thresholds == [10.0, 20.0, 30.0]


STEPPED = _line("num_a", breakpoints=[(0.0, 0.0), (2.0, 50.0), (4.0, 50.0), (6.0, 100.0)])


def test_band_labels_are_taken_for_the_bands_left_on_the_map():
    """落ちた境界の上下は1つの段にまとまり、下端が同じ値の下側の段として扱う。"""
    definition = _axis(
        STEPPED, display_thresholds_override=[2.0, 3.0, 4.0, 6.0], display_band_labels_override=list("abcde")
    )

    assert map_band_labels(definition) == ["a", "b", "e"]


def test_band_labels_are_missing_without_overriding_labels():
    assert map_band_labels(_axis(STEPPED, display_thresholds_override=[2.0, 3.0])) is None


@st.composite
def _line_and_boundaries(draw):
    xs = sorted(draw(st.sets(st.integers(min_value=0, max_value=20), min_size=2, max_size=6)))
    ys = draw(st.lists(st.integers(min_value=0, max_value=100), min_size=len(xs), max_size=len(xs)))
    boundaries = sorted(draw(st.sets(st.integers(min_value=-5, max_value=25), min_size=1, max_size=8)))
    return _line("num_a", breakpoints=[(float(x), float(y)) for x, y in zip(xs, ys)]), [float(b) for b in boundaries]


@given(line_and_boundaries=_line_and_boundaries())
def test_the_map_keeps_the_boundaries_whose_score_rises_and_labels_every_band_it_keeps(line_and_boundaries):
    """残る境界の得点は折れ線の最も低い得点から上がり続け、落ちる境界の得点は直前に残した境界の得点（無ければ
    最も低い得点）を上回らない。体感ラベルは地図の段の数だけ配る。"""
    line, boundaries = line_and_boundaries
    definition = _axis(
        line,
        display_thresholds_override=boundaries,
        display_band_labels_override=[f"段{i}" for i in range(len(boundaries) + 1)],
    )

    kept = axis_display_for(definition).thresholds

    lowest = min(line.score_at(x) for x, _ in line.breakpoints)
    scores = [line.score_at(boundary) for boundary in kept]
    assert all(lower < upper for lower, upper in zip([lowest, *scores], scores))
    for dropped in thresholds_the_map_drops("axis_a", line, [], boundaries):
        below = [line.score_at(boundary) for boundary in kept if boundary < dropped]
        assert line.score_at(dropped) <= max([lowest, *below])
    assert kept == [b for b in boundaries if b not in thresholds_the_map_drops("axis_a", line, [], boundaries)]
    assert len(map_band_labels(definition) or []) == len(kept) + 1
