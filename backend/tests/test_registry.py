"""`domain/registry.py`——一次属性と二次軸の宣言を受け付ける登録口。

何を登録するかは`test_registry_defaults.py`が持つ。ここで見るのは**何を拒むか**。
"""

import pytest

from app.domain.registry import (
    AxisInputConflictError,
    AxisSpec,
    PrimaryAttributeSpec,
    TileInputSpec,
    all_axes,
    all_primary_attributes,
    register_axis,
    register_primary_attribute,
    reset_registry_for_testing,
)


@pytest.fixture(autouse=True)
def _empty_registry():
    reset_registry_for_testing()
    yield
    reset_registry_for_testing()


def _attribute(attr_id: str) -> PrimaryAttributeSpec:
    return PrimaryAttributeSpec(attr_id=attr_id, label=f"属性[{attr_id}]")


class TestRegisterPrimaryAttribute:
    def test_a_registered_attribute_is_listed(self):
        register_primary_attribute(_attribute("a"))

        assert [spec.attr_id for spec in all_primary_attributes()] == ["a"]

    def test_registering_the_same_id_twice_is_rejected(self):
        """後勝ちで上書きすると、先に登録した側のラベルが黙って消える。"""
        register_primary_attribute(_attribute("a"))

        with pytest.raises(ValueError, match="a"):
            register_primary_attribute(_attribute("a"))


class TestRegisterAxis:

    def test_an_axis_with_registered_inputs_is_accepted(self):
        register_primary_attribute(_attribute("a"))

        register_axis(AxisSpec(axis_id="axis", inputs=["a"]))

        assert [spec.axis_id for spec in all_axes()] == ["axis"]

    def test_an_axis_with_no_inputs_is_accepted(self):
        register_axis(AxisSpec(axis_id="axis", inputs=[]))

        assert len(all_axes()) == 1

    def test_an_unregistered_input_is_rejected(self):
        """綴り違いをそのまま通すと、その属性の名前を引けない軸が登録される。"""
        with pytest.raises(ValueError, match="no_such_attribute"):
            register_axis(AxisSpec(axis_id="axis", inputs=["no_such_attribute"]))

    def test_registering_the_same_axis_twice_is_rejected(self):
        register_primary_attribute(_attribute("a"))
        register_axis(AxisSpec(axis_id="axis", inputs=["a"]))

        with pytest.raises(ValueError, match="axis"):
            register_axis(AxisSpec(axis_id="axis", inputs=["a"]))

    def test_two_axes_sharing_an_input_are_rejected(self):
        """同じ一次属性が2つの軸へ入ると、その属性が難易度へ二重に効く。"""
        register_primary_attribute(_attribute("a"))
        register_axis(AxisSpec(axis_id="first", inputs=["a"]))

        with pytest.raises(AxisInputConflictError):
            register_axis(AxisSpec(axis_id="second", inputs=["a"]))

    def test_the_conflict_names_both_axes_and_the_overlap(self):
        register_primary_attribute(_attribute("a"))
        register_primary_attribute(_attribute("b"))
        register_axis(AxisSpec(axis_id="first", inputs=["a", "b"]))

        with pytest.raises(AxisInputConflictError) as caught:
            register_axis(AxisSpec(axis_id="second", inputs=["b"]))

        message = str(caught.value)
        assert "first" in message and "second" in message and "b" in message

    def test_a_rejected_axis_is_not_partially_registered(self):
        register_primary_attribute(_attribute("a"))
        register_axis(AxisSpec(axis_id="first", inputs=["a"]))

        with pytest.raises(AxisInputConflictError):
            register_axis(AxisSpec(axis_id="second", inputs=["a"]))

        assert [spec.axis_id for spec in all_axes()] == ["first"]

    def test_disjoint_inputs_are_accepted(self):
        register_primary_attribute(_attribute("a"))
        register_primary_attribute(_attribute("b"))

        register_axis(AxisSpec(axis_id="first", inputs=["a"]))
        register_axis(AxisSpec(axis_id="second", inputs=["b"]))

        assert len(all_axes()) == 2


class TestTileInputSpec:
    def test_a_category_table_given_as_none_stays_absent(self):
        """空辞書へ倒すと、「分類ではない材料」と「分類だが値が無い材料」を読む側が
        区別できない。
        """
        assert TileInputSpec(property="p", categories=None).categories is None

    def test_the_category_table_is_stored_in_a_fixed_order(self):
        """順序が違うだけで生成物の差分が出ると、意味の無い再デプロイが要る。"""
        spec = TileInputSpec(property="p", categories={"c": 3.0, "a": 1.0, "b": 2.0})

        assert list(spec.categories) == ["a", "b", "c"]

