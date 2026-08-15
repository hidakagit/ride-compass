from collections import Counter
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from app.domain.geo import haversine_distance_km
from app.domain.route import Coordinates


class Node(BaseModel):
    """道路ネットワーク上の接続点（交差点・分岐点・行き止まり等）。

    シェイプポイント（Way形状を構成するだけで接続点ではない中間点）はNode化せず、
    DirectedEdge.geometryの一部として保持する（仕様書7章）。
    """

    node_id: str
    latitude: float
    longitude: float
    osm_node_id: int | None = None


class DirectedEdge(BaseModel):
    """経路探索の基本単位となる、方向を持つ道路区間（仕様書8-10章）。

    A→BとB→Aは別のEdgeとして扱う。road_edgesの責務は道路ネットワークそのものの表現に
    限定し、標高・路面・交通量等のRoad Attributeはここへ持たせない（仕様書10章）。
    """

    edge_id: str
    from_node_id: str
    to_node_id: str
    geometry: list[list[float]]  # [[latitude, longitude], ...] from_node→to_nodeの向き
    distance_m: float
    osm_way_id: int | None = None
    highway: str | None = None  # OSMのhighwayタグ（生値。分類・評価はRoad Attribute側の責務）


class RoadGraph(BaseModel):
    """Node/DirectedEdgeからなる道路ネットワーク（仕様書6章）。

    graph_versionは過剰なバージョン管理機構を導入せず、生成時刻ベースの単純な識別子に
    留める（仕様書12章：「将来追加可能な構造を優先する」）。
    """

    graph_version: str
    nodes: dict[str, Node]
    edges: dict[str, DirectedEdge]


class WaySpec(BaseModel):
    """Road Graph構築（build_road_graph）への入力単位。

    データソースに依存しない契約であり、OSM Adapter（domain/osm_adapter.py）等、
    データソースごとのAdapterがこの形へ変換してから渡す（仕様書47章の
    「OSM Adapter / Importer → Road Graph」の境界）。build_road_graph自身は
    タグの生値（OSMのoneway文字列等）を一切解釈しない。将来Overpass以外の
    データソース（PBF一括抽出等）に切り替えても、Adapterを差し替えるだけで
    build_road_graphは無変更で使える。
    """

    osm_way_id: int | None = None
    node_ids: list[int]
    highway: str | None = None
    surface: str | None = None  # OSMのsurfaceタグ生値。DirectedEdgeへは持たせず、Road Attribute
    # 生成側（domain/attributes.py）がosm_way_id経由で参照する（仕様書13章：Edge本体と
    # 属性データの分離）。
    # 静的道路属性の許可リストタグ（docs/static-road-attributes-plan.md P0、
    # osm_adapter.py: ALLOWED_WAY_TAGS）。highway/surface同様、build_road_graphは
    # 解釈しない（DirectedEdgeへは持たせない）。表示（MVT）・将来の評価拡張の
    # 入力として、osm_way_id経由で別途参照する想定。
    tags: dict[str, str] = {}
    direction: Literal["forward", "backward", "both"] = "both"


def _new_graph_version() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _way_length_m(coordinates: list[tuple[float, float]]) -> float:
    total_km = 0.0
    for (lat1, lon1), (lat2, lon2) in zip(coordinates, coordinates[1:]):
        total_km += haversine_distance_km(
            Coordinates(latitude=lat1, longitude=lon1), Coordinates(latitude=lat2, longitude=lon2)
        )
    return total_km * 1000


def _split_points(node_ids: list[int], split_nodes: set[int]) -> list[list[int]]:
    """Wayのノード列を、split_nodes（交差点・分岐点・端点）で区切って部分列に分割する。

    各部分列は先頭・末尾がsplit_nodesに属し、間には形状点（split_nodesに属さないノード）
    を含みうる（仕様書9章の分割ルール）。
    """
    if len(node_ids) < 2:
        return []

    segments: list[list[int]] = []
    current = [node_ids[0]]
    for node_id in node_ids[1:]:
        current.append(node_id)
        if node_id in split_nodes:
            if len(current) >= 2:
                segments.append(current)
            current = [node_id]
    return segments


