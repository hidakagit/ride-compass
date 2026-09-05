from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from app.domain.geo import LatLonPoint, bearing_between, haversine_distance_km


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
    # from_node→to_node方向の方位角（度、北=0、時計回り、domain/geo.py:
    # bearing_betweenと同じ定義）。build_road_graphがgeometryから算出して
    # 保持する。探索フェーズの風評価（DYNAMIC_MATERIAL_EVALUATORS）がgeometryを取得・decodeせずに
    # この値だけで完結できるようにするための事前計算値（そのため既定値Noneを許容しつつ、
    # build_road_graph経由の生成では必ず値を持つ）。
    bearing_deg: float | None = None


class RoadGraph(BaseModel):
    """Node/DirectedEdgeからなる道路ネットワーク（仕様書6章）。

    graph_versionは過剰なバージョン管理機構を導入せず、生成時刻ベースの単純な識別子に
    留める（仕様書12章：「将来追加可能な構造を優先する」）。
    """

    graph_version: str
    nodes: dict[str, Node]
    edges: dict[str, DirectedEdge]


@runtime_checkable
class NodeLike(Protocol):
    """探索フェーズ（domain/routing.py・domain/evaluation.py）が実際に読む`Node`の
    フィールドのみを表す構造的型。`Node`（Pydantic）と`LeanNode`
    （dataclass、探索専用の軽量実装）の両方がこのProtocolを満たす。"""

    node_id: str
    latitude: float
    longitude: float
    osm_node_id: int | None


@runtime_checkable
class EdgeLike(Protocol):
    """探索フェーズが実際に読む`DirectedEdge`のフィールドのみを表す構造的型。
    `DirectedEdge`（Pydantic、表示・保存用）と`LeanEdge`
    （dataclass、探索専用の軽量実装）の両方がこのProtocolを満たす。

    `RoadGraphEngine.trace_loop`（`hydrated.get(edge_id) or context.graph.edges[edge_id]`、
    表示用に取り直したフルEdgeと探索グラフのlean Edgeを同じリストへ混在させる）が
    どちらの実体型が来ても同じ属性名で読める必要があるため、フィールド構成は
    `DirectedEdge`と完全に一致させる（`geometry`はlean側では常に空リストの
    プレースホルダ、`osm_way_id`は探索フェーズでは未使用だが表示用途との
    フィールド互換のため保持する）。
    """

    edge_id: str
    from_node_id: str
    to_node_id: str
    geometry: list[list[float]]
    distance_m: float
    osm_way_id: int | None
    highway: str | None
    bearing_deg: float | None


@runtime_checkable
class RoadGraphLike(Protocol):
    """`RoadGraph`（Pydantic、表示・保存用）と`LeanRoadGraph`（dataclass、探索専用の
    軽量実装）の両方が満たす構造的型。探索フェーズ
    （`RoadGraphEngine`・`domain/routing.py`・`domain/evaluation.py`）はどちらの実体型を
    渡されても同じ属性アクセスで動作する。"""

    graph_version: str
    nodes: dict[str, NodeLike]
    edges: dict[str, EdgeLike]


@dataclass(frozen=True, slots=True)
class LeanNode:
    """`Node`の探索専用軽量実装。フィールド構成は`Node`と完全に一致させる
    （`NodeLike`Protocol参照）。Pydantic（`model_construct`でもバリデーション機構自体の
    簿記コストは残る）ではなく素のdataclassにすることで、探索用グラフ構築時の
    オブジェクト構築コストを削減する（dev DB、68,760件でNode.model_construct
    2.125秒→dataclass構築）。
    """

    node_id: str
    latitude: float
    longitude: float
    osm_node_id: int | None = None


@dataclass(frozen=True, slots=True)
class LeanEdge:
    """`DirectedEdge`の探索専用軽量実装。フィールド構成は
    `DirectedEdge`と完全に一致させる（`EdgeLike`Protocol参照、
    `RoadGraphEngine.trace_loop`がlean/フル両方のEdgeを同じリストへ混在させるため）。
    `geometry`は常に空リストのプレースホルダ（探索フェーズはgeometryを参照しない設計、
    `_topology_rows_to_road_graph`参照）。dev DBで171,461件を
    DirectedEdge.model_constructすると8.938秒かかるのに対し、dataclass構築なら短縮する。
    """

    edge_id: str
    from_node_id: str
    to_node_id: str
    geometry: list[list[float]]
    distance_m: float
    osm_way_id: int | None = None
    highway: str | None = None
    bearing_deg: float | None = None


