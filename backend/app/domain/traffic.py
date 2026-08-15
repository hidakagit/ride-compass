"""静的道路属性の派生分類（docs/static-road-attributes-plan.md P0・§2.4）。

すべて純関数・unknown安全（タグが無い/未知の値は`None`または`"unknown"`を返し、
根拠のない推測はしない）。正準定義はここ1箇所（domain/road.pyのGOOD/BAD_OSM_SURFACE_TAGSと
同じ「正準1箇所」の運用、改善計画T7原則）。

MVT生成（road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQL）はSQL側で同じ判定基準を
CASE式として実装しており、この関数群と1:1で対応させる（test_road_graph_repository.pyの
整合性テストで突き合わせる。SQL側にPythonを呼び出す手段が無いため、判定ロジック自体は
やむを得ず2箇所に存在するが、同じ入力に対し常に同じ出力になることをテストで担保する）。
"""

from typing import Literal

# 信号・横断歩道・一時停止・踏切のnode空間マッチ用スナップ半径（静的道路属性P1、改善計画T44）。
# openrouteservice_engine.py（明示引数）とAttributeRepository各メソッド（デフォルト引数、
# GraphService.get_stop_poi_countsはこのデフォルトを暗黙使用）の両方がこの定数をimportして
# 参照する。domain/road.py: SURFACE_MATCH_MAX_DISTANCE_Mと同じ理由で「コメントで揃える」
# 手動同期にしない（設計原則2）。
STOP_POI_MATCH_MAX_DISTANCE_M = 15.0

# smoothness→スコア(0-100)。未設定・未知の値はNone（評価しない）。
_SMOOTHNESS_SCORES: dict[str, float] = {
    "excellent": 100.0,
    "good": 85.0,
    "intermediate": 60.0,
    "bad": 30.0,
    "very_bad": 10.0,
    "horrible": 0.0,
    "very_horrible": 0.0,
    "impassable": 0.0,
}


def smoothness_score(tags: dict[str, str]) -> float | None:
    value = tags.get("smoothness")
    if value is None:
        return None
    return _SMOOTHNESS_SCORES.get(value.strip().lower())


def parse_lanes(tags: dict[str, str]) -> int | None:
    """lanesタグを正の整数へ変換する。表記ゆれ（小数点混じり等）は緩く許容し、
    パース不能・0以下はNone。"""
    raw = tags.get("lanes")
    if raw is None:
        return None
    try:
        value = int(float(raw.strip()))
    except ValueError:
        return None
    return value if value > 0 else None


def parse_maxspeed(tags: dict[str, str]) -> int | None:
    """maxspeedタグを正の整数(km/h)へ変換する。日本のOSMはkm/h数値表記が主のため、
    "50 mph"のような単位付き表記はパース対象外としNoneを返す（unknown安全。
    誤った単位変換で実際より安全側/危険側の値を作らないため）。"""
    raw = tags.get("maxspeed")
    if raw is None:
        return None
    cleaned = raw.strip().lower()
    if not cleaned or not cleaned.replace(".", "", 1).isdigit():
        return None
    value = int(float(cleaned))
    return value if value > 0 else None


def _cycleway_values(tags: dict[str, str]) -> list[str]:
    """cycleway/cycleway:left/cycleway:right/cycleway:bothのうち設定済みの値を集める
    （left/right統合の正規化。計画書のcycleway*表記に対応）。"""
    keys = ("cycleway", "cycleway:left", "cycleway:right", "cycleway:both")
    return [tags[k].strip().lower() for k in keys if tags.get(k)]


BicycleInfraClass = Literal[
    "separated", "lane", "shared_busway", "shared_pedestrian", "roadway", "prohibited", "unknown"
]


