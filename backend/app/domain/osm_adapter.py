"""OSM Adapter / Importer（仕様書2・21・47章）。

OSM（Overpass由来のWay/Nodeデータ）の語彙（`tags`辞書、`oneway`タグの値等）を解釈し、
データソースに依存しない`WaySpec`（domain/graph.py）へ変換する。この変換をここに
閉じ込めることで、`build_road_graph`（domain/graph.py）はOSMのタグ形式を一切知らずに
すむ。将来Overpassのクエリ形式が変わったり、OSM以外のデータソース（PBF一括抽出等）に
切り替えたりしても、影響範囲はこのファイル（と対応するAdapter）に限定される。
"""

from pydantic import BaseModel

from app.domain.graph import WaySpec
from app.domain.traffic import classify_stop_poi, classify_supply_poi

# OSMのoneway値のうち「逆方向への通行不可」を意味するもの。
ONEWAY_FORWARD_ONLY = {"yes", "true", "1"}
ONEWAY_BACKWARD_ONLY = {"-1", "reverse"}


def _resolve_direction(tags: dict) -> str:
    """`oneway`と`oneway:bicycle`から通行方向を決定する。

    `oneway:bicycle`は「自転車に限り一方通行規制の対象外（またはbicycle独自の一方通行）」
    という意味の例外タグで、値がある場合は`oneway`本体より優先する（現実のOSM上でも
    contraflow cycling＝逆走可の代表的な表現。例: `oneway=yes` + `oneway:bicycle=no`は
    「車は一方通行だが自転車は両方向通行可」）。`oneway:bicycle`が無い、または
    forward/backward/no のいずれにも解決できない値の場合は`oneway`本体にフォールバックする。
    """
    oneway_bicycle = str(tags.get("oneway:bicycle", "")).strip().lower()
    if oneway_bicycle in ONEWAY_BACKWARD_ONLY:
        return "backward"
    if oneway_bicycle in ONEWAY_FORWARD_ONLY:
        return "forward"
    if oneway_bicycle == "no":
        return "both"

    oneway = str(tags.get("oneway", "")).strip().lower()
    if oneway in ONEWAY_BACKWARD_ONLY:
        return "backward"
    if oneway in ONEWAY_FORWARD_ONLY:
        return "forward"
    return "both"


# 静的道路属性（docs/static-road-attributes-plan.md P0）で保持するタグの許可リスト。
# highway/surface/onewayは既存の専用フィールドで扱うためここには含めない。
# GOOD/BAD_OSM_SURFACE_TAGS（domain/road.py）と同じ「正準1箇所」の考え方で、
# ここに無いタグはWaySpec.tagsへ残らない（生データ汚染を避ける、計画書§2.4）。
# 容量実測（2026-08-15、static-attributes-capacity-estimate）: 本番規模で約9MB、
# 誤差程度で安全。
ALLOWED_WAY_TAGS = frozenset(
    {
        "smoothness",
        "lanes",
        "maxspeed",
        "width",
        "cycleway",
        "cycleway:left",
        "cycleway:right",
        "cycleway:both",
        "bicycle",
        "motor_vehicle",
        "access",
        # 方向自体は_resolve_directionでWaySpec.directionへ解決済みだが、生タグも
        # 表示・デバッグ用途に引き続き保持する（他の解釈済みタグと同じ扱い）。
        "oneway:bicycle",
        "tunnel",
        "bridge",
        "name",
        "ref",
        "tracktype",
        "shoulder",
        # shared_pedestrian_waysルールで取り込む自転車歩行者道の歩車分離有無。取込コストは
        # ゼロ（既存のtags jsonbへ相乗り）。自転車インフラ分類（domain/recipe.py:
        # bicycle_infra_flags）への反映は未実施（採用可否の判断は完了、実装は別タスクで
        # 検討、docs/static-road-attributes-plan.md §2.5参照）。
        "segregated",
        # 街灯の有無。関東全域で全体1.1%・幹線道路4.8%と既採用tagの水準を上回るため保持する
        # （詳細はstatic-road-attributes-plan.md §2.5参照）。取込コストはsegregatedと
        # 同じくゼロ（既存way向けtags jsonbへ相乗り、新規node取込は不要）。評価軸・表示への
        # 反映は別タスクで検討（本タグは保持のみ）。
        "lit",
    }
)


