"""一次属性の行に塗る色を、パレットの枠から取る。

読み方の決まりは`docs/modules/frontend/static-map-layers.md`「地図全体で共有する配色の
読み方」。ここはその決まりを実装する1箇所で、**色の表を持たない**。
"""

import colorsys

from app.domain.registry import PrimaryAttributeSpec

#: 順序のある分類（幹線→細街路）の色相と彩度。明度だけを動かして濃淡にする。
_ORDERED_HUE_DEG = 215.0
_ORDERED_SATURATION = 0.18
#: 端は避ける。暗くすると黒、明るくすると背景と区別できない。
_ORDERED_LIGHTNESS_RANGE = (0.28, 0.80)

#: 順序を持たない列挙の枠。色相を等分し、明度でさらに分ける（色相だけだと枠が増えたとき
#: 隣同士を見分けられない）。
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


#: 役割ごとの色。名前は「どこで使うか」ではなく「何を意味するか」で付ける——使い場所で
#: 名前を付けると、同じ意味の色が使い場所の数だけ増える。
SEMANTIC_COLORS: dict[str, str] = {
    # 評価（2次）。良い側から悪い側への順序を持つ唯一の配色。
    "evaluation_good": "#16a34a",
    "evaluation_bad": "#dc2626",
    # 符号を持つ材料（勾配）。0を境に別方向へ伸ばすため、下り側と登り側の中継点を持つ。
    "signed_descent": "#0284c7",
    "signed_climb_mid": "#eab308",
    "signed_climb_extreme": "#7f1d1d",
    # **取得中と対象外は見分けられる明度差を保つ**（同じに見えると「壊れている」と読まれる）。
    "no_data": "#9ca3af",
    "loading": "#d1d5db",
    "hidden": "rgba(0,0,0,0)",
    # 利用者が作った線。基礎地図の主要道路（暖色系）に溶け込まない寒色を参考線に、
    # 乗り換えと合成には暖色を使う。
    "route_candidate": "#64748b",
    "route_selected_halo": "#1e3a8a",
    "route_casing": "rgba(15, 23, 42, 0.8)",
    "route_splice": "#c2612b",
    "route_arrow": "#ffffff",
    "route_arrow_halo": "#111827",
    # 記号の縁取りと、雷。
    "mark_halo": "rgba(31, 41, 55, 0.85)",
    "mark_stroke": "#ffffff",
    "lightning": "#facc15",
    # 押せるだけで見えない線。不透明度0で塗るが、値を省くとMapLibreが既定色で描く。
    "hit": "#000000",
    # 詳細を見ている1本の強調。どの分類の色とも重ならない色にする。
    "inspected": "#f59e0b",
    # 「値が無い」と「この軸の対象外」を見分けるため、no_dataより青寄りにする。
    "neutral": "#94a3b8",
    # 地点のピン。出発地は白い台の上に十字（地図の上での慣習）。
    "pin_origin_background": "#ffffff",
    "pin_origin": "#e11d48",
    "pin_origin_unresolved": "#9ca3af",
    "pin_waypoint": "#2563eb",
    "pin_destination": "#059669",
}

#: 比較スロットの色。並べて見分けられることだけが要件で、順序の意味は持たない。
COMPARISON_SLOT_COLORS: tuple[str, ...] = ("#16a34a", "#ea580c", "#9333ea")

#: 評価（2次）の段を作る中継点。段数が変わっても同じ系統のまま増減する。
EVALUATION_RAMP_ANCHORS: tuple[tuple[float, str], ...] = (
    (0.0, "#4caf50"),
    (1 / 3, "#ffb300"),
    (2 / 3, "#fb8c00"),
    (1.0, "#e53935"),
)


def resolved_display_axes(attr: PrimaryAttributeSpec) -> list[dict]:
    """行の色を解決した表示定義。**色は宣言に無い**ので、配る直前にここで決める。"""
    axes = []
    for axis in attr.display_axes:
        colors = (
            ordered_colors(len(axis.categories))
            if axis.palette == "ordered"
            else [nominal_color(c.color_slot or 0) for c in axis.categories]
        )
        axes.append(
            {
                **axis.model_dump(exclude={"categories", "palette"}),
                "categories": [
                    {**c.model_dump(exclude={"color_slot"}), "color": color}
                    for c, color in zip(axis.categories, colors, strict=True)
                ],
            }
        )
    return axes
