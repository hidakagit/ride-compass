"""静的道路属性の派生分類（docs/static-road-attributes-plan.md P0・§2.4）。

すべて純関数・unknown安全（タグが無い/未知の値は`None`または`"unknown"`を返し、
根拠のない推測はしない）。正準定義はここ1箇所（domain/road.pyのGOOD/BAD_OSM_SURFACE_TAGSと
同じ「正準1箇所」の運用、改善計画T7原則）。

車ストレス（改善計画T150で「交通ストレス」から改称）は専用Pythonレシピ（旧
car_stress_breakdown/car_stress_level）を改善計画T292で廃止し、AXIS_DEFINITIONS
（domain/axis_definitions.py）の内部軸5つ+公開軸1つの階層構造で再現している。

改善計画T347: 旧`classify_bicycle_infrastructure`（優先順位付き分類、SQL CASE式との
2箇所手書き複製が「生データの分類ロジックをPythonに持たせない」方針に反するという
ユーザー指摘を受け削除）は、正規化フラグ材料4種（`domain/recipe.py: bicycle_infra_flags`）
の組み合わせへ置き換えた（domain/evaluation.pyの軸材料合成が直接参照する）。
"""

from typing import Literal

# 信号・横断歩道・一時停止・踏切のnode空間マッチ用スナップ半径（静的道路属性P1、改善計画T44）。
# AttributeRepository.get_stop_poi_counts（デフォルト引数、GraphService.get_stop_poi_counts
# はこのデフォルトを暗黙使用）がこの定数をimportして参照する。
STOP_POI_MATCH_MAX_DISTANCE_M = 15.0

# 交差点（次数3以上のroad_node）の空間マッチ用半径（静的道路属性P1残り、intersectionDensity）。
# road_nodeは信号等のPOIと違い必ずEdgeの端点に位置するが、Edge単位（LATERAL join）で
# Edge geometry全体に対して距離判定するため、端点ちょうどではなくEdge沿いに近接する
# 交差点も拾えるよう、STOP_POI_MATCH_MAX_DISTANCE_Mより大きめの「物理的な道路網特徴への
# スナップ許容量」を採用する。
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

# 停止要因POIのkind正準集合（SQL側のkindフィルタ用、改善計画T145b実装中に発見したバグの
# 修正）。T101で補給POI（convenience/vending_machine等、SupplyPoiKind）が同じ
# `osm_raw_pois`テーブルへ入ったため、kindを絞らないCOUNTは停止密度へコンビニ・自販機を
# 誤算入する。停止密度系のSQL（_STOP_POI_COUNTS_SQL等）は必ずこの集合でフィルタする
# （設計原則2: 片側import。StopPoiKindのLiteral値と乖離しないようテストで照合する）。
STOP_POI_KINDS = frozenset(_HIGHWAY_STOP_KINDS.values()) | {"level_crossing"}


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
    """補給・休憩ポイント（コンビニ・自販機・トイレ・給水・駐輪場）の分類（改善計画T101、
    static-road-attributes-plan.md §2.3）。classify_stop_poiと同じくnode取込の対象判定にも
    使う（osm_adapter.py: osm_node_to_poi_spec）。停止要因POIとタグ名（shop/amenity vs
    highway/railway）が独立しており衝突しないため、優先順位の考慮は不要。

    実店舗との乖離（閉店・移転にOSM側が追従できていないリスク）はタグ自体からは
    分からないため、`backend/scripts/measure_poi_freshness.py`（2026-08-18実測）で
    要素の最終編集日時を代理指標に実測した。コンビニ（shop=convenience）は直近2年以内の
    編集が関東全域で62.4%と明確に新しいが、自販機・トイレ・給水・駐輪場は5年以上未編集が
    58〜59%と高く、実店舗との乖離リスクが相対的に高い（フロント側mapLayers.ts:
    supplyPoiのpanelHintで「鮮度に注意」と明記して利用者に伝える。取込・分類自体は
    5種すべて対象とし、鮮度の扱いは表示側の注意喚起に留める）。
    """
    if (tags.get("shop") or "").strip().lower() == "convenience":
        return "convenience"
    amenity = (tags.get("amenity") or "").strip().lower()
    return _AMENITY_SUPPLY_KINDS.get(amenity)
