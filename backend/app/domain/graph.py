from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.domain.strict_model import StrictModel


class Node(StrictModel):
    """道路ネットワーク上の接続点（交差点・分岐点・行き止まり等）。

    シェイプポイント（Way形状を構成するだけで接続点ではない中間点）はNode化せず、
    DirectedEdge.geometryの一部として保持する（仕様書7章）。
    """

    node_id: str
    latitude: float
    longitude: float
    osm_node_id: int | None = None
    # そのノードに信号があるか・集まる道の最大階級（road_nodesの事前集計列、
    # precompute_road_node_intersections.py）。ターンの費用が「信号が無いのに上位の道を
    # 渡る」場合だけ待ちを足すために読む。既定値は未集計のDBから読んだときの値と同じで、
    # どちらもターンの費用がこの列の導入前と同じ結果になる側へ倒してある。
    has_traffic_signals: bool = False
    max_highway_rank: int = 0


class DirectedEdge(StrictModel):
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
    #: 親の道の中で何番目の区間か。DBは向きを持たない1行で、この2つと`forward`で引く
    #: （`edge_id`は表示・辞書の鍵としてだけ使い、解析しない）。
    segment_index: int | None = None
    #: 区間のジオメトリと同じ向きに走るか。
    forward: bool = True
    highway: str | None = None  # OSMのhighwayタグ（生値。分類・評価はRoad Attribute側の責務）
    # from_node→to_node方向の方位角（度、北=0、時計回り、domain/geo.py:
    # bearing_betweenと同じ定義）。build_road_graphがgeometryから算出して
    # 保持する。探索フェーズの風評価（DYNAMIC_MATERIAL_EVALUATORS）がgeometryを取得・decodeせずに
    # この値だけで完結できるようにするための事前計算値（そのため既定値Noneを許容しつつ、
    # build_road_graph経由の生成では必ず値を持つ）。
    bearing_deg: float | None = None


class RoadGraph(StrictModel):
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
    has_traffic_signals: bool
    max_highway_rank: int


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
    segment_index: int | None
    forward: bool
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
    # そのノードに信号があるか・集まる道の最大階級（road_nodesの事前集計列、
    # precompute_road_node_intersections.py）。ターンの費用が「信号が無いのに上位の道を
    # 渡る」場合だけ待ちを足すために読む。既定値は未集計のDBから読んだときの値と同じで、
    # どちらもターンの費用がこの列の導入前と同じ結果になる側へ倒してある。
    has_traffic_signals: bool = False
    max_highway_rank: int = 0


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
    segment_index: int | None = None
    forward: bool = True
    highway: str | None = None
    bearing_deg: float | None = None


def _rebuild_lean_road_graph(
    graph_version: str,
    node_rows: list[tuple[str, float, float, int | None, bool, int]],
    edge_rows: list[tuple[str, str, str, float, int | None, int | None, bool, str | None, float | None]],
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
        node_id: LeanNode(node_id=node_id, latitude=lat, longitude=lon, osm_node_id=osm_node_id,
                          has_traffic_signals=has_signal, max_highway_rank=max_rank)
        for node_id, lat, lon, osm_node_id, has_signal, max_rank in node_rows
    }
    edges = {
        edge_id: LeanEdge(
            edge_id=edge_id, from_node_id=from_id, to_node_id=to_id, geometry=[],
            distance_m=distance_m, osm_way_id=osm_way_id, segment_index=segment_index,
            forward=forward, highway=highway, bearing_deg=bearing_deg,
        )
        for (edge_id, from_id, to_id, distance_m, osm_way_id, segment_index, forward,
             highway, bearing_deg) in edge_rows
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
        node_rows = [(n.node_id, n.latitude, n.longitude, n.osm_node_id,
                      n.has_traffic_signals, n.max_highway_rank) for n in self.nodes.values()]
        edge_rows = [
            (e.edge_id, e.from_node_id, e.to_node_id, e.distance_m, e.osm_way_id,
             e.segment_index, e.forward, e.highway, e.bearing_deg)
            for e in self.edges.values()
        ]
        return (_rebuild_lean_road_graph, (self.graph_version, node_rows, edge_rows))
