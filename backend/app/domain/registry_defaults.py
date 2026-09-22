"""既存の一次属性・二次軸をレジストリ（domain/registry.py）へ登録する既定セット。

`register_defaults()`はビルド時（`scripts/export_openapi.py`が`axis-catalog.json`等を
書き出す）にだけ呼ばれ、FastAPIアプリ本体は起動時に呼ばない——コスト関数の評価経路は
このレジストリを参照せず、実行時の軸カタログは`GET /api/axis-catalog`が配る。
そのため軸スタジオでの編集は、`axis-catalog.json`（frontendの読込中/エラー時
フォールバック専用）へは再デプロイまで反映されない。

モジュールimport時には自動実行しない。グローバルなレジストリ状態への副作用をimportの
タイミングに依存させると、テストの実行順序でレジストリが空/一部登録済みのどちらにも
なりうるため。
"""

from app.domain.axis_definitions import AXIS_DEFINITIONS, primary_attribute_ids_for
from app.domain.axis_display import axis_display_for
from app.domain.material_catalog import MATERIAL_CATALOG, PRIMARY_ATTRIBUTES
from app.domain.registry import (
    AxisSpec,
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
    # 材料が指す一次属性が宣言に無ければここで落とす（軸の公開時ではなく登録時に出す）。
    missing = sorted(
        {m.primary_attribute_id for m in MATERIAL_CATALOG.values() if m.primary_attribute_id}
        - {spec.attr_id for spec in PRIMARY_ATTRIBUTES}
    )
    if missing:
        raise ValueError(f"材料が指す一次属性がPRIMARY_ATTRIBUTESにありません: {missing}")
    for spec in PRIMARY_ATTRIBUTES:
        register_primary_attribute(spec)


def _register_axes() -> None:
    """公開済みの評価軸すべてを、AXIS_DEFINITIONSを走査してレジストリへ登録する。

    `inputs`・`display`は`GET /api/axis-catalog`（実行時API）が同じ軸に対して呼ぶのと
    同一の純粋関数から導出するため、ビルド時生成物と実行時APIとで計算が分岐しない。
    """
    for axis_id, definition in AXIS_DEFINITIONS.items():
        if not definition.is_published:
            continue
        register_axis(
            AxisSpec(
                axis_id=axis_id,
                inputs=primary_attribute_ids_for(definition),
                display=axis_display_for(definition),
            )
        )
