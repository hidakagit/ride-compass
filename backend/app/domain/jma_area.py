"""地点が属する区域（class20）から、JMA警報エリアの親子関係を解決する。

JMA警報API（r8スキーマ）は府県予報区単位（例: 東京都全体）でしか個別に問い合わせられ
ないが、レスポンス内の`class10Items`/`class20Items`は都道府県内の細分区域ごとに警報を
持つ（例: 東京地方 vs 伊豆諸島北部 vs 小笠原諸島）。地点を正しい細分区域まで解決する
ために、気象庁が公開する地域マスタ（area.json）の親子関係
（class20=市区町村等 → class15 → class10=一次細分区域 → offices=府県予報区）を辿る。
地点→class20は区域の境界（`infrastructure/jma_area_boundaries.py`）が引き、area.jsonの形は
`infrastructure/jma_warning_client.py`が`AreaMaster`へ解く。
"""

from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class ResolvedArea:
    class20_code: str
    class10_code: str
    office_code: str


@dataclass(frozen=True)
class AreaEntry:
    """地域マスタの1区域。親の無い区域もある（外部のデータのため）。"""

    parent: str | None


@dataclass(frozen=True)
class AreaMaster:
    """地域マスタ（area.json）のうち、警報エリアの解決に使う階層。区域のコード→区域。"""

    class20s: dict[str, AreaEntry]
    class15s: dict[str, AreaEntry]
    class10s: dict[str, AreaEntry]


def resolve_area(class20_code: str, master: AreaMaster) -> ResolvedArea | None:
    """地域マスタを使い、区域のコードからJMA警報エリア（class20/class10/office）を解決する。
    辿れなければNoneを返す。"""
    class20 = master.class20s.get(class20_code)
    if class20 is None:
        return None

    # class15→class10まで親を辿る。区域によってはclass20の親が既にclass10自身になっている
    # （細分がそれ以上分かれない）ため、class10sに見つかるまでループする。
    code = class20.parent
    if code is None:
        return None
    seen = {code}
    while code not in master.class10s:
        parent_entry = master.class15s.get(code)
        if parent_entry is None or parent_entry.parent is None:
            return None
        parent = parent_entry.parent
        if parent in seen:
            # 循環参照は本来あり得ないが、外部データを無限ループさせないための安全弁。
            return None
        seen.add(parent)
        code = parent

    class10 = master.class10s[code]
    office_code = class10.parent
    if office_code is None:
        return None
    return ResolvedArea(class20_code=class20_code, class10_code=code, office_code=office_code)
