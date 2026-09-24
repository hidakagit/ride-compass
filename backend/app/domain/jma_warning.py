"""JMA警報・注意報コードの定義。

コード対応表は気象庁「気象警報・注意報（Ｒ０６）」電文フォーマット解説資料の別表3
（警戒レベル等対応コード表、令和8年5月29日の運用切替以降の現行r8スキーマ）を
典拠とする。同資料の別表1により、これらのコードは複数の電文
（VPWW55〜61。大雨・土砂災害・高潮・暴風/暴風雪・波浪・大雪・その他の注意報を
それぞれ別電文として発表）に分散しているため、1地点ぶんの警報を網羅するには
r8警報API（jma_warning_client.py）が返す電文配列の全件を走査する必要がある
（warning_service.py参照）。
"""

from __future__ import annotations

from typing import NamedTuple

from app.domain.warning_levels import WarningBadgeLevel
from app.domain.strict_model import StrictModel


class WarningKind(NamedTuple):
    """1コードぶんの種別。名称と、サイクリングで出すかどうかを1つに束ねる——名称の表と
    除外する側の表を分けて持つと、名称の無いコードを除外へ書いても何も起きず、その指定は
    効かないまま残る。"""

    name: str
    #: サイクリングに関わらないため出さない種別はFalse。**既定はTrue**——気象庁が新しい
    #: 種別を出したとき、黙って隠すより出す側へ倒す（レベルは`warning_level`が名称から
    #: 導くため、新しい名称でも段は決まる）。
    relevant_to_cycling: bool = True


# 気象庁公式コード対応表（別表3）の全コード→種別。「レベルN」プレフィックスは
# warning_level()がlevelフィールドとして別途表現するため、名称からは省いている
# （同じ情報を2箇所で別々に持たない）。対応表で※1（予約領域）とされ割り当ての無い
# コードは含めない。
#
# 出さない側の理由: 路面凍結系（なだれ・低温・霜・着氷・着雪）と濃霧は、警告としての
# 出し方が他と違うため別扱いにする。高潮・乾燥・融雪・その他の注意報は道路走行への
# 関連が薄い。「解除」は発表の取り下げで、出すものが無い。
WARNING_KINDS: dict[str, WarningKind] = {
    "00": WarningKind("解除", relevant_to_cycling=False),
    "02": WarningKind("暴風雪警報"),
    "03": WarningKind("大雨警報"),
    "04": WarningKind("洪水警報"),
    "05": WarningKind("暴風警報"),
    "06": WarningKind("大雪警報"),
    "07": WarningKind("波浪警報"),
    "08": WarningKind("高潮警報", relevant_to_cycling=False),
    "09": WarningKind("土砂災害警報"),
    "10": WarningKind("大雨注意報"),
    "12": WarningKind("大雪注意報"),
    "13": WarningKind("風雪注意報"),
    "14": WarningKind("雷注意報"),
    "15": WarningKind("強風注意報"),
    "16": WarningKind("波浪注意報"),
    "17": WarningKind("融雪注意報", relevant_to_cycling=False),
    "18": WarningKind("洪水注意報"),
    "19": WarningKind("高潮注意報", relevant_to_cycling=False),
    "20": WarningKind("濃霧注意報", relevant_to_cycling=False),
    "21": WarningKind("乾燥注意報", relevant_to_cycling=False),
    "22": WarningKind("なだれ注意報", relevant_to_cycling=False),
    "23": WarningKind("低温注意報", relevant_to_cycling=False),
    "24": WarningKind("霜注意報", relevant_to_cycling=False),
    "25": WarningKind("着氷注意報", relevant_to_cycling=False),
    "26": WarningKind("着雪注意報", relevant_to_cycling=False),
    "27": WarningKind("その他の注意報", relevant_to_cycling=False),
    "29": WarningKind("土砂災害注意報"),
    "32": WarningKind("暴風雪特別警報"),
    "33": WarningKind("大雨特別警報"),
    "35": WarningKind("暴風特別警報"),
    "36": WarningKind("大雪特別警報"),
    "37": WarningKind("波浪特別警報"),
    "38": WarningKind("高潮特別警報", relevant_to_cycling=False),
    "39": WarningKind("土砂災害特別警報"),
    "43": WarningKind("大雨危険警報"),
    "48": WarningKind("高潮危険警報", relevant_to_cycling=False),
    "49": WarningKind("土砂災害危険警報"),
}

# 警報・注意報が「現在発表中」であることを示すstatus値。「解除」（直前まで出ていたが
# 取り下げられた）と「発表警報・注意報はなし」（元々何も出ていない、code自体を持たない）
# はどちらも現在アクティブではないため対象外。
ACTIVE_STATUSES = frozenset({"発表", "継続"})


def warning_level(code: str) -> WarningBadgeLevel:
    """コードから警戒レベル（バッジの色分けに使う）を導出する。対応表に無いコードは
    KeyError——呼び出し側は必ず`WARNING_KINDS`で引いた後に呼ぶ。

    レベルを別テーブルとして二重管理せず、名称文字列（「特別警報」「危険警報」「警報」を
    含むか）から導出する（片側import）。危険警報（警戒レベル4）は警報と特別警報の間の段。
    「危険警報」「特別警報」はどちらも「警報」を含むため、「警報」より先に見る。"""
    name = WARNING_KINDS[code].name
    if "特別警報" in name:
        return "emergency_warning"
    if "危険警報" in name:
        return "severe_warning"
    if "警報" in name:
        return "warning"
    return "advisory"


class ActiveWarning(StrictModel):
    code: str
    name: str
    level: WarningBadgeLevel
    additions: list[str]


def extract_active_warnings(kinds: list[dict]) -> list[ActiveWarning]:
    """JMA r8警報JSONの1地域ぶんの`kinds`配列から、サイクリングに関連し現在発表中の
    警報・注意報だけを取り出す。

    `kinds`の要素は`{"code": "14", "status": "発表", "additions": [...]}`（発表中）、
    または警報が何も無い地域の`{"status": "発表警報・注意報はなし"}`（codeキー自体が
    無い）のいずれか。"""
    result: list[ActiveWarning] = []
    for kind in kinds:
        code = kind.get("code")
        if code is None or kind.get("status") not in ACTIVE_STATUSES:
            continue
        registered = WARNING_KINDS.get(code)
        if registered is None or not registered.relevant_to_cycling:
            continue
        result.append(
            ActiveWarning(
                code=code,
                name=registered.name,
                level=warning_level(code),
                additions=kind.get("additions", []),
            )
        )
    return result
