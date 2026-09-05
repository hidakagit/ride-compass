"""緯度経度→JMA警報エリアコードの解決。

JMA警報API（r8スキーマ）は府県予報区単位（例: 東京都全体）でしか個別に問い合わせられ
ないが、レスポンス内の`class10Items`/`class20Items`は都道府県内の細分区域ごとに警報を
持つ（例: 東京地方 vs 伊豆諸島北部 vs 小笠原諸島）。地点を正しい細分区域まで解決する
ために、気象庁が公開する地域マスタ（area.json）の親子関係
（class20=市区町村等 → class15 → class10=一次細分区域 → offices=府県予報区）を辿る。

class20のエリアコードは、国土地理院リバースジオコーダが返すJIS市区町村コード（5桁）の
末尾に"00"を付けたものと一致する（公式仕様書での明記は見つかっていないが、東京都千代田区・
小笠原村の2地点で確認した限りこの規則で例外なく一致する）。
これにより、GSIの市区町村名と気象庁の地域名を文字列突合する必要がない。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedArea:
    class20_code: str
    class10_code: str
    office_code: str
    class10_name: str


def municipality_code_to_class20_code(muni_cd: str) -> str:
    return f"{muni_cd}00"


def resolve_area(muni_cd: str, area_data: dict) -> ResolvedArea | None:
    """area.json（気象庁の地域マスタ）を使い、JIS市区町村コードからJMA警報エリア
    （class20/class10/office）を解決する。muni_cdがarea.jsonのclass20に存在しない
    （例: 海外・データ不整合）場合はNoneを返す。"""
    class20s = area_data.get("class20s", {})
    class15s = area_data.get("class15s", {})
    class10s = area_data.get("class10s", {})

    class20_code = municipality_code_to_class20_code(muni_cd)
    class20 = class20s.get(class20_code)
    if class20 is None:
        return None

    # class15→class10まで親を辿る。区域によってはclass20の親が既にclass10自身になっている
    # （細分がそれ以上分かれない）ため、class10sに見つかるまでループする。
    # area.jsonは気象庁が公開する外部データのため、想定外の形式のエントリ
    # （"parent"/"name"キー欠如）が来てもKeyErrorを伝播させず、この関数自身のNone契約
    # （関数docstring「データ不整合の場合はNoneを返す」）どおりに倒す（他の外部データ
    # 処理関数と同じ.get()ベースの流儀へ揃えている）。
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
