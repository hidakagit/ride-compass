"""OSM Adapter / Importer（仕様書2・21・47章）。

OSM（Overpass由来のWay/Nodeデータ）の語彙（`tags`辞書、`oneway`タグの値等）を解釈し、
データソースに依存しない`WaySpec`（domain/graph.py）へ変換する。この変換をここに
閉じ込めることで、`build_road_graph`（domain/graph.py）はOSMのタグ形式を一切知らずに
すむ。将来Overpassのクエリ形式が変わったり、OSM以外のデータソース（PBF一括抽出等）に
切り替えたりしても、影響範囲はこのファイル（と対応するAdapter）に限定される。
"""

from pydantic import BaseModel

from app.domain.graph import WaySpec
from app.domain.traffic import classify_stop_poi

# OSMのoneway値のうち「逆方向への通行不可」を意味するもの。bicycle固有の例外
# （oneway:bicycle=no等）はここでは扱わない（Evaluation Engine側の関心事。
# Road Graphは基本的な通行方向のみを保持する、仕様書10章の方針）。
ONEWAY_FORWARD_ONLY = {"yes", "true", "1"}
ONEWAY_BACKWARD_ONLY = {"-1", "reverse"}

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
        "oneway:bicycle",
        "tunnel",
        "bridge",
        "name",
        "ref",
        "tracktype",
        "shoulder",
    }
)


def _filter_allowed_tags(tags: dict) -> dict[str, str]:
    """許可リストに含まれるタグだけを、値を文字列化して残す（未設定タグは省略。
    根拠のない推測はせず、無い場合はキー自体を持たせない＝raw=NULL相当）。"""
    return {key: str(value) for key, value in tags.items() if key in ALLOWED_WAY_TAGS and value is not None}


def osm_way_to_way_spec(raw_way: dict) -> WaySpec | None:
    """OverpassClient.get_ways_and_nodesが返すway要素
    （`{"id": int, "tags": dict, "nodes": list[int]}`）を`WaySpec`へ変換する。

    ノードが2未満のwayは経路探索上の区間になり得ないためNoneを返す。
    """
    node_ids = raw_way.get("nodes") or []
    if len(node_ids) < 2:
        return None

    tags = raw_way.get("tags", {})
    oneway = str(tags.get("oneway", "")).strip().lower()
    if oneway in ONEWAY_BACKWARD_ONLY:
        direction = "backward"
    elif oneway in ONEWAY_FORWARD_ONLY:
        direction = "forward"
    else:
        direction = "both"

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


# 信号・横断歩道・一時停止・踏切のnode取込で保持するタグの許可リスト（静的道路属性P1）。
# highway/railwayはclassify_stop_poiの分類根拠そのものだが、値をそのまま保持しておくと
# 将来の分類精緻化（例: crossing=uncontrolled/traffic_signalsの区別）を再取込無しに
# 遡って行える（ALLOWED_WAY_TAGSと同じ「生タグ保持」の考え方）。
ALLOWED_NODE_TAGS = frozenset({"highway", "railway", "crossing"})


class POISpec(BaseModel):
    """信号・横断歩道・一時停止・踏切等、停止・減速要因になるnodeの取込単位（静的道路属性P1）。

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
    変換する。信号・横断歩道・一時停止・踏切のいずれにも該当しないnode（大多数の
    形状点）はNoneを返す（osm_raw_poisは分類できたnodeだけを保持する、road_graph_models.py:
    OsmRawPoiRow参照）。
    """
    tags = raw_node.get("tags", {})
    kind = classify_stop_poi(tags)
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


def osm_nodes_to_poi_specs(raw_nodes: list[dict]) -> list[POISpec]:
    specs = (osm_node_to_poi_spec(node) for node in raw_nodes)
    return [spec for spec in specs if spec is not None]
