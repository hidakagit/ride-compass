"""地点が属する区域（class20）から、JMA警報エリアの親子関係を解決する。

JMA警報API（r8スキーマ）は府県予報区単位（例: 東京都全体）でしか個別に問い合わせられ
ないが、レスポンス内の`class10Items`/`class20Items`は都道府県内の細分区域ごとに警報を
持つ（例: 東京地方 vs 伊豆諸島北部 vs 小笠原諸島）。地点を正しい細分区域まで解決する
ために、気象庁が公開する地域マスタ（area.json）の親子関係
（class20=市区町村等 → class15 → class10=一次細分区域 → offices=府県予報区）を辿る。
地点→class20は区域の境界（`infrastructure/jma_area_boundaries.py`）が引く。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("ridecompass.jma_area")


@dataclass(frozen=True)
class ResolvedArea:
    class20_code: str
    class10_code: str
    office_code: str
    class10_name: str


def resolve_area(class20_code: str, area_data: dict) -> ResolvedArea | None:
    """area.json（気象庁の地域マスタ）を使い、区域のコードからJMA警報エリア
    （class20/class10/office）を解決する。辿れなければNoneを返す。"""
    class20s = area_data.get("class20s", {})
    class15s = area_data.get("class15s", {})
    class10s = area_data.get("class10s", {})

    class20 = class20s.get(class20_code)
    if class20 is None:
        # 区域の境界と地域マスタは別々に配られるため、片方だけが区域の変更に追いついていると起きる。
        logger.warning("区域の境界が返したコードが地域マスタ(area.json)に無い class20=%s", class20_code)
        return None

    # class15→class10まで親を辿る。区域によってはclass20の親が既にclass10自身になっている
    # （細分がそれ以上分かれない）ため、class10sに見つかるまでループする。
    # area.jsonは外部データのため、キー欠如はKeyErrorを投げずNoneへ倒す。
    code = class20.get("parent")
    if code is None:
        return None
    seen = {code}
    while code not in class10s:
        parent_entry = class15s.get(code)
        if parent_entry is None:
            return None
        parent = parent_entry.get("parent")
        if parent is None:
            return None
        if parent in seen:
            # 循環参照は本来あり得ないが、外部データを無限ループさせないための安全弁。
            return None
        seen.add(parent)
        code = parent

    class10 = class10s[code]
    office_code = class10.get("parent")
    class10_name = class10.get("name")
    if office_code is None or class10_name is None:
        return None
    return ResolvedArea(
        class20_code=class20_code,
        class10_code=code,
        office_code=office_code,
        class10_name=class10_name,
    )
