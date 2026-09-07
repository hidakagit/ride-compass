"""静的道路属性の派生分類（docs/static-road-attributes-plan.md P0・§2.4）。

すべて純関数・unknown安全（タグが無い/未知の値は`None`または`"unknown"`を返し、
根拠のない推測はしない）。正準定義はここ1箇所（domain/road.pyのGOOD/BAD_OSM_SURFACE_TAGSと
同じ「正準1箇所」の運用）。

車ストレスはAXIS_DEFINITIONS（domain/axis_definitions.py）の内部軸5つ+公開軸1つの
階層構造で再現している。自転車インフラは正規化フラグ材料4種
（`domain/recipe.py: bicycle_infra_flags`）の組み合わせで表し、
domain/evaluation.pyの軸材料合成が直接参照する。
"""

from typing import Literal

# 信号・横断歩道・一時停止・踏切のnode空間マッチ用スナップ半径（静的道路属性P1）。
# AttributeRepository.get_stop_poi_counts（デフォルト引数、GraphService.get_stop_poi_counts
# はこのデフォルトを暗黙使用）がこの定数をimportして参照する。
STOP_POI_MATCH_MAX_DISTANCE_M = 15.0

# 交差点（次数3以上のroad_node）の空間マッチ用半径（静的道路属性P1残り、intersectionDensity）。
# road_nodeは信号等のPOIと違い必ずEdgeの端点に位置するが、Edge単位（LEFT JOIN）で
# Edge geometry全体に対して距離判定するため、端点ちょうどではなくEdge沿いに近接する
# 交差点も拾えるよう、STOP_POI_MATCH_MAX_DISTANCE_Mより大きめの「物理的な道路網特徴への
# スナップ許容量」を採用する（domain/accident.py: ACCIDENT_MATCH_MAX_DISTANCE_Mと同じ30m。
# 値が一致するのは意図的で、片方だけ変える場合は意図的な差別化かどうかを検討すること）。
INTERSECTION_MATCH_MAX_DISTANCE_M = 30.0

# 交差点判定の次数しきい値（この数以上の異なる隣接Nodeを持つNodeを交差点とみなす）。
INTERSECTION_DEGREE_THRESHOLD = 3

StopPoiKind = Literal["traffic_signals", "crossing", "stop", "give_way", "level_crossing"]

_HIGHWAY_STOP_KINDS: dict[str, StopPoiKind] = {
    "traffic_signals": "traffic_signals",
    "crossing": "crossing",
    "stop": "stop",
    "give_way": "give_way",
}

# 停止要因POIのkind正準集合（SQL側のkindフィルタ用）。補給POI（convenience/
# vending_machine等、SupplyPoiKind）が同じ`osm_raw_pois`テーブルへ入っているため、
# kindを絞らないCOUNTは停止密度へコンビニ・自販機を誤算入する。停止密度系のSQL
# （_STOP_POI_COUNTS_SQL等）は必ずこの集合でフィルタする（設計原則2: 片側import。
# StopPoiKindのLiteral値と乖離しないようテストで照合する）。
STOP_POI_KINDS = frozenset(_HIGHWAY_STOP_KINDS.values()) | {"level_crossing"}


# 停止要因の集計キー（`edge_attribute_counts.poi_counts`・`way_attribute_counts.poi_counts`の
# jsonbキー）と、その日本語ラベル。**キーの単一ソース**で、材料
# （`domain/material_catalog.py`の`poi_*_per_km`）はこの一覧から生成する。
#
# `StopPoiKind`（取込時の分類）と1対1ではない。分ける基準は「評価軸で違う重みを付けたいか」
# だけで、次の2点で異なる:
# - `crossing`は信号の有無で意味が変わるため`crossing_signals`と`crossing`へ分ける
#   （日本のOSMは押しボタン式・歩車分離の信号を`highway=crossing`＋`crossing=traffic_signals`
#   で表すため、`crossing`を一括で扱うと実質的な信号の半分が横断歩道に紛れる）
# - `give_way`は`stop`へ畳む（実データ上ほぼ存在せず、一時停止と重みを分ける意味が無い）
POI_COUNT_KINDS: dict[str, str] = {
    "traffic_signals": "信号",
    "crossing_signals": "信号付き横断歩道",
    "crossing": "横断歩道(信号なし)",
    "stop": "一時停止・徐行",
    "level_crossing": "踏切",
}


def classify_stop_poi(tags: dict[str, str]) -> StopPoiKind | None:
    """信号・横断歩道・一時停止・踏切の分類（静的道路属性P1、計画書§2.2）。node取込の
    対象node判定にも使う（osm_adapter.py: osm_node_to_poi_spec、Noneを返すnodeは取込対象外）。

    railway=level_crossingとhighway=*は独立したタグのため、両方が同一nodeに付く場合は
    railway側を優先する（踏切は自転車にとって一時停止の法的義務が信号・横断歩道より
    強く、質的に異なるため）。いずれにも該当しなければNone（対象外・評価しない）。
    """
    if (tags.get("railway") or "").strip().lower() == "level_crossing":
        return "level_crossing"
    highway = (tags.get("highway") or "").strip().lower()
    return _HIGHWAY_STOP_KINDS.get(highway)


SupplyPoiKind = Literal["convenience", "vending_machine", "toilets", "drinking_water", "bicycle_parking"]

_AMENITY_SUPPLY_KINDS: dict[str, SupplyPoiKind] = {
    "vending_machine": "vending_machine",
    "toilets": "toilets",
    "drinking_water": "drinking_water",
    "bicycle_parking": "bicycle_parking",
}


def classify_supply_poi(tags: dict[str, str]) -> SupplyPoiKind | None:
    """補給・休憩ポイント（コンビニ・自販機・トイレ・給水・駐輪場）の分類
    （static-road-attributes-plan.md §2.3）。classify_stop_poiと同じくnode取込の対象判定にも
    使う（osm_adapter.py: osm_node_to_poi_spec）。停止要因POIとタグ名（shop/amenity vs
    highway/railway）が独立しており衝突しないため、優先順位の考慮は不要。

    実店舗との乖離（閉店・移転にOSM側が追従できていないリスク）はタグ自体からは
    分からない。`backend/scripts/measure_poi_freshness.py`で要素の最終編集日時を
    代理指標に計測すると、コンビニ（shop=convenience）は直近2年以内の編集が関東全域で
    62.4%と明確に新しいが、自販機・トイレ・給水・駐輪場は5年以上未編集が58〜59%と高く、
    実店舗との乖離リスクが相対的に高い（フロント側mapLayers.ts: supplyPoiのpanelHintで
    「鮮度に注意」と明記して利用者に伝える。取込・分類自体は5種すべて対象とし、鮮度の
    扱いは表示側の注意喚起に留める）。
    """
    if (tags.get("shop") or "").strip().lower() == "convenience":
        return "convenience"
    amenity = (tags.get("amenity") or "").strip().lower()
    return _AMENITY_SUPPLY_KINDS.get(amenity)