def build_road_graph(
    ways: list[WaySpec],
    nodes: dict[int, tuple[float, float]],
    graph_version: str | None = None,
) -> RoadGraph:
    """WaySpecの列とノード座標から、交差点で分割したDirected Edgeを持つRoadGraphを構築する。

    nodes: osm_node_id（またはデータソース側のノードID） -> (latitude, longitude)

    内部ID（node_id/edge_id）はosm_node_id/osm_way_idから決定論的に導出する（単純な連番では
    ない）。これにより、同じOSMデータに対しては何度ビルドしても同じ内部IDになり、永続化
    キャッシュ（PostGIS）上で同一の現実の交差点・道路区間として扱い続けられる（idempotentな
    upsertが成立する）。ただし内部IDそのものはOSM IDの生値ではなく別表現（`osm-node-<id>`等）
    にしており、osm_way_idを永続的な道路の識別子としてそのまま扱ってはいない点は維持する
    （仕様書11章）。
    """
    # 分割地点＝Wayの端点、または複数のWayから参照される（＝交差点の）ノード、
    # または同一Way内に複数回登場するノード（仕様書9章）。
    node_occurrences: Counter[int] = Counter()
    for way in ways:
        node_occurrences.update(way.node_ids)

    split_node_ids: set[int] = set()
    for way in ways:
        way_nodes = way.node_ids
        if not way_nodes:
            continue
        split_node_ids.add(way_nodes[0])
        split_node_ids.add(way_nodes[-1])
        for node_id in way_nodes:
            if node_occurrences[node_id] >= 2:
                split_node_ids.add(node_id)

    graph_nodes: dict[str, Node] = {}
    osm_to_internal_node_id: dict[int, str] = {}

    def _get_or_create_node(osm_node_id: int) -> str | None:
        if osm_node_id in osm_to_internal_node_id:
            return osm_to_internal_node_id[osm_node_id]
        coordinates = nodes.get(osm_node_id)
        if coordinates is None:
            return None
        internal_id = f"osm-node-{osm_node_id}"
        lat, lon = coordinates
        graph_nodes[internal_id] = Node(node_id=internal_id, latitude=lat, longitude=lon, osm_node_id=osm_node_id)
        osm_to_internal_node_id[osm_node_id] = internal_id
        return internal_id

    edges: dict[str, DirectedEdge] = {}
    anonymous_way_counter = 0

    for way in ways:
        # way_keyはedge_idの決定論的な導出に使う。osm_way_idが無いWaySpec（OSM以外の
        # 将来のデータソースを想定）は連番にフォールバックするが、その場合は複数回の
        # ビルド間でIDが安定しない（永続化キャッシュとの整合はosm_way_idがある前提）。
        if way.osm_way_id is not None:
            way_key = str(way.osm_way_id)
        else:
            anonymous_way_counter += 1
            way_key = f"anon{anonymous_way_counter}"

        for segment_index, segment_node_ids in enumerate(_split_points(way.node_ids, split_node_ids)):
            coordinates = [nodes[n] for n in segment_node_ids if n in nodes]
            if len(coordinates) < 2:
                continue

            from_internal = _get_or_create_node(segment_node_ids[0])
            to_internal = _get_or_create_node(segment_node_ids[-1])
            if from_internal is None or to_internal is None:
                continue

            distance_m = _way_length_m(coordinates)
            geometry_forward = [[lat, lon] for lat, lon in coordinates]

            if way.direction != "backward":
                edge_id = f"way-{way_key}-seg{segment_index}-fwd"
                edges[edge_id] = DirectedEdge(
                    edge_id=edge_id,
                    from_node_id=from_internal,
                    to_node_id=to_internal,
                    geometry=geometry_forward,
                    distance_m=round(distance_m, 1),
                    osm_way_id=way.osm_way_id,
                    highway=way.highway,
                )

            if way.direction != "forward":
                edge_id = f"way-{way_key}-seg{segment_index}-bwd"
                edges[edge_id] = DirectedEdge(
                    edge_id=edge_id,
                    from_node_id=to_internal,
                    to_node_id=from_internal,
                    geometry=list(reversed(geometry_forward)),
                    distance_m=round(distance_m, 1),
                    osm_way_id=way.osm_way_id,
                    highway=way.highway,
                )

    return RoadGraph(graph_version=graph_version or _new_graph_version(), nodes=graph_nodes, edges=edges)
