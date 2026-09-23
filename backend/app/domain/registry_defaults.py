"""既存の一次属性をレジストリ（domain/registry.py）へ登録する既定セット。

`register_defaults()`はビルド時（`scripts/export_openapi.py`が一次属性の語彙を
書き出す）にだけ呼ばれ、FastAPIアプリ本体は起動時に呼ばない——コスト関数の評価経路は
このレジストリを参照せず、実行時の軸カタログは`GET /api/axis-catalog`が配る。

モジュールimport時には自動実行しない。グローバルなレジストリ状態への副作用をimportの
タイミングに依存させると、テストの実行順序でレジストリが空/一部登録済みのどちらにも
なりうるため。
"""

from app.domain.material_catalog import MATERIAL_CATALOG, PRIMARY_ATTRIBUTES
from app.domain.registry import register_primary_attribute


def register_defaults() -> None:
    """一次属性の語彙を材料カタログから登録する。正本は`material_catalog.py`にある。
    プロセス内で1回だけ呼ぶこと（二重呼び出しは「既に登録済み」の`ValueError`になる）。"""
    # 材料が指す一次属性が宣言に無ければここで落とす（軸の公開時ではなく登録時に出す）。
    missing = sorted(
        {m.primary_attribute_id for m in MATERIAL_CATALOG.values() if m.primary_attribute_id}
        - {spec.attr_id for spec in PRIMARY_ATTRIBUTES}
    )
    if missing:
        raise ValueError(f"材料が指す一次属性がPRIMARY_ATTRIBUTESにありません: {missing}")
    for spec in PRIMARY_ATTRIBUTES:
        register_primary_attribute(spec)
