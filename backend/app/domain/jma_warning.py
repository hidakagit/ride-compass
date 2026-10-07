"""JMA警報・注意報の判断——どの種別をサイクリングに関わるとして出すかと、種別の名称から導く警戒の段。

配信元のコード→種別の名称・状態の文字列→発表中か、の読み替えは取りに行く層（`jma_warning_client.py`）が持ち、
ここへは読み替えた値（`AreaWarningKind`）で届く。1地点ぶんの警報は種類ごとの複数の電文
（VPWW55〜61）に分かれて届くため、電文配列の全件を走査する（warning_service.py参照）。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import get_args

from app.domain.warning_levels import WarningBadgeLevel
from app.domain.strict_model import StrictModel


#: サイクリングに関わらないため出さない種別の名称。**既定は出す**——気象庁が新しい種別を出したとき、
#: 黙って隠すより出す側へ倒す（段は`warning_level`が名称から導くため、新しい名称でも決まる）。
#: 路面凍結系（なだれ・低温・霜・着氷・着雪）と濃霧は、警告としての出し方が他と違うため別扱いにする。
#: 高潮・乾燥・融雪・その他の注意報は道路走行への関連が薄い。「解除」は発表の取り下げで、出すものが無い。
#: 名称はどれも読み替えの表にあること——無い名称を書いても何も起きないので、`jma_warning_client.py`が
#: importの時点で確かめる。
NOT_RELEVANT_TO_CYCLING: frozenset[str] = frozenset({
    "解除",
    "高潮警報",
    "融雪注意報",
    "高潮注意報",
    "濃霧注意報",
    "乾燥注意報",
    "なだれ注意報",
    "低温注意報",
    "霜注意報",
    "着氷注意報",
    "着雪注意報",
    "その他の注意報",
    "高潮特別警報",
    "高潮危険警報",
})

#: 段階ごとの呼び名（種別の名称の末尾の語。警戒度バッジもこの語を出す。domain/warning_display.py）。
JMA_LEVEL_LABELS: dict[WarningBadgeLevel, str] = {
    "advisory": "注意報",
    "warning": "警報",
    "severe_warning": "危険警報",
    "emergency_warning": "特別警報",
}

#: 重い段から。「危険警報」「特別警報」はどちらも「警報」を含むため、重い段の語を先に見る。
_HEAVIEST_FIRST: tuple[WarningBadgeLevel, ...] = tuple(reversed(get_args(WarningBadgeLevel)))


def warning_level(name: str) -> WarningBadgeLevel:
    """種別の名称から警戒レベル（バッジの色分けに使う）を導出する。

    レベルを別テーブルとして二重管理せず、名称が段の呼び名を含むかから導く。危険警報（警戒レベル4）は
    警報と特別警報の間の段。どの段の語も含まない名称は注意報の段。"""
    return next((level for level in _HEAVIEST_FIRST if JMA_LEVEL_LABELS[level] in name), "advisory")


class ActiveWarning(StrictModel):
    code: str
    name: str
    level: WarningBadgeLevel
    additions: list[str]


@dataclass(frozen=True)
class AreaWarningKind:
    """電文の1地域ぶんの1種別。警報が何も無い地域は、種別を1つも持たない。"""

    #: 配信元のコード。読まずに、種類ごとの電文に重なって現れた同じ種別をまとめる鍵と、応答の識別子に使う。
    code: str
    name: str
    #: 発表中か（発表・継続）。解除されたものはFalse。
    active: bool
    additions: tuple[str, ...]


@dataclass(frozen=True)
class WarningBulletin:
    """警報・注意報の電文1件。地域のコード→その地域の種別。電文が地域の項目を持たない
    （例: 高潮の電文は対象外の地域の区域を載せないことがある）なら、その地域のキーが無い。"""

    class20_kinds: dict[str, tuple[AreaWarningKind, ...]]
    class10_kinds: dict[str, tuple[AreaWarningKind, ...]]

    def kinds_for(self, class20_code: str, class10_code: str) -> tuple[AreaWarningKind, ...] | None:
        """区域（`class20_code`）の種別。区域の項目がある電文はその中身（「なし」でも）を使い、
        区域の項目が無い電文だけを二次細分区域（`class10_code`）で探す。どちらも無ければNone。"""
        kinds = self.class20_kinds.get(class20_code)
        return kinds if kinds is not None else self.class10_kinds.get(class10_code)


def extract_active_warnings(kinds: Iterable[AreaWarningKind]) -> list[ActiveWarning]:
    """電文の1地域ぶんの種別から、サイクリングに関連し現在発表中の警報・注意報だけを取り出す。"""
    return [
        ActiveWarning(code=kind.code, name=kind.name, level=warning_level(kind.name), additions=list(kind.additions))
        for kind in kinds
        if kind.active and kind.name not in NOT_RELEVANT_TO_CYCLING
    ]


def collect_active_warnings(
    bulletins: Iterable[WarningBulletin], class20_code: str, class10_code: str
) -> list[ActiveWarning]:
    """電文の一覧から、対象エリアぶんのアクティブな警報を返す。

    警報の種類ごとに電文が分かれているため、同じコードが複数の電文に現れうる。codeで重複を除く。
    """
    collected: dict[str, ActiveWarning] = {}

    for bulletin in bulletins:
        kinds = bulletin.kinds_for(class20_code, class10_code)
        if kinds is None:
            continue

        for item in extract_active_warnings(kinds):
            collected[item.code] = item

    return list(collected.values())
