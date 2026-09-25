"""一次属性の行に塗る色を、軸の宣言（パレット・色相の起点・行数）から作る。

読み方の決まりは`docs/modules/frontend/static-map-layers.md`「地図全体で共有する配色の
読み方」。ここはその決まりを実装する1箇所で、**色の表を持たない**。

色はCIELCh（明度・彩度・色相）で作る。明度をそろえると、どの色相も基礎地図の背景に対して
同じだけ浮く（HSLの明度は色相ごとに見た目の明るさが違い、黄緑だけが背景へ沈む）。
"""

import math

from app.domain.map_display import ROAD_LINE_WIDTH_PX, ROAD_ORDERED_MAX_WIDTH_PX
from app.domain.registry import PrimaryAttributeSpec

#: 明度の上限。**基礎地図の背景（`SEMANTIC_COLORS["basemap_ground"]`）に対してコントラスト比3:1を割らない明るさ**
#: ——これより明るい分類色は「薄い＝対象外」の表現と見分けられない。
_MAX_LIGHTNESS = 58.0

#: 順序のある分類（幹線→細街路）。明度で順序を示し、色相も並びに沿って動かす（明度だけの濃淡は、上限の明度の下では
#: 隣どうしが近く、どれも暗い灰に見える）。色相は評価の配色（緑〜赤）を避けて紫→水色に限る——観測された事実の
#: 分類を良し悪しの色で読ませない。暗い端は黒と見分けられる所で止める。
_ORDERED_HUE_RANGE_DEG = (305.0, 205.0)
_ORDERED_LIGHTNESS_RANGE = (26.0, 56.0)
#: 目標の彩度。暗い側の色相によってはsRGBに収まらないので、収まるところまで下げる（`_fit_chroma`）。
_ORDERED_CHROMA = 45.0

#: 順序を持たない列挙。明度と彩度は1つに固定し、**軸の行へ色相環を等分して配る**——連番の
#: 色相を当てると、同じ軸の行どうしが最も見分けにくい隣の色相になる。起点は軸が
#: `hue_slot`（12分割の枠）で宣言する。この明度・彩度はどの色相でもsRGBに収まる。
NOMINAL_HUE_SLOTS = 12
_NOMINAL_START_HUE_DEG = 255.0
_NOMINAL_LIGHTNESS = 52.0
_NOMINAL_CHROMA = 28.0


