"""気象庁タイルの配信元のパスを読む——タイルとして読み戻す・404が確定した事実か。

パスの形は`domain/jma_tile_specs.py: jma_url_template`が持ち（画面も同じテンプレートを埋める）、ここはそのテンプレートに
パスを当てて読むだけで、形を別に持たない。
"""

import re

from app.domain import jma_tile_specs
from app.domain.jma_tile_specs import TEMPLATE_PLACEHOLDER, JmaFrame, JmaTile, jma_url_template

#: 読み戻すとき数字だけに当てる項目（タイル座標）。他の項目はパスの1区切りに当てる。
_NUMERIC_FIELDS = frozenset({"z", "x", "y"})
_NUMBER = r"\d+"
_SEGMENT = r"[^/?]+"


def _template_pattern(template: str) -> re.Pattern[str]:
    parts = TEMPLATE_PLACEHOLDER.split(template)
    pattern = "".join(
        re.escape(part) if index % 2 == 0 else f"(?P<{part}>{_NUMBER if part in _NUMERIC_FIELDS else _SEGMENT})"
        for index, part in enumerate(parts)
    )
    return re.compile(f"^{pattern}$")


def read_jma_tile_path(path: str) -> JmaTile | None:
    """配信元のパスを、宣言のある要素のタイルとして読む。タイルでないパス（時刻一覧・地物）・宣言の無い要素はNone。"""
    for element_id, element in jma_tile_specs.JMA_ELEMENTS.items():
        if element.tile is None:
            continue
        match = _template_pattern(jma_url_template(element_id)).match(path)
        if match is not None:
            return JmaTile(
                element_id,
                JmaFrame(match["basetime"], match["member"], match["validtime"]),
                int(match["z"]),
                int(match["x"]),
                int(match["y"]),
            )
    return None


def is_final_absence(path: str) -> bool:
    """配信元がこのパスに404を返したとき、それが「描くものが無い」という確定した事実か。

    タイルと時刻一覧は確定する（疎な格子の穴）。タイルで配らない要素のコマの地物（GeoJSON）は確定しない
    ——配信元は時刻一覧に載せたコマの地物を配信するまで404を返し、配信した後は地物が無くても200で空の
    集まりを返すため、この404は「まだ配信されていない」である。"""
    return not any(
        _template_pattern(jma_url_template(element_id)).match(path)
        for element_id, element in jma_tile_specs.JMA_ELEMENTS.items()
        if element.tile is None
    )
