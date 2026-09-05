"""JMA指定河川洪水予報の警戒レベル判定。

コード対応表は気象庁「指定河川洪水予報」電文フォーマット解説資料の表２
（令和8年度出水期以降の対応表、dmdata.jp経由で取得）を典拠とする。
実際のライブデータ（神田川のレベル4氾濫危険警報・善福寺川のレベル2氾濫注意報解除の例）と
突き合わせて確認済み。

JMA警報（jma_warning.py）と異なり、このAPIはstatus文字列（"発表"/"継続"/"解除"）
ではなく、item.code自体が「発表」「継続」「解除」「警報解除（下位レベルへの引き下げ）」を
区別する（例: code"20"=新規発表、"21"=継続、"22"=上位警報解除で当レベルへ引き下げ、
"10"=完全解除）。code"10"だけが「現在は何も発表されていない」を意味する唯一のコードで、
それ以外（20/21/22/30/31/40/41/51/53）はすべて現在アクティブな状態を表す。
"""

from __future__ import annotations

from pydantic import BaseModel

# item.code → レベル（2〜5）。
FLOOD_CODE_LEVELS: dict[str, int] = {
    "20": 2,
    "21": 2,
    "22": 2,
    "30": 3,
    "31": 3,
    "40": 4,
    "41": 4,
    "51": 5,
    "53": 5,
}

# 「レベル2氾濫注意報解除」を意味する唯一のコード（完全解除、現在アクティブな発表なし）。
CLEARED_CODE = "10"

LEVEL_SUFFIXES: dict[int, str] = {
    2: "氾濫注意報",
    3: "氾濫警報",
    4: "氾濫危険警報",
    5: "氾濫特別警報",
}

# WarningBadgeの4段階（WBGTと同じ語彙、advisory/warning/severe_warning/emergency_warning）
# へレベル2〜5をそのまま対応させる。JMA警報の3段階とは異なる軸だが、バッジの見た目の
# 語彙は共有できる（severe_warningは既に追加済み）。
LEVEL_BADGE_LEVELS: dict[int, str] = {
    2: "advisory",
    3: "warning",
    4: "severe_warning",
    5: "emergency_warning",
}


class ActiveFloodForecast(BaseModel):
    river_code: str
    river_name: str
    level: int
    badge_level: str
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
    code = item.get("code")
    if code is None or code == CLEARED_CODE:
        return None
    level = FLOOD_CODE_LEVELS.get(code)
    if level is None:
        return None

    class20_codes = entry.get("class20Codes") or []
    class10_codes = entry.get("class10Codes") or []
    if class20_code not in class20_codes and class10_code not in class10_codes:
        return None

    river_name = entry.get("riverName") or ""
    return ActiveFloodForecast(
        river_code=entry.get("riverCode", ""),
        river_name=river_name,
        level=level,
        badge_level=LEVEL_BADGE_LEVELS[level],
        label=f"{river_name}{LEVEL_SUFFIXES[level]}",
        condition=item.get("condition", ""),
        report_datetime=entry.get("reportDatetime", ""),
    )
