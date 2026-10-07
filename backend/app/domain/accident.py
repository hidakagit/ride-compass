"""警察庁交通事故統計オープンデータの事故を道路へ帰属させ、数えるときの判断。

本票CSV（honhyo_YYYY.csv）の列名とコードの読み替えは、生データを読む副問い合わせ
（`infrastructure/source_models.py: ACCIDENTS_SOURCE_SQL`）が持ち、ここへは読み替えた列で届く。
"""

from enum import StrEnum

# 事故地点を道路へスナップする際の探索半径。事故点はOSMの要素ではないため、信号・交差点の
# ように「wayの構成ノードか」で帰属を決められず、距離で最も近い道路を選ぶしかない。
# 緯度経度は本票の度分秒表記からの変換値でOSM nodeよりジオコーディング精度が粗いため、
# 半径は大きめに採る。
ACCIDENT_MATCH_MAX_DISTANCE_M = 30.0

# 死亡事故の重み。件数を単純にCOUNTすると軽傷の物損に近い事故と死亡事故が同じ1件として
# 扱われ、最も避けたい重大事故のリスクが薄まるため、死亡事故はこの件数分として積算する
# （「死亡事故は軽傷事故の3件分のリスク」という意味づけの値で、実測から導いたものではない）。
ACCIDENT_FATAL_WEIGHT = 3.0


class PartyType(StrEnum):
    """当事者種別のうち、判定が名指すもの。"""

    #: 軽車両－自転車。
    BICYCLE = "bicycle"
    #: 軽車両－駆動補助機付自転車（電動アシスト自転車）。
    POWER_ASSISTED_BICYCLE = "power_assisted_bicycle"
    #: 判定が名指さない種別（自動車・歩行者・軽車両－その他等）。
    OTHER = "other"


#: 自転車関連事故とみなす当事者種別。軽車両－その他（手押し車等）は自転車ではないため含めない。
BICYCLE_PARTY_TYPES: frozenset[PartyType] = frozenset({PartyType.BICYCLE, PartyType.POWER_ASSISTED_BICYCLE})


# --- 生データの列から判定する式 -----------------------------------------------
#
# 判定の規則をここだけが持つ。読む側は都度これを使う——同じ判定をタイルと集計で別々に書くとずれる。
# 別名`a`は事故の生データの行（`infrastructure/source_models.py: ACCIDENTS_SOURCE_SQL`）を指す。

FATAL_SQL = "coalesce(a.deaths, 0) > 0"

_BICYCLE_PARTY_LIST = ", ".join(f"'{party}'" for party in sorted(BICYCLE_PARTY_TYPES))
#: 当事者のどちらかが自転車なら自転車関連事故とみなす式。
BICYCLE_SQL = f"(a.party_type_a IN ({_BICYCLE_PARTY_LIST}) OR a.party_type_b IN ({_BICYCLE_PARTY_LIST}))"
