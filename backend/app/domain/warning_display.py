"""警戒度バッジ（画面のヘッダー）の、出所ごとの段階の表示名と色。

段階の語彙（`WarningBadgeLevel`）は出所をまたいで共通だが、呼び名は出所の正式な語彙に合わせる——気象庁の
「警報」と暑さ指数の「警戒」は別の意味の言葉で、同じ語にすると誤解を招く。暑さ指数と氾濫の呼び名は、それぞれの
段階を決める宣言（`domain/wbgt.py`・`domain/flood_forecast.py`）から読む。

色は白文字で読める濃さにし、テーマで変えない（警戒度は常に強調して出す）。気象庁と河川の氾濫は公式の警報として
同じ配色を持ち、特別警報級は雷ナウキャストの最上段と同じ「最も警戒すべき段階」の色を使う。暑さ指数は気象庁の
警報と無関係の別の基準のため、一目で系統が違うと分かる別の配色にする。
"""

from typing import Literal, NamedTuple, get_args

from app.domain.flood_forecast import FLOOD_LEVEL_LABELS
from app.domain.warning_levels import WarningBadgeLevel
from app.domain.wbgt import WBGT_LEVEL_LABELS
from app.domain.weather_display import THUNDER_ACTIVITY_LEVELS

WarningBadgeSource = Literal["jma", "wbgt", "flood"]


class BadgeLevelDisplay(NamedTuple):
    level: WarningBadgeLevel
    label: str
    color: str


_OFFICIAL_COLORS: dict[WarningBadgeLevel, str] = {
    "advisory": "#f59e0b",
    "warning": "#dc2626",
    "severe_warning": "#be123c",
    "emergency_warning": THUNDER_ACTIVITY_LEVELS[-1].color,
}
_WBGT_COLORS: dict[WarningBadgeLevel, str] = {
    "advisory": "#4d7c0f",
    "warning": "#ca8a04",
    "severe_warning": "#ea580c",
    "emergency_warning": "#b91c1c",
}
_JMA_LABELS: dict[WarningBadgeLevel, str] = {
    "advisory": "注意報",
    "warning": "警報",
    "severe_warning": "危険警報",
    "emergency_warning": "特別警報",
}

_LEVELS: tuple[WarningBadgeLevel, ...] = get_args(WarningBadgeLevel)


def _display(
    labels: dict[WarningBadgeLevel, str], colors: dict[WarningBadgeLevel, str]
) -> tuple[BadgeLevelDisplay, ...]:
    return tuple(BadgeLevelDisplay(level, labels[level], colors[level]) for level in _LEVELS)


#: 出所 → 段階の表示（軽い→重いの順）。
WARNING_BADGE_DISPLAY: dict[WarningBadgeSource, tuple[BadgeLevelDisplay, ...]] = {
    "jma": _display(_JMA_LABELS, _OFFICIAL_COLORS),
    "flood": _display(FLOOD_LEVEL_LABELS, _OFFICIAL_COLORS),
    "wbgt": _display(WBGT_LEVEL_LABELS, _WBGT_COLORS),
}