def _lch_hex(lightness: float, chroma: float, hue_deg: float) -> str:
    """CIELCh（D65）→ sRGBの16進。色域を外れる組み合わせは黙って丸めずに止める。"""
    a = chroma * math.cos(math.radians(hue_deg))
    b = chroma * math.sin(math.radians(hue_deg))
    fy = (lightness + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200

    def f_inv(t: float) -> float:
        return t**3 if t**3 > 216 / 24389 else (116 * t - 16) / (24389 / 27)

    x, y, z = f_inv(fx) * 0.95047, f_inv(fy), f_inv(fz) * 1.08883
    linear = (
        3.2406 * x - 1.5372 * y - 0.4986 * z,
        -0.9689 * x + 1.8758 * y + 0.0415 * z,
        0.0557 * x - 0.2040 * y + 1.0570 * z,
    )
    channels = [12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055 for c in linear]
    if any(not -0.001 <= c <= 1.001 for c in channels):
        raise ValueError(f"sRGBの色域外: L*={lightness} C*={chroma} h={hue_deg % 360:.0f}")
    return "#" + "".join(f"{round(min(1.0, max(0.0, c)) * 255):02x}" for c in channels)


def _fit_chroma(lightness: float, chroma: float, hue_deg: float) -> str:
    """指定の明度・色相で、sRGBに収まる最も高い彩度（整数刻み）の色。"""
    for candidate in range(int(chroma), -1, -1):
        try:
            return _lch_hex(lightness, float(candidate), hue_deg)
        except ValueError:
            continue
    raise ValueError(f"彩度0でも色域外: L*={lightness} h={hue_deg % 360:.0f}")


def _ordered_positions(count: int) -> list[float]:
    """順序のある分類の各行の、並びの中の位置（先頭0〜末尾1）。色と太さが同じ位置から導かれるので、2つは同じ順序を示す。"""
    if count <= 0:
        return []
    return [0.5] if count == 1 else [i / (count - 1) for i in range(count)]


def ordered_colors(count: int) -> list[str]:
    """順序のある分類の色。並びの位置が意味を持つので、行数ぶんを一度に作る。"""
    (l_low, l_high), (h_start, h_end) = _ORDERED_LIGHTNESS_RANGE, _ORDERED_HUE_RANGE_DEG
    return [
        _fit_chroma(l_low + (l_high - l_low) * p, _ORDERED_CHROMA, h_start + (h_end - h_start) * p)
        for p in _ordered_positions(count)
    ]


def ordered_line_widths(count: int) -> list[float]:
    """順序のある分類を線で描くときの太さ（px）。先頭ほど太く、末尾は他の線と同じ太さ。"""
    return [
        round(ROAD_ORDERED_MAX_WIDTH_PX + (ROAD_LINE_WIDTH_PX - ROAD_ORDERED_MAX_WIDTH_PX) * p, 2)
        for p in _ordered_positions(count)
    ]


def nominal_colors(hue_slot: int, count: int) -> list[str]:
    """順序を持たない列挙の1軸ぶん。起点から色相環を行数で等分する。**同じ起点・同じ行数なら
    常に同じ色**（行を足すと、その軸の色は配り直される）。"""
    if not 0 <= hue_slot < NOMINAL_HUE_SLOTS:
        raise ValueError(f"色相の起点は0〜{NOMINAL_HUE_SLOTS - 1}: {hue_slot}")
    start = _NOMINAL_START_HUE_DEG + (360.0 / NOMINAL_HUE_SLOTS) * hue_slot
    return [_lch_hex(_NOMINAL_LIGHTNESS, _NOMINAL_CHROMA, start + 360.0 * i / count) for i in range(count)]


#: 役割ごとの色。名前は「どこで使うか」ではなく「何を意味するか」で付ける——使い場所で
#: 名前を付けると、同じ意味の色が使い場所の数だけ増える。
SEMANTIC_COLORS: dict[str, str] = {
    # 評価（2次）。良い側から悪い側への順序を持つ唯一の配色。中ほどと最も悪い側に中継点を置き、色相とともに明度も
    # 動かす——良い・悪いの2色を色相だけで補間すると、良い側の2段がどちらも緑に見える。
    "evaluation_good": "#16a34a",
    "evaluation_mid": "#eab308",
    "evaluation_bad": "#dc2626",
    "evaluation_extreme": "#7f1d1d",
    # 符号を持つ材料（勾配）の下り側。0を境に別方向へ伸ばし、上り側は評価の配色をそのまま使う。
    "signed_descent": "#0284c7",
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
    # 基礎地図（OpenFreeMap liberty）の背景色。配信元のスタイルが持つ値の写しで、分類色の
    # 明度の上限（`_MAX_LIGHTNESS`）はこれを基準にする——分類色は地図の上では常にこの地に載る。
    "basemap_ground": "#f8f4f0",
    # 大きさだけで意味を示す行（事故の重大度）の見本。地図の点の色はこの行では決まらない
    # ことを、どの分類色とも違う灰で示す。
    "legend_size_only": "#6b7280",
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
    """行の色と太さを解決した表示定義。**どちらも宣言に無い**ので、配る直前にここで決める。

    色を持つのは`palette`を宣言した軸（先頭の軸）の行だけで、他の軸の行は`color`を持たない
    ——地図が塗らない色を配ると、凡例がそれを色見本として出す。太さ（`line_width_px`）を持つのは、線で描く
    属性の順序のある分類の行だけ——太さは色と同じ順序を重ねて示す手がかりで、順序を持たない分類に付けると
    太さが意味の無い差を示す。"""
    axes = []
    for axis in attr.display_axes:
        count = len(axis.categories)
        widths: list[float | None] = [None] * count
        if axis.palette == "ordered":
            colors: list[str | None] = list(ordered_colors(count))
            if attr.geometry == "line":
                widths = list(ordered_line_widths(count))
        elif axis.palette == "nominal":
            colors = list(nominal_colors(axis.hue_slot or 0, count))
        else:
            colors = [None] * count
        axes.append(
            {
                **axis.model_dump(exclude={"categories", "palette", "hue_slot"}),
                "categories": [
                    {
                        **c.model_dump(),
                        **({} if color is None else {"color": color}),
                        **({} if width is None else {"line_width_px": width}),
                    }
                    for c, color, width in zip(axis.categories, colors, widths, strict=True)
                ],
            }
        )
    return axes
