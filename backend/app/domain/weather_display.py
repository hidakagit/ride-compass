"""気象の値を色へ写す段。配信元（気象庁）の配色に合わせるもので、画面の好みではない。

危険度・雷・竜巻は気象庁がカラーコードを公開しておらず、タイル画像から読んだ**近似値**。
凡例と地図が違って見えたら、まずここを実物と突き合わせる。降水と風速は自前のグリッドだが、
利用者は気象庁の地図と並べて見るため同じ向き（弱い＝寒色、強い＝暖色）へ揃える。
"""

from typing import NamedTuple


class ValueColorStop(NamedTuple):
    """この値以上の範囲を塗る色。`name`は段そのものが持つ——別の配列へ分けると、段を足した
    ときに名前を足し忘れても型が通り、凡例に空が出る。"""

    value: float
    color: str
    name: str


def ascending_stops(*stops: ValueColorStop) -> tuple[ValueColorStop, ...]:
    """段の並び。**値の昇順でなければ読み込んだ時点で落とす**——画面は段を帯の下限として
    この順のまま塗り分けの式と凡例へ組み立てるため、順が崩れると地図のレイヤーが黙って
    描かれなくなる。"""
    values = [stop.value for stop in stops]
    if any(later <= earlier for earlier, later in zip(values, values[1:], strict=False)):
        raise ValueError(f"色の段は値の昇順で並べる: {values}")
    return stops


class LevelColor(NamedTuple):
    """段階そのものが鍵を持つもの（危険度・活動度）。"""

    key: str
    label: str
    color: str


#: 降水の強さ（mm/h）。背景と同じ色にすると「降っていない」と見分けが付かないため、
#: いちばん弱い段も色を持つ。20mm/h以上の切れ目と名前は気象庁「雨の強さと降り方」の分類、
#: それ未満は公式の区分が無いため体感の言い方（ポツポツ・パラパラ等）で分ける。
PRECIPITATION_COLOR_STOPS: tuple[ValueColorStop, ...] = ascending_stops(
    ValueColorStop(0, "#b8e6fd", "ごく弱い雨"),
    ValueColorStop(0.4, "#93dafc", "ポツポツ"),
    ValueColorStop(2, "#68ccfb", "パラパラ"),
    ValueColorStop(4, "#38bdf8", "ザーッ"),
    ValueColorStop(10, "#3b82f6", "ザーザー"),
    ValueColorStop(20, "#eab308", "強い雨"),
    ValueColorStop(30, "#f97316", "激しい雨"),
    ValueColorStop(50, "#dc2626", "非常に激しい雨"),
    ValueColorStop(80, "#9333ea", "猛烈な雨"),
)

#: 風速（m/s）。段の切れ目はビューフォート風力階級の上限で、名前は自転車で走るときの
#: 感じ方へ寄せてある。走行困難域（Bf7以上）は粒度を粗くする。
WIND_SPEED_COLOR_STOPS: tuple[ValueColorStop, ...] = ascending_stops(
    ValueColorStop(0, "#7dd3fc", "微風"),
    ValueColorStop(1.5, "#38bdf8", "そよ風"),
    ValueColorStop(3.3, "#22d3ee", "心地よい風"),
    ValueColorStop(5.4, "#34d399", "やや強い風"),
    ValueColorStop(7.9, "#a3e635", "強い風・向かい風がこたえ始める"),
    ValueColorStop(10.7, "#facc15", "かなり強い風"),
    ValueColorStop(13.8, "#f97316", "ロードバイクでの走行が難しい強風"),
    ValueColorStop(17.1, "#dc2626", "暴風"),
    ValueColorStop(24.4, "#7f1d1d", "猛烈な暴風"),
)

#: 危険度分布。白→黄→赤→紫→黒と上がる。
#: 線状降水帯予測マップの塗り色。**配信元タイルが実際に塗っている色そのもの**で、
#: 画面の好みではない。凡例をこれ以外から取ると、地図の塗りと凡例の色が黙ってずれる
#: （危険度の段の色がたまたま近いだけで、別の配色として動く）。
LINEAR_RAINBAND_COLOR = "#ff2800"

RISK_LEVEL_COLORS: tuple[LevelColor, ...] = (
    LevelColor("level0", "平常（危険度なし）", "#ffffff"),
    LevelColor("level1", "注意（黄）", "#f2e700"),
    LevelColor("level2", "警戒（赤）", "#ff2800"),
    LevelColor("level3", "危険（紫）", "#aa00aa"),
    LevelColor("level4", "災害切迫（黒）", "#0c000c"),
)

#: 雷の活動度。弱い＝黄→強い＝紫というナウキャスト系の配色慣習に沿う。気象庁はタイルの配色の
#: カラーコードを公開していないため、雷・竜巻の色は近似値で、実際のタイル画像の色とは厳密には一致しない。
THUNDER_ACTIVITY_LEVELS: tuple[LevelColor, ...] = (
    LevelColor("level1", "活動度1: 雷雲発達の可能性（1時間以内に発雷のおそれ）", "#fde047"),
    LevelColor("level2", "活動度2: 雷雲発生、落雷の可能性", "#fb923c"),
    LevelColor("level3", "活動度3: 落雷が発生中", "#ef4444"),
    LevelColor("level4", "活動度4: 激しい雷（雹に注意）", "#9333ea"),
)

#: 竜巻発生確度。数字は切迫度ではなく「可能性の程度」の違い（気象庁の注記どおり）。
#: 雷と区別できる寒色系にする。
TORNADO_POTENTIAL_LEVELS: tuple[LevelColor, ...] = (
    LevelColor("potential1", "発生確度1: 広く注意（見逃しを減らす、的中率1〜7%）", "#38bdf8"),
    LevelColor("potential2", "発生確度2: 重点警戒（気象庁「竜巻注意」相当、的中率7〜14%）", "#1d4ed8"),
)


class WeatherCategory(NamedTuple):
    """天気コード（WMO）の分類。画面はこの分類ごとにアイコンと名前を出す。"""

    key: str
    label: str
    codes: tuple[int, ...]


#: 天気コードの分類。どれにも当たらないコードは「くもり」として出す（`WEATHER_CATEGORY_FALLBACK`）。
WEATHER_CATEGORIES: tuple[WeatherCategory, ...] = (
    WeatherCategory("clear", "晴れ", (0, 1)),
    WeatherCategory("cloudy", "くもり", (2, 3)),
    WeatherCategory("fog", "霧", (45, 48)),
    WeatherCategory("rain", "雨", (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82)),
    WeatherCategory("snow", "雪", (71, 73, 75, 77, 85, 86)),
    WeatherCategory("thunderstorm", "雷雨", (95, 96, 99)),
)
WEATHER_CATEGORY_FALLBACK = "cloudy"
