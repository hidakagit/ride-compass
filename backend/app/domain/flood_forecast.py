"""JMA指定河川洪水予報の判断——出発地点にかかる発表中の予報を取り出し、段に河川名を付けて呼ぶ。

電文のコード（`item.code`）→段の読み替えは取りに行く層（`flood_client.py`）が持ち、ここへは読み替えた段で届く。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.warning_levels import WarningBadgeLevel
from app.domain.strict_model import StrictModel

#: 段階ごとの表示名（河川名の後ろに付ける語。警戒度バッジもこの語を出す。domain/warning_display.py）。
#: バッジの段の語彙はJMA警報と共有するが、軸は別。
FLOOD_LEVEL_LABELS: dict[WarningBadgeLevel, str] = {
    "advisory": "氾濫注意報",
    "warning": "氾濫警報",
    "severe_warning": "氾濫危険警報",
    "emergency_warning": "氾濫特別警報",
}


class ActiveFloodForecast(StrictModel):
    river_code: str
    badge_level: WarningBadgeLevel
    label: str
    condition: str


@dataclass(frozen=True)
class FloodBulletin:
    """指定河川洪水予報の電文1件（1河川の最新の状態）。文字の項目は、電文に無ければ空の文字。"""

    #: 発表中の段。解除された・コードの無い電文はNone。
    level: WarningBadgeLevel | None
    #: 予報の対象の区域（市区町村等）と二次細分区域のコード。
    class20_codes: tuple[str, ...]
    class10_codes: tuple[str, ...]
    river_code: str
    river_name: str
    condition: str


def extract_active_flood_forecast(
    bulletin: FloodBulletin, class20_code: str, class10_code: str
) -> ActiveFloodForecast | None:
    """電文1件から、出発地点に該当し現在アクティブな氾濫予報を取り出す。

    地点の該当判定は出発地点のclass20（優先）またはclass10が電文の対象の区域に含まれるかで行う
    （行政区画の親子関係を辿る`jma_area.resolve_area`で解決済みの値を渡す想定）。
    """
    if bulletin.level is None:
        return None

    if class20_code not in bulletin.class20_codes and class10_code not in bulletin.class10_codes:
        return None

    return ActiveFloodForecast(
        river_code=bulletin.river_code,
        badge_level=bulletin.level,
        label=f"{bulletin.river_name}{FLOOD_LEVEL_LABELS[bulletin.level]}",
        condition=bulletin.condition,
    )
