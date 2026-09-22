"""`domain/registry_defaults.py`——ビルド時生成物のためにレジストリを1回だけ埋める。

実行時の軸カタログは`GET /api/axis-catalog`が配る。ここが埋めるのは、frontendが読込中・
エラー時に使うビルド時の写しのためのレジストリ。

`inputs`・`display`の導出そのものは`test_axis_definitions.py`・`test_axis_display.py`が
持つ。ここで見るのは**何を登録し、何を登録しないか**。
"""

from contextlib import contextmanager

import pytest

from app.domain import registry_defaults
from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisDefinition, BreakpointLinearShape, MaterialTerm
from app.domain.registry import all_axes, all_primary_attributes, reset_registry_for_testing
from app.domain.registry_defaults import register_defaults

LINE = [(0.0, 0.0), (10.0, 100.0)]


@contextmanager
def _empty_registry():
    reset_registry_for_testing()
    try:
        yield
    finally:
        reset_registry_for_testing()


@contextmanager
def _vocabulary(labels: dict[str, str], without_material: dict[str, str], material_attributes: dict[str, str]):
    """一次属性の語彙と、材料がどの一次属性を指すかを差し替える。"""
    specs = {m: type("Spec", (), {"primary_attribute_id": attr})() for m, attr in material_attributes.items()}
    saved = (
        registry_defaults.PRIMARY_ATTRIBUTE_LABELS,
        registry_defaults.PRIMARY_ATTRIBUTES_WITHOUT_MATERIAL,
        registry_defaults.MATERIAL_CATALOG,
    )
    registry_defaults.PRIMARY_ATTRIBUTE_LABELS = labels
    registry_defaults.PRIMARY_ATTRIBUTES_WITHOUT_MATERIAL = without_material
    registry_defaults.MATERIAL_CATALOG = specs
    try:
        yield
    finally:
        (
            registry_defaults.PRIMARY_ATTRIBUTE_LABELS,
            registry_defaults.PRIMARY_ATTRIBUTES_WITHOUT_MATERIAL,
            registry_defaults.MATERIAL_CATALOG,
        ) = saved


@contextmanager
def _axes(definitions: dict[str, AxisDefinition]):
    original = dict(AXIS_DEFINITIONS)
    AXIS_DEFINITIONS.clear()
    AXIS_DEFINITIONS.update(definitions)
    try:
        yield
    finally:
        AXIS_DEFINITIONS.clear()
        AXIS_DEFINITIONS.update(original)


def _axis(axis_id: str, is_published: bool) -> AxisDefinition:
    return AxisDefinition(
        axis_id=axis_id,
        shape=BreakpointLinearShape(terms=[MaterialTerm(material="m_a")], breakpoints=LINE),
        default_weight=0.1,
        label=f"軸[{axis_id}]",
        is_published=is_published,
    )


class TestWhatGetsRegistered:
    def test_the_vocabulary_comes_from_both_declarations(self):
        """片方だけ登録すると、その属性を指す表示が名前を引けない。"""
        with _empty_registry(), _axes({}):
            with _vocabulary({"with": "材料あり"}, {"without": "材料なし"}, {"m_a": "with"}):
                register_defaults()

                assert {a.attr_id for a in all_primary_attributes()} == {"with", "without"}

    def test_only_published_axes_are_registered(self):
        """下書きの軸がビルド時の写しへ入ると、一般向けの画面に出る。"""
        with _empty_registry():
            with _vocabulary({"with": "材料あり"}, {}, {"m_a": "with"}):
                with _axes({"shown": _axis("shown", True), "draft": _axis("draft", False)}):
                    register_defaults()

                    assert {a.axis_id for a in all_axes()} == {"shown"}

    def test_a_material_pointing_at_an_unknown_attribute_is_rejected(self):
        """登録の時点で落とす。軸の公開まで持ち越すと、名前を引けない属性を指したまま
        公開できてしまう。
        """
        with _empty_registry(), _axes({}):
            with _vocabulary({"known": "既知"}, {}, {"m_a": "no_such_attribute"}):
                with pytest.raises(ValueError, match="no_such_attribute"):
                    register_defaults()

    def test_a_material_without_an_attribute_is_not_required_to_be_in_the_table(self):
        """Noneを語彙の欠落として扱うと、登録できなくなる。"""
        with _empty_registry(), _axes({}):
            with _vocabulary({"known": "既知"}, {}, {"m_a": None}):
                register_defaults()

                assert {a.attr_id for a in all_primary_attributes()} == {"known"}

    def test_calling_it_twice_is_rejected(self):
        """レジストリは大域の状態。二重に埋めると、どちらの内容か分からなくなる。"""
        with _empty_registry(), _axes({}):
            with _vocabulary({"with": "材料あり"}, {}, {"m_a": "with"}):
                register_defaults()

                with pytest.raises(ValueError):
                    register_defaults()


class TestAgainstTheRealDeclarations:
    def test_the_real_declarations_register_without_conflict(self):
        """差し替えずに実際の宣言で通す。`register_defaults`が弾くもの——材料が指す未登録の
        一次属性、2つの表への二重登録——は、**この呼び出しが成功すること**で確かめられる。
        個別の性質を並べ直しても、同じことの言い換えにしかならない。
        """
        reset_registry_for_testing()
        try:
            register_defaults()
        finally:
            reset_registry_for_testing()
