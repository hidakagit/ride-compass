"""テストが軸を組み立て、`AXIS_DEFINITIONS`を差し替えるための道具。軸そのものは配らない。

`AXIS_DEFINITIONS`はDBが唯一の正本で、テストの中では空から始まる。軸の集合を必要とする
テストは、見たい性質だけを持つ軸をそのファイルで組み立て、ここの道具で流し込む——共通の軸を
全テストへ配ると、その値に関心のないテストまでそれに依存する。
"""

from collections.abc import Mapping
from contextlib import contextmanager
from typing import Any

from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisDefinition, BreakpointLinearShape, MaterialTerm


def axis_definition(axis_id: str, *, material: str = "material_a", **fields: Any) -> AxisDefinition:
    """中身がテストの主題でない軸を1本作る。

    既定は型を満たすためだけの値（架空の材料1つを読む区分線形・重み0・下書き）で、本番の
    軸を模さない。見たい性質（材料・重み・公開・表示や配信の印）は呼び出し側が引数で書く。
    shapeそのものを見るテストは、この関数を使わずに自分で組み立てる。
    """
    return AxisDefinition(
        axis_id=axis_id,
        shape=BreakpointLinearShape(terms=[MaterialTerm(material=material)], breakpoints=[(0.0, 0.0), (1.0, 100.0)]),
        **{"default_weight": 0.0, "label": "軸", **fields},
    )


@contextmanager
def axis_definitions_snapshot():
    """`AXIS_DEFINITIONS`の今の中身を憶えておき、ブロック終了時に戻す。

    ブロック内で何を書き込むか（差し替えるか、そもそも書き込まないか）は呼び出し側の責務。
    """
    original = dict(AXIS_DEFINITIONS)
    try:
        yield original
    finally:
        AXIS_DEFINITIONS.clear()
        AXIS_DEFINITIONS.update(original)


@contextmanager
def replaced_axis_definitions(definitions: Mapping[str, AxisDefinition]):
    """ブロックの間だけ`AXIS_DEFINITIONS`を`definitions`だけにする。"""
    with axis_definitions_snapshot():
        AXIS_DEFINITIONS.clear()
        AXIS_DEFINITIONS.update(definitions)
        yield
