"""JMA指定河川洪水予報の警戒レベル判定。

コード対応表は気象庁「指定河川洪水予報」電文フォーマット解説資料の表２
（令和8年度出水期以降の対応表）を典拠とする。

JMA警報（jma_warning.py）と異なり、このAPIはstatus文字列（"発表"/"継続"/"解除"）
ではなく、item.code自体が「発表」「継続」「解除」「警報解除（下位レベルへの引き下げ）」を
区別する（例: code"20"=新規発表、"21"=継続、"22"=上位警報解除で当レベルへ引き下げ）。
完全解除（現在アクティブな発表なし）を表すコード"10"は`FLOOD_CODE_LEVELS`に載せない
——載っているコードはすべて現在アクティブな状態を表す、が表の意味である。
"""

from __future__ import annotations

from typing import NamedTuple

from app.domain.warning_levels import WarningBadgeLevel
from app.domain.strict_model import StrictModel


class FloodLevel(NamedTuple):
    """氾濫の段。バッジの見た目の語彙はJMA警報と共有するが、軸は別。"""

    level: int
    badge_level: WarningBadgeLevel
    suffix: str


_WATCH = FloodLevel(2, "advisory", "氾濫注意報")
_WARNING = FloodLevel(3, "warning", "氾濫警報")
_DANGER = FloodLevel(4, "severe_warning", "氾濫危険警報")
_EMERGENCY = FloodLevel(5, "emergency_warning", "氾濫特別警報")

# item.code → 段。
FLOOD_CODE_LEVELS: dict[str, FloodLevel] = {
    "20": _WATCH,
    "21": _WATCH,
    "22": _WATCH,
    "30": _WARNING,
    "31": _WARNING,
    "40": _DANGER,
    "41": _DANGER,
    "51": _EMERGENCY,
    "53": _EMERGENCY,
}


class ActiveFloodForecast(StrictModel):
    river_code: str
    river_name: str
    level: int
    badge_level: WarningBadgeLevel
    label: str
    condition: str
    report_datetime: str


def extract_active_flood_forecast(
    entry: dict, class20_code: str, class10_code: str
) -> ActiveFloodForecast | None:
    """r8指定河川洪水予報の電文1件から、出発地点に該当し現在アクティブな氾濫予報を取り出す。

    `entry`は`flood_xml.json`配列の1要素（`item.code`・`class20Codes`・`class10Codes`・
    `riverCode`・`riverName`・`reportDatetime`を持つ）。地点の該当判定は出発地点の
    class20Code（優先）またはclass10Codeが電文のclass20Codes/class10Codesに含まれるかで行う
    （行政区画の親子関係を辿るjma_area.resolve_areaで解決済みの値を渡す想定）。
    """
    item = entry.get("item") or {}
    flood_level = FLOOD_CODE_LEVELS.get(item.get("code"))
    if flood_level is None:
        return None

    class20_codes = entry.get("class20Codes") or []
    class10_codes = entry.get("class10Codes") or []
    if class20_code not in class20_codes and class10_code not in class10_codes:
        return None

    river_name = entry.get("riverName") or ""
    return ActiveFloodForecast(
        river_code=entry.get("riverCode", ""),
        river_name=river_name,
        level=flood_level.level,
        badge_level=flood_level.badge_level,
        label=f"{river_name}{flood_level.suffix}",
        condition=item.get("condition", ""),
        report_datetime=entry.get("reportDatetime", ""),
    )