def _rebuild_lean_road_graph(
    graph_version: str,
    node_rows: list[tuple[str, float, float, int | None]],
    edge_rows: list[tuple[str, str, str, float, int | None, str | None, float | None]],
) -> "LeanRoadGraph":
    """`LeanRoadGraph.__reduce__`が指すpickle復元関数。列（生のtuple列）から
    `LeanNode`/`LeanEdge`をコンストラクタ呼び出しで作り直す——デフォルトのpickle復元
    （slotted dataclassごとに`__setstate__`/`dataclasses.fields()`を呼ぶ機構、Edge1本
    あたり約36µsかかる）を経由しない。`geometry`は`_topology_rows_to_road_graph`が生成する
    タイルキャッシュ経路（`GraphService._get_or_build_tile_materials`が
    `graph_material_cache`経由でpickle化する対象）に限り常に空リストのため、列として
    持たせず復元時に固定で補う。
    """
    nodes = {
        node_id: LeanNode(node_id=node_id, latitude=lat, longitude=lon, osm_node_id=osm_node_id)
        for node_id, lat, lon, osm_node_id in node_rows
    }
    edges = {
        edge_id: LeanEdge(
            edge_id=edge_id, from_node_id=from_id, to_node_id=to_id, geometry=[],
            distance_m=distance_m, osm_way_id=osm_way_id, highway=highway, bearing_deg=bearing_deg,
        )
        for edge_id, from_id, to_id, distance_m, osm_way_id, highway, bearing_deg in edge_rows
    }
    return LeanRoadGraph(graph_version=graph_version, nodes=nodes, edges=edges)


@dataclass(frozen=True, slots=True)
class LeanRoadGraph:
    """`RoadGraph`の探索専用軽量実装。`graph_version`・`nodes`・`edges`の
    フィールド構成は`RoadGraph`と一致させ、`RoadGraphLike`Protocolを満たす。
    `get_graph_topology_in_bbox`（road_graph_repository.py）の戻り値として使う。
    """

    graph_version: str
    nodes: dict[str, LeanNode]
    edges: dict[str, LeanEdge]

    def __reduce__(self) -> tuple:
        """pickle時にNode/Edgeを列（tupleのリスト）へ分解し、復元は
        `_rebuild_lean_road_graph`が担う。デフォルトのpickle復元は`nodes`/`edges`辞書の値
        （`LeanNode`/`LeanEdge`、いずれもslotted frozen dataclass）を1個ずつ
        `__setstate__`経由で再構築するため、Edge数万〜数十万件規模のタイルでは
        このオブジェクト単位の復元コストが支配的になる（合成計測でグラフ部分は
        253ms→118ms/タイルへ短縮）。`geometry`は常に空リスト
        （`_topology_rows_to_road_graph`のタイルキャッシュ経路のみがpickle化対象、
        クラスdocstring参照）のため列に持たせない。
        """
        node_rows = [(n.node_id, n.latitude, n.longitude, n.osm_node_id) for n in self.nodes.values()]
        edge_rows = [
            (e.edge_id, e.from_node_id, e.to_node_id, e.distance_m, e.osm_way_id, e.highway, e.bearing_deg)
            for e in self.edges.values()
        ]
        return (_rebuild_lean_road_graph, (self.graph_version, node_rows, edge_rows))


@dataclass(frozen=True, slots=True)
class WaySpec:
    """Road Graph構築（build_road_graph）への入力単位。

    データソースに依存しない契約であり、OSM Adapter（domain/osm_adapter.py）等、
    データソースごとのAdapterがこの形へ変換してから渡す（仕様書47章の
    「OSM Adapter / Importer → Road Graph」の境界）。build_road_graph自身は
    タグの生値（OSMのoneway文字列等）を一切解釈しない。将来Overpass以外の
    データソース（PBF一括抽出等）に切り替えても、Adapterを差し替えるだけで
    build_road_graphは無変更で使える。

    Pydantic BaseModelではなく素のdataclass。`build_road_graph`が対象bbox＋近傍の
    全Way（都心規模で数万〜十数万件）ぶん構築するたびPydanticバリデーションのコストが
    かかるため、外部境界（API・DB行）からの変換専用の内部契約でPydantic固有機能
    （.model_dump()等）への依存が無いこの型はdataclassにする。
    """

    node_ids: list[int]
    osm_way_id: int | None = None
    highway: str | None = None
    surface: str | None = None  # OSMのsurfaceタグ生値。DirectedEdgeへは持たせず、Road Attribute
    # 生成側（domain/attributes.py）がosm_way_id経由で参照する（仕様書13章：Edge本体と
    # 属性データの分離）。
    # 静的道路属性の許可リストタグ（docs/static-road-attributes-plan.md P0、
    # osm_adapter.py: ALLOWED_WAY_TAGS）。highway/surface同様、build_road_graphは
    # 解釈しない（DirectedEdgeへは持たせない）。表示（MVT）・将来の評価拡張の
    # 入力として、osm_way_id経由で別途参照する想定。
    tags: dict[str, str] = field(default_factory=dict)
    direction: Literal["forward", "backward", "both"] = "both"


