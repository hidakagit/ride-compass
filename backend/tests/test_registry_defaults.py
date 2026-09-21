"""`register_defaults()`（既存の一次属性・二次軸の既定登録）が、コード変更なしに実行でき、
排他検証を通ることを確認する。

個々の軸id・材料idを名指しせず、材料カタログ・軸定義から導いた母集団に対する不変条件だけを
置く（軸が1つ増減しても書き換えずに済み、増えた要素も自動で検査対象になる）。
`register_defaults()`は呼び出し時点の`AXIS_DEFINITIONS`をそのまま走査するため、本番相当の
軸定義が要る——`tests/conftest.py`のセッションスコープautouseフィクスチャが用意する。
"""

import pytest

from app.domain import registry
from app.domain.axis_definitions import AXIS_DEFINITIONS
from app.domain.material_catalog import (
    MATERIAL_CATALOG,
    PRIMARY_ATTRIBUTES_WITHOUT_MATERIAL,
    PRIMARY_ATTRIBUTE_LABELS,
)
from app.domain.registry_defaults import register_defaults


@pytest.fixture(autouse=True)
def _defaults_registered():
    registry.reset_registry_for_testing()
    register_defaults()
    yield
    registry.reset_registry_for_testing()


def test_primary_attributes_come_from_the_material_catalog():
    """語彙をここへ書き写さず、材料カタログから導かれることだけを見る。"""
    registered = {attr.attr_id for attr in registry.all_primary_attributes()}

    assert registered == set(PRIMARY_ATTRIBUTE_LABELS) | set(PRIMARY_ATTRIBUTES_WITHOUT_MATERIAL)


def test_every_primary_attribute_a_material_points_to_is_registered():
    pointed = {m.primary_attribute_id for m in MATERIAL_CATALOG.values() if m.primary_attribute_id}
    registered = {attr.attr_id for attr in registry.all_primary_attributes()}

    assert pointed <= registered


def test_attributes_without_material_are_declared_as_such():
    """材料を持たない一次属性は、その旨の表にだけ載っている。"""
    pointed = {m.primary_attribute_id for m in MATERIAL_CATALOG.values() if m.primary_attribute_id}

    for attr_id in PRIMARY_ATTRIBUTES_WITHOUT_MATERIAL:
        assert attr_id not in pointed, f"{attr_id}は材料が指しているので、材料由来の表へ移す"


def test_all_primary_attributes_have_non_empty_labels():
    """labelは地図チップ・サイドバー・研究タブが表示する名称の単一ソース。pydanticの
    required制約は空文字を通すため、ここで機械的に空でないことを確認する。"""
    for attr in registry.all_primary_attributes():
        assert attr.label.strip() != "", f"{attr.attr_id} has empty label"


def test_registry_axis_ids_match_axis_definitions():
    """表示カタログ用レジストリの登録軸集合が、評価ロジックが参照する公開軸と一致する
    （片方だけ更新しても気づかない死角をここで塞ぐ）。"""
    registry_axis_ids = {axis.axis_id for axis in registry.all_axes()}
    definition_axis_ids = {axis_id for axis_id, d in AXIS_DEFINITIONS.items() if d.is_published}

    assert definition_axis_ids == registry_axis_ids
    for axis_id, definition in AXIS_DEFINITIONS.items():
        assert definition.axis_id == axis_id


def test_registry_axis_display_labels_match_axis_definitions():
    """`AxisDisplaySpec.label`は軸定義のlabelを参照する（同じ文字列を2箇所で手書きすると
    片方だけ変えても気づかない）。"""
    for axis in registry.all_axes():
        assert axis.display is not None
        assert axis.display.label == AXIS_DEFINITIONS[axis.axis_id].label


def test_register_defaults_is_idempotent_guarded():
    """2回連続で呼ぶとValueErrorを送出する（二重登録によるレジストリ不整合を防ぐ）。"""
    with pytest.raises(ValueError, match="already registered"):
        register_defaults()


def test_register_defaults_does_not_crash_when_a_builtin_axis_is_removed(monkeypatch):
    """`_register_axes()`は`AXIS_DEFINITIONS`を走査するだけで特定のaxis_idを名指ししない。
    組み込み軸が軸スタジオで削除された状態でビルドしても、KeyErrorで落ちずにその軸が
    登録対象から外れるだけになる。"""
    removed = next(axis_id for axis_id, d in AXIS_DEFINITIONS.items() if d.is_published)
    expected = {axis_id for axis_id, d in AXIS_DEFINITIONS.items() if d.is_published} - {removed}
    registry.reset_registry_for_testing()
    monkeypatch.delitem(AXIS_DEFINITIONS, removed)

    register_defaults()

    assert {axis.axis_id for axis in registry.all_axes()} == expected
