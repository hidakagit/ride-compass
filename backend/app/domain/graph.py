from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class LeanNode:
    """道路ネットワーク上の接続点（交差点・分岐点・行き止まり等）。

    形状点（Wayの形を作るだけで接続点ではない中間点）はここに現れず、`LeanEdge.geometry`
    の一部として持つ。

    Pydanticではなく素のdataclassにするのは、探索用グラフの構築でノード数万件ぶんの
    オブジェクトを作るため——バリデーションを飛ばしても簿記のコストが残る。
    """

    node_id: str
    latitude: float
    longitude: float
    osm_node_id: int | None = None
    # そのノードに信号があるか・集まる道の最大階級（`node_materials`の列）。ターンの費用が
    # 「信号が無いのに上位の道を渡る」場合だけ待ちを足すために読む。既定値は未集計のDBから
    # 読んだときの値と同じで、どちらも待ちを足さない側へ倒してある。
    has_traffic_signals: bool = False
    max_highway_rank: int = 0


@dataclass(frozen=True, slots=True)
class LeanEdge:
    """経路探索の基本単位となる、方向を持つ道路区間。A→BとB→Aは別の枝として扱う。

    `geometry`は**探索フェーズでは空リスト**（探索は形を見ない）。表示のために形が要る
    区間だけ`get_edges_with_geometry`が取り直して埋める。読む側はどちらが来ても同じ
    属性名で読めるため、区別しない。

    路面・標高・交通量といった評価の材料はここへ持たせない（道路網そのものの表現に限る）。
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
    """`LeanNode`/`LeanEdge`からなる道路ネットワーク。

    `graph_version`は生成時刻ベースの単純な識別子で、版管理の機構は持たない。
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
