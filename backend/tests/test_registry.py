"""`domain/registry.py`——地図が軸をどう塗るかの宣言の型（`TileInputSpec`・`AxisDisplaySpec`）。

入口は2つの型の組み立て。読む側（画面の式）は形を1つだけ選んで塗るため、食い違う宣言は組み立ての時点で断る。

ここで見ないもの:
- 軸の定義から宣言を組み立てること → `test_axis_display.py`
- 一次属性の宣言（`PrimaryAttributeSpec`等）は検証を持たない型だけなので見ない
"""

import pytest
from pydantic import ValidationError

from app.domain.registry import AxisDisplaySpec, TileInputSpec


def test_a_tile_input_with_two_forms_is_refused():
    """形を2つ載せると、画面の式が片方を選び、選ばれなかった指定が黙って消える。"""
    with pytest.raises(ValidationError, match="more than one form"):
        TileInputSpec(property="p", categories={"a": 1.0}, breakpoints=[(0.0, 0.0), (1.0, 100.0)])


@pytest.mark.parametrize("values", [{"true_value": 1.0}, {"false_value": 1.0}])
def test_true_and_false_values_without_the_boolean_form_are_refused(values):
    with pytest.raises(ValidationError, match="without boolean=True"):
        TileInputSpec(property="p", **values)


def test_a_weight_on_the_boolean_form_is_refused_because_the_form_ignores_it():
    with pytest.raises(ValidationError, match="weight the boolean form ignores"):
        TileInputSpec(property="p", boolean=True, true_value=10.0, weight=2.0)


@pytest.mark.parametrize("form", [{"weight": 2.0}, {"boolean": True, "true_value": 10.0, "false_value": 2.0}])
def test_each_form_alone_is_accepted_and_reads_back_from_what_it_writes(form):
    """配った値は、書き出した形（使わない形の欄は空の値）から同じ宣言へ読み直せる。"""
    spec = TileInputSpec(property="p", **form)

    assert TileInputSpec.model_validate(spec.model_dump()) == spec


def test_categories_come_out_in_the_same_order_whatever_order_they_were_given_in():
    """DB・API・コードのどこから組み立てても、配る値（と生成物の差分）が同じになる。"""
    forward = TileInputSpec(property="p", categories={"a": 1.0, "b": 2.0, "c": 3.0})
    backward = TileInputSpec(property="p", categories={"c": 3.0, "a": 1.0, "b": 2.0})

    assert forward.model_dump_json() == backward.model_dump_json()


def test_a_ramp_display_with_nothing_to_read_from_the_tile_is_refused():
    with pytest.raises(ValidationError, match="nothing to read"):
        AxisDisplaySpec(kind="ramp", thresholds=[1.0])


@pytest.mark.parametrize(
    "payload",
    [{"tile_inputs": [TileInputSpec(property="p")]}, {"thresholds": [1.0]}],
)
def test_a_display_that_is_not_drawn_refuses_a_ramp_payload(payload):
    """`kind`だけを見てレイヤーを作るため、中身との食い違いは「地図に出ているのに塗られない」に化ける。"""
    with pytest.raises(ValidationError, match="kind=none"):
        AxisDisplaySpec(kind="none", **payload)


def test_band_boundaries_that_do_not_rise_are_refused():
    """昇順でない境界は画面のstep式が読めず、境界が1つ先の帯へ吸われる。同じ値も昇順でない。"""
    with pytest.raises(ValidationError, match="not ascending"):
        AxisDisplaySpec(kind="ramp", tile_inputs=[TileInputSpec(property="p")], thresholds=[1.0, 1.0])


def test_displays_that_agree_with_their_kind_are_accepted():
    ramp = AxisDisplaySpec(kind="ramp", tile_inputs=[TileInputSpec(property="p")], thresholds=[1.0, 2.0])
    none = AxisDisplaySpec(kind="none")

    assert ramp.thresholds == [1.0, 2.0]
    assert none.tile_inputs == [] and none.thresholds == []
