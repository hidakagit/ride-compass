"""既存の一次属性・二次軸をレジストリ（domain/registry.py）へ登録する既定セット。

`register_defaults()`はビルド時（`scripts/export_openapi.py`が一次属性の語彙を
書き出す）にだけ呼ばれ、FastAPIアプリ本体は起動時に呼ばない——コスト関数の評価経路は
このレジストリを参照せず、実行時の軸カタログは`GET /api/axis-catalog`が配る。

モジュールimport時には自動実行しない。グローバルなレジストリ状態への副作用をimportの
タイミングに依存させると、テストの実行順序でレジストリが空/一部登録済みのどちらにも
なりうるため。
"""

from app.domain.axis_definitions import AXIS_DEFINITIONS, primary_attribute_ids_for
from app.domain.material_catalog import (
    MATERIAL_CATALOG,
    PRIMARY_ATTRIBUTES_WITHOUT_MATERIAL,
    PRIMARY_ATTRIBUTE_LABELS,
)
from app.domain.registry import (
    AxisSpec,
    PrimaryAttributeSpec,
    register_axis,
    register_primary_attribute,
)


def register_defaults() -> None:
    """既存の一次属性・二次軸をレジストリへ登録する。プロセス内で1回だけ呼ぶこと
    （二重呼び出しは「既に登録済み」の`ValueError`になる）。"""
    _register_primary_attributes()
    _register_axes()


def _register_primary_attributes() -> None:
    """一次属性の語彙を材料カタログから登録する。正本は`material_catalog.py`にある。"""
    # 材料が指す一次属性がラベル表に無ければここで落とす（軸の公開時ではなく登録時に出す）。
    missing = sorted(
        {m.primary_attribute_id for m in MATERIAL_CATALOG.values() if m.primary_attribute_id}
        - set(PRIMARY_ATTRIBUTE_LABELS)
    )
    if missing:
        raise ValueError(f"材料が指す一次属性がPRIMARY_ATTRIBUTE_LABELSにありません: {missing}")
    for attr_id, label in PRIMARY_ATTRIBUTE_LABELS.items():
        register_primary_attribute(PrimaryAttributeSpec(attr_id=attr_id, label=label))
    for attr_id, label in PRIMARY_ATTRIBUTES_WITHOUT_MATERIAL.items():
        register_primary_attribute(PrimaryAttributeSpec(attr_id=attr_id, label=label))


def _register_axes() -> None:
    """公開済みの評価軸すべてを、AXIS_DEFINITIONSを走査してレジストリへ登録する。

    登録した軸を読む先は無い——**この走査は「1つの一次属性が2つの公開軸へ入っていないか」
    の検査そのもの**で、重なっていれば`register_axis`が送出し、ビルドが止まる。
    """
    for axis_id, definition in AXIS_DEFINITIONS.items():
        if not definition.is_published:
            continue
        register_axis(AxisSpec(axis_id=axis_id, inputs=primary_attribute_ids_for(definition)))
