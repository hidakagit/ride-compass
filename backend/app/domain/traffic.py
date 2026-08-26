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
の組み合わせへ置き換えた。`is_dedicated_bicycle_infra`はこのフラグ辞書を直接受け取る。
"""

from typing import Literal

# 信号・横断歩道・一時停止・踏切のnode空間マッチ用スナップ半径（静的道路属性P1、改善計画T44）。
# openrouteservice_engine.py（明示引数）とAttributeRepository各メソッド（デフォルト引数、
# GraphService.get_stop_poi_countsはこのデフォルトを暗黙使用）の両方がこの定数をimportして
# 参照する。domain/road.py: SURFACE_MATCH_MAX_DISTANCE_Mと同じ理由で「コメントで揃える」
# 手動同期にしない（設計原則2）。
STOP_POI_MATCH_MAX_DISTANCE_M = 15.0

# 交差点（次数3以上のroad_node）の空間マッチ用半径（静的道路属性P1残り、intersectionDensity）。
# road_nodeは信号等のPOIと違い必ずEdgeの端点に位置するため、Edge単位（road_graphエンジン、
# 端点そのもの）ではSTOP_POI_MATCH_MAX_DISTANCE_M相当でも十分だが、ORSエンジンのサンプル点は
# ルートgeometry上の等間隔点でありグラフのNodeに一致するとは限らないため、路面評価
# （domain/road.py: SURFACE_MATCH_MAX_DISTANCE_M=30m）と同じ「物理的な道路網特徴への
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


def _density_per_km(segments: list[tuple[float, int | None]]) -> float | None:
    """(区間distance_km, 区間内のcount)のリストから「合計count÷合計distance_km」を求める
    （密度は加算的な量の比であり、区間ごとに既に正規化された値の平均ではないため、
    domain/difficulty.pyのdistance_weighted_*とは異なる集約になる）。

    countがNoneの区間は「データ未取得（例: repository未注入）」を表し、0（実測で対象無し）
    とは区別して集計から除外する。除外後に1区間も残らない、または距離の合計が0以下ならNone。
    """
    available = [(distance, count) for distance, count in segments if count is not None]
    if not available:
        return None
    distance_sum = sum(distance for distance, _ in available)
    if distance_sum <= 0:
        return None
    count_sum = sum(count for _, count in available)
    return round(count_sum / distance_sum, 2)


def distance_weighted_stop_density(segments: list[tuple[float, int | None]]) -> float | None:
    """(区間distance_km, 区間内の停止要因count)のリストから、ルート全体の停止密度
    （回/km）を求める（静的道路属性P1）。"""
    return _density_per_km(segments)


def distance_weighted_intersection_density(segments: list[tuple[float, int | None]]) -> float | None:
    """(区間distance_km, 区間内の交差点count)のリストから、ルート全体の交差点密度
    （回/km）を求める（静的道路属性P1残り、intersectionDensity）。集約方法は
    distance_weighted_stop_densityと同じ（stop_countsに無いEdge/サンプル点はNone扱いで
    「データ未取得」と「実測0件」を区別する、road_score等と同じ方針）。"""
    return _density_per_km(segments)


def is_dedicated_bicycle_infra(flags: dict[str, bool] | None) -> bool | None:
    """正規化フラグ（`domain/recipe.py: bicycle_infra_flags`の戻り値）が「専用インフラ
    （分離自転車道・自転車レーン）」を示すかどうかを3値で返す（不明はNone。
    road.py: classify_osm_surfaceの3値判定と同じ考え方）。

    改善計画T347: 旧`classify_bicycle_infrastructure`の優先順位付き分類（separated/lane/
    shared_busway等の7値）を廃止し、cycleway/highway由来の判定のみを担う正規化フラグ4種
    （highway_is_cycleway/cycleway_has_track/cycleway_has_lane/cycleway_has_shared）から
    直接判定する。「専用」＝旧separated相当(highway_is_cycleway or cycleway_has_track)
    または旧lane相当(cycleway_has_lane)。cycleway_has_shared（旧shared_busway相当）は
    専用インフラに含めない（旧分類と同じ扱い）。

    `flags`がNone（way_tagsの空間マッチに失敗した区間、データ欠損）の場合はNoneを返す。
    これを怠ると、データ欠損区間が「専用インフラではないと確認された区間」として
    distance_weighted_bicycle_infra_scoreの分母に混入してしまう。
    """
    if flags is None:
        return None
    return flags.get("highway_is_cycleway", False) or flags.get("cycleway_has_track", False) or flags.get(
        "cycleway_has_lane", False
    )


def distance_weighted_bicycle_infra_score(pairs: list[tuple[float, bool | None]]) -> float | None:
    """(区間の距離, 専用の自転車インフラか)のペア列から、距離加重の専用インフラ率(%)を
    算出する（domain/road.py: distance_weighted_road_scoreと同じ集約方法。不明区間は
    分母から除外し、判定できる区間が1つも無ければNone）。"""
    known = sum(distance for distance, is_dedicated in pairs if is_dedicated is not None)
    if known <= 0:
        return None
    dedicated = sum(distance for distance, is_dedicated in pairs if is_dedicated)
    return round(dedicated / known * 100, 1)