def _new_graph_version() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _way_length_m(coordinates: list[tuple[float, float]]) -> float:
    # LatLonPoint（NamedTuple、バリデーション無し）を使う——build_road_graphは
    # 都心規模で数万〜十数万Edgeぶんこのループを回すホットパスのため、
    # Pydantic Coordinatesの構築コストを避ける。
    total_km = 0.0
    for (lat1, lon1), (lat2, lon2) in zip(coordinates, coordinates[1:]):
        total_km += haversine_distance_km(LatLonPoint(lat1, lon1), LatLonPoint(lat2, lon2))
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
) -> LeanRoadGraph:
    """WaySpecの列とノード座標から、交差点で分割したDirected Edgeを持つRoadGraphを構築する。

    nodes: osm_node_id（またはデータソース側のノードID） -> (latitude, longitude)

    内部ID（node_id/edge_id）はosm_node_id/osm_way_idから決定論的に導出する（単純な連番では
    ない）。これにより、同じOSMデータに対しては何度ビルドしても同じ内部IDになり、永続化
    キャッシュ（PostGIS）上で同一の現実の交差点・道路区間として扱い続けられる（idempotentな
    upsertが成立する）。ただし内部IDそのものはOSM IDの生値ではなく別表現（`osm-node-<id>`等）
    にしており、osm_way_idを永続的な道路の識別子としてそのまま扱ってはいない点は維持する
    （仕様書11章）。

    戻り値は`RoadGraph`（Pydantic）ではなく`LeanRoadGraph`（dataclass）。
    対象bbox＋近傍の全Way（都心規模で数万〜十数万件）ぶんNode/DirectedEdgeを構築する
    このホットパスでPydanticバリデーションのコストがかかる（Node/DirectedEdgeの
    `model_construct`ですら171,461件で8.9秒超かかる）。呼び出し元
    （`GraphService.get_or_build_graph_with_attributes`）は元々`RoadGraphLike`
    Protocolで受けており、Pydantic固有機能への依存が無い。`LeanEdge.geometry`
    は「常に空」という規約（`get_graph_topology_in_bbox`側の規約）ではなく、ここでは実際の
    座標列をそのまま持たせる（地図表示（`lean=False`）でも実ジオメトリが必要なため）。
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

    graph_nodes: dict[str, LeanNode] = {}
    osm_to_internal_node_id: dict[int, str] = {}

    def _get_or_create_node(osm_node_id: int) -> str | None:
        if osm_node_id in osm_to_internal_node_id:
            return osm_to_internal_node_id[osm_node_id]
        coordinates = nodes.get(osm_node_id)
        if coordinates is None:
            return None
        internal_id = f"osm-node-{osm_node_id}"
        lat, lon = coordinates
        graph_nodes[internal_id] = LeanNode(
            node_id=internal_id, latitude=lat, longitude=lon, osm_node_id=osm_node_id
        )
        osm_to_internal_node_id[osm_node_id] = internal_id
        return internal_id

    edges: dict[str, LeanEdge] = {}
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
            # forward/backwardそれぞれの実際の進行方向で方位角を算出する
            # （+180度の単純反転ではなく、逆順の始点・終点から都度求める。短い区間では
            # ほぼ等価だが、地球の丸みを近似せず素直に正しい値を使う）。
            start_point = LatLonPoint(*coordinates[0])
            end_point = LatLonPoint(*coordinates[-1])
            bearing_forward = bearing_between(start_point, end_point)
            bearing_backward = bearing_between(end_point, start_point)

            if way.direction != "backward":
                edge_id = f"way-{way_key}-seg{segment_index}-fwd"
                edges[edge_id] = LeanEdge(
                    edge_id=edge_id,
                    from_node_id=from_internal,
                    to_node_id=to_internal,
                    geometry=geometry_forward,
                    distance_m=round(distance_m, 1),
                    osm_way_id=way.osm_way_id,
                    highway=way.highway,
                    bearing_deg=bearing_forward,
                )

            if way.direction != "forward":
                edge_id = f"way-{way_key}-seg{segment_index}-bwd"
                edges[edge_id] = LeanEdge(
                    edge_id=edge_id,
                    from_node_id=to_internal,
                    to_node_id=from_internal,
                    geometry=list(reversed(geometry_forward)),
                    distance_m=round(distance_m, 1),
                    osm_way_id=way.osm_way_id,
                    highway=way.highway,
                    bearing_deg=bearing_backward,
                )

    return LeanRoadGraph(graph_version=graph_version or _new_graph_version(), nodes=graph_nodes, edges=edges)
