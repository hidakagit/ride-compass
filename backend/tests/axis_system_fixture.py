"""テストが`AXIS_DEFINITIONS`を差し替えるための道具。軸そのものは配らない。

`AXIS_DEFINITIONS`はDBが唯一の正本で、テストの中では空から始まる。軸の集合を必要とする
テストは、見たい性質だけを持つ軸をそのファイルで組み立て、ここの道具で流し込む——共通の軸を
全テストへ配ると、その値に関心のないテストまでそれに依存する。
"""

from collections.abc import Mapping
from contextlib import contextmanager

from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisDefinition


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