def classify_bicycle_infrastructure(tags: dict[str, str], highway: str | None) -> BicycleInfraClass:
    """自転車インフラ分類（優先順位: separated＞lane＞shared_busway等＞shared_pedestrian＞
    roadway/prohibited＞unknown。計画書§2.4）。"""
    cycleway_values = _cycleway_values(tags)
    bicycle = (tags.get("bicycle") or "").strip().lower()

    if highway == "cycleway" or "track" in cycleway_values:
        return "separated"
    if "lane" in cycleway_values:
        return "lane"
    if any(v in ("share_busway", "shared_lane") for v in cycleway_values):
        return "shared_busway"
    if highway in ("path", "footway") and bicycle in ("yes", "designated", "permissive"):
        return "shared_pedestrian"
    if bicycle == "no":
        return "prohibited"
    if highway is not None:
        return "roadway"
    return "unknown"


# 交通ストレス基本値（highwayのみで決定、全wayで必ず決まる。計画書§2.4）。
TRAFFIC_STRESS_BASE_BY_HIGHWAY: dict[str, int] = {
    "cycleway": 1,
    "living_street": 2,
    "residential": 2,
    "unclassified": 2,
    "track": 2,
    "tertiary": 3,
    "tertiary_link": 3,
    "secondary": 4,
    "secondary_link": 4,
    "primary": 4,
    "primary_link": 4,
    "trunk": 4,
    "trunk_link": 4,
}


StopPoiKind = Literal["traffic_signals", "crossing", "stop", "give_way", "level_crossing"]

_HIGHWAY_STOP_KINDS: dict[str, StopPoiKind] = {
    "traffic_signals": "traffic_signals",
    "crossing": "crossing",
    "stop": "stop",
    "give_way": "give_way",
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


def distance_weighted_stop_density(segments: list[tuple[float, int | None]]) -> float | None:
    """(区間distance_km, 区間内の停止要因count)のリストから、ルート全体の停止密度
    （回/km）を求める（静的道路属性P1）。domain/difficulty.pyのdistance_weighted_*と違い
    「率の加重平均」ではなく「合計count÷合計distance_km」が正しい集約（密度は加算的な量の
    比であり、区間ごとに既に正規化された値の平均ではないため）。

    countがNoneの区間は「データ未取得（例: repository未注入）」を表し、0（実測でPOI無し）
    とは区別して集計から除外する（distance_weighted_difficulty等、他のdistance_weighted_*と
    同じ「欠損は除外し残りで再正規化」の考え方）。除外後に1区間も残らない、または距離の
    合計が0以下ならNone。"""
    available = [(distance, count) for distance, count in segments if count is not None]
    if not available:
        return None
    distance_sum = sum(distance for distance, _ in available)
    if distance_sum <= 0:
        return None
    count_sum = sum(count for _, count in available)
    return round(count_sum / distance_sum, 2)


def traffic_stress_level(highway: str | None, tags: dict[str, str]) -> int | None:
    """交通ストレス（LTS: Level of Traffic Stress風の1-4段階。「交通量」ではなく
    「推定交通ストレス」、計画書§2.4）。基本値はhighwayのみで決まり、未知のhighwayは
    None（評価しない）。補正はタグが実際にある場合のみ適用する（unknownは補正しない）。
    """
    base = TRAFFIC_STRESS_BASE_BY_HIGHWAY.get(highway or "")
    if base is None:
        return None

    # motor_vehicle=no（自転車可）は他の補正に関わらず1に固定（計画書§2.4）。
    if (tags.get("motor_vehicle") or "").strip().lower() == "no":
        return 1

    level = base
    cycleway_values = _cycleway_values(tags)
    if "track" in cycleway_values:
        level -= 2
    elif "lane" in cycleway_values:
        level -= 1

    maxspeed = parse_maxspeed(tags)
    if maxspeed is not None:
        if maxspeed <= 30:
            level -= 1
        elif maxspeed >= 60:
            level += 1

    lanes = parse_lanes(tags)
    if lanes is not None and lanes >= 4:
        level += 1

    return max(1, min(4, level))
