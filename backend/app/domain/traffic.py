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

# 交差点（次数3以上のroad_node）の空間マッチ用半径（静的道路属性P1残り、intersectionDensity）。
# road_nodeは信号等のPOIと違い必ずEdgeの端点に位置するため、Edge単位（road_graphエンジン、
# 端点そのもの）ではSTOP_POI_MATCH_MAX_DISTANCE_M相当でも十分だが、ORSエンジンのサンプル点は
# ルートgeometry上の等間隔点でありグラフのNodeに一致するとは限らないため、路面評価
# （domain/road.py: SURFACE_MATCH_MAX_DISTANCE_M=30m）と同じ「物理的な道路網特徴への
# スナップ許容量」を採用する。
INTERSECTION_MATCH_MAX_DISTANCE_M = 30.0

# 交差点判定の次数しきい値（この数以上の異なる隣接Nodeを持つNodeを交差点とみなす）。
INTERSECTION_DEGREE_THRESHOLD = 3

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
    roadway/prohibited＞unknown。計画書§2.4）。

    cycleway/cycleway:left/right/bothタグは`traffic_stress_level`（本モジュール）でも
    「専用自転車道の有無」の補正に使われている（trackなら-2、laneなら-1）。同じ入力を
    別目的で解釈しているため、bicycle_infra_score（本分類ベース）とtraffic_stress_score
    （交通ストレス）は完全には独立ではなく、専用自転車道が併設された区間では両方が
    同時に「易しい」側へ動く（改善計画T62、意図的な設計でありバグではない）。
    """
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


# 交通ストレス基本値（highwayのみで決定。計画書§2.4）。
#
# path/footway/pedestrian/bridleway/steps・motorway/motorway_link・service/roadは意図的に
# 未登録（`traffic_stress_level`はbase=Noneのため常にNoneを返し、交通ストレス軸では評価
# 対象外になる）。「登録漏れ」ではなく、他の2軸（roadFilterAxes.tsのhighway表示分類・
# classify_bicycle_infrastructureの自転車インフラ分類）ではこれらのhighway値が評価対象に
# なりうるため、3軸のカバレッジは意図的に揃っていない（改善計画T62）。値付けは
# LTSの目安として根拠が弱く、本格チューニングはP2据え置き（不確かな推測でNone以外を
# 返さない、という本ファイル冒頭の方針を優先した）。
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


# 分離自転車道・自転車レーンを「専用インフラ」とみなす分類（bicycle_infra_score算出用）。
DEDICATED_BICYCLE_INFRA_CLASSES: frozenset[str] = frozenset({"separated", "lane"})


def is_dedicated_bicycle_infra(bicycle_infra: BicycleInfraClass | None) -> bool | None:
    """自転車インフラ分類が「専用インフラ（分離・レーン）」かどうかを3値で返す
    （不明はNone。road.py: classify_osm_surfaceの3値判定と同じ考え方）。

    `classify_bicycle_infrastructure`は判定不能（highway等の入力が無い）な場合Noneではなく
    文字列`"unknown"`を返す仕様のため、ここでも明示的にNone扱いする。これを怠ると、
    ORSエンジンでway_tagsの空間マッチに失敗した区間（データ欠損）が「専用インフラではないと
    確認された区間」としてdistance_weighted_bicycle_infra_scoreの分母に混入してしまう。
    """
    if bicycle_infra is None or bicycle_infra == "unknown":
        return None
    return bicycle_infra in DEDICATED_BICYCLE_INFRA_CLASSES


def distance_weighted_bicycle_infra_score(pairs: list[tuple[float, bool | None]]) -> float | None:
    """(区間の距離, 専用の自転車インフラか)のペア列から、距離加重の専用インフラ率(%)を
    算出する（domain/road.py: distance_weighted_road_scoreと同じ集約方法。不明区間は
    分母から除外し、判定できる区間が1つも無ければNone）。"""
    known = sum(distance for distance, is_dedicated in pairs if is_dedicated is not None)
    if known <= 0:
        return None
    dedicated = sum(distance for distance, is_dedicated in pairs if is_dedicated)
    return round(dedicated / known * 100, 1)


def traffic_stress_level(highway: str | None, tags: dict[str, str], is_designated: bool = False) -> int | None:
    """交通ストレス（LTS: Level of Traffic Stress風の1-4段階。「交通量」ではなく
    「推定交通ストレス」、計画書§2.4）。基本値はhighwayのみで決まり、未知のhighwayは
    None（評価しない）。補正はタグが実際にある場合のみ適用する（unknownは補正しない）。

    cycleway系タグによる補正は`classify_bicycle_infrastructure`と同じ入力を別目的で
    解釈しているため、両者は完全には独立ではない（同関数のdocstring参照、改善計画T62）。

    `is_designated`はKSJ N10（緊急輸送道路）・N12（重要物流道路）への該当（外部静的
    データソース T51、`domain/designation.py: TRAFFIC_STRESS_DESIGNATION_KINDS`）。
    大型車交通の代理指標として+1する（既存クランプ内、motor_vehicle=noの固定1より後段）。
    road_graph_repository.pyのMVT生成CASE式と1:1対応させる（test_road_graph_repository.pyの
    整合性テストで担保）。
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

    if is_designated:
        level += 1

    return max(1, min(4, level))
