"""一次属性の行に塗る色を、パレットの枠から取る。

**色の表を持たない。** 行が宣言するのは「どの枠か」（順序のある分類なら並びの位置、
順序を持たない列挙なら枠の番号）だけで、色そのものはここが1箇所で決める。色を行ごとに
書けるようにすると、「中立色か評価配色か」という決まりがその場の判断で破れる。

枠の番号を行が持つのは、**軸をまたいで色が衝突しないため**。位置だけで決めると、
1行しか持たない軸どうし（トンネルと一方通行）が必ず同じ色になる。

評価配色（緑〜赤）はここに無い。順序のある分類は色相ではなく明度で表す——観測された事実の
分類へ良し悪しの順序を持ち込むと、地図の上で事実と評価が混ざる。
"""

import colorsys
from typing import Literal

DisplayPalette = Literal["ordered", "nominal"]

#: 順序のある分類（幹線→細街路）の色相と彩度。明度だけを動かして濃淡にする。
_ORDERED_HUE_DEG = 215.0
_ORDERED_SATURATION = 0.18
#: 端は避ける。暗くすると黒、明るくすると背景と区別できない。
_ORDERED_LIGHTNESS_RANGE = (0.28, 0.80)

#: 順序を持たない列挙の枠。色相を等分し、明度2段で倍に増やす——色相だけで分けると、
#: 枠が増えたとき隣同士が見分けられなくなる。
NOMINAL_HUE_SLOTS = 12
_NOMINAL_LIGHTNESS_STEPS = (0.40, 0.55, 0.70)
NOMINAL_SLOT_COUNT = NOMINAL_HUE_SLOTS * len(_NOMINAL_LIGHTNESS_STEPS)
_NOMINAL_START_HUE_DEG = 215.0
_NOMINAL_SATURATION = 0.32


def _hex(hue_deg: float, saturation: float, lightness: float) -> str:
    red, green, blue = colorsys.hls_to_rgb((hue_deg % 360.0) / 360.0, lightness, saturation)
    return "#{:02x}{:02x}{:02x}".format(round(red * 255), round(green * 255), round(blue * 255))


def ordered_colors(count: int) -> list[str]:
    """順序のある分類の濃淡。並びの位置が意味を持つので、行数ぶんを一度に作る。"""
    if count <= 0:
        return []
    low, high = _ORDERED_LIGHTNESS_RANGE
    if count == 1:
        return [_hex(_ORDERED_HUE_DEG, _ORDERED_SATURATION, (low + high) / 2)]
    step = (high - low) / (count - 1)
    return [_hex(_ORDERED_HUE_DEG, _ORDERED_SATURATION, low + step * i) for i in range(count)]


def nominal_color(slot: int) -> str:
    """順序を持たない列挙の枠1つぶん。**同じ番号は常に同じ色**。"""
    if not 0 <= slot < NOMINAL_SLOT_COUNT:
        raise ValueError(f"枠の番号は0〜{NOMINAL_SLOT_COUNT - 1}: {slot}")
    hue = _NOMINAL_START_HUE_DEG + (360.0 / NOMINAL_HUE_SLOTS) * (slot % NOMINAL_HUE_SLOTS)
    lightness = _NOMINAL_LIGHTNESS_STEPS[slot // NOMINAL_HUE_SLOTS]
    return _hex(hue, _NOMINAL_SATURATION, lightness)