def _filter_allowed_tags(tags: dict) -> dict[str, str]:
    """許可リストに含まれるタグだけを、値を文字列化して残す（未設定タグは省略。
    根拠のない推測はせず、無い場合はキー自体を持たせない＝raw=NULL相当）。"""
    return {key: str(value) for key, value in tags.items() if key in ALLOWED_WAY_TAGS and value is not None}


def osm_way_to_way_spec(raw_way: dict) -> WaySpec | None:
    """OSM生データ由来のway要素（`{"id": int, "tags": dict, "nodes": list[int]}`、
    PBF取込バッチ・テストフィクスチャ等が共通で使う形）を`WaySpec`へ変換する。

    ノードが2未満のwayは経路探索上の区間になり得ないためNoneを返す。
    """
    node_ids = raw_way.get("nodes") or []
    if len(node_ids) < 2:
        return None

    tags = raw_way.get("tags", {})
    direction = _resolve_direction(tags)

    return WaySpec(
        osm_way_id=raw_way.get("id"),
        node_ids=node_ids,
        highway=tags.get("highway"),
        surface=tags.get("surface"),
        tags=_filter_allowed_tags(tags),
        direction=direction,
    )


def osm_ways_to_way_specs(raw_ways: list[dict]) -> list[WaySpec]:
    specs = (osm_way_to_way_spec(way) for way in raw_ways)
    return [spec for spec in specs if spec is not None]


# 信号・横断歩道・一時停止・踏切・補給休憩ポイント(T101)のnode取込で保持するタグの
# 許可リスト（静的道路属性P1）。highway/railway/shop/amenityは分類根拠そのものだが、
# 値をそのまま保持しておくと将来の分類精緻化（例: crossing=uncontrolled/traffic_signalsの
# 区別）を再取込無しに遡って行える（ALLOWED_WAY_TAGSと同じ「生タグ保持」の考え方）。
ALLOWED_NODE_TAGS = frozenset({"highway", "railway", "crossing", "shop", "amenity"})


class POISpec(BaseModel):
    """信号・横断歩道・一時停止・踏切・補給休憩ポイント(T101)等、道路脇のnodeの取込単位
    （静的道路属性P1）。

    WaySpecと対称に、データソースに依存しない契約（PBF取込・将来のOverpass双方が
    ここへ変換してから渡す想定）。build_road_graphの入力ではないため、graph.pyではなく
    ここに置く。
    """

    osm_node_id: int
    kind: str
    tags: dict[str, str] = {}
    latitude: float
    longitude: float


def osm_node_to_poi_spec(raw_node: dict) -> POISpec | None:
    """`{"id": int, "tags": dict, "lat": float, "lon": float}`形式のnode要素をPOISpecへ
    変換する。停止要因（信号・横断歩道・一時停止・踏切）・補給休憩ポイント(T101:
    コンビニ・自販機・トイレ・給水・駐輪場)のいずれにも該当しないnode（大多数の形状点）は
    Noneを返す（osm_raw_poisは分類できたnodeだけを保持する、road_graph_models.py:
    OsmRawPoiRow参照）。2つの分類はタグ名が独立している（highway/railway vs shop/amenity）
    ため優先順位を考慮せず、いずれか一致した方をそのまま使う。
    """
    tags = raw_node.get("tags", {})
    kind = classify_stop_poi(tags) or classify_supply_poi(tags)
    if kind is None:
        return None

    return POISpec(
        osm_node_id=raw_node["id"],
        kind=kind,
        tags=_filter_allowed_node_tags(tags),
        latitude=raw_node["lat"],
        longitude=raw_node["lon"],
    )


def _filter_allowed_node_tags(tags: dict) -> dict[str, str]:
    return {key: str(value) for key, value in tags.items() if key in ALLOWED_NODE_TAGS and value is not None}
