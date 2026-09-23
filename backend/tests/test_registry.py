"""`domain/registry.py`——一次属性の宣言を受け付ける登録口。

何を登録するかは`test_registry_defaults.py`が持つ。ここで見るのは**何を拒むか**。
"""

import pytest

from app.domain.registry import (
    PrimaryAttributeSpec,
    TileInputSpec,
    all_primary_attributes,
    register_primary_attribute,
    reset_registry_for_testing,
)


@pytest.fixture(autouse=True)
def _empty_registry():
    reset_registry_for_testing()
    yield
    reset_registry_for_testing()


def _attribute(attr_id: str) -> PrimaryAttributeSpec:
    return PrimaryAttributeSpec(attr_id=attr_id, label=f"属性[{attr_id}]", geometry="line")


class TestRegisterPrimaryAttribute:
    def test_a_registered_attribute_is_listed(self):
        register_primary_attribute(_attribute("a"))

        assert [spec.attr_id for spec in all_primary_attributes()] == ["a"]

    def test_registering_the_same_id_twice_is_rejected(self):
        """後勝ちで上書きすると、先に登録した側のラベルが黙って消える。"""
        register_primary_attribute(_attribute("a"))

        with pytest.raises(ValueError, match="a"):
            register_primary_attribute(_attribute("a"))


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

