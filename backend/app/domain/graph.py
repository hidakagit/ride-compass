from dataclasses import dataclass, fields
from operator import attrgetter

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


# pickleの列。フィールドの宣言から導く——手で並べると、フィールドを1つ足したときに列を
# 足し忘れても、復元側が既定値で埋めてしまい値だけが黙って消える。`geometry`は載せない
# （pickleするのはタイルキャッシュのグラフに限られ、そこでは常に空リスト）。
_NODE_COLUMNS = tuple(f.name for f in fields(LeanNode))
_EDGE_COLUMNS = tuple(f.name for f in fields(LeanEdge) if f.name != "geometry")
_EDGE_GEOMETRY_POSITION = [f.name for f in fields(LeanEdge)].index("geometry")
_node_row = attrgetter(*_NODE_COLUMNS)
_edge_row = attrgetter(*_EDGE_COLUMNS)


def _rebuild_lean_road_graph(
    graph_version: str,
    node_rows: list[tuple],
    edge_rows: list[tuple],
) -> "LeanRoadGraph":
    """`LeanRoadGraph.__reduce__`が指すpickle復元関数（対になる分解側のdocstring参照）。

    列数が合わない行は送出する。足りない列のほとんどは既定値を持つため、そのまま
    組み立てると値の欠けたグラフが黙って出来上がる。
    """
    nodes = {}
    for row in node_rows:
        if len(row) != len(_NODE_COLUMNS):
            raise ValueError(f"pickled node row has {len(row)} columns, expected {_NODE_COLUMNS}")
        node = LeanNode(*row)
        nodes[node.node_id] = node
    edges = {}
    for row in edge_rows:
        if len(row) != len(_EDGE_COLUMNS):
            raise ValueError(f"pickled edge row has {len(row)} columns, expected {_EDGE_COLUMNS}")
        edge = LeanEdge(*(*row[:_EDGE_GEOMETRY_POSITION], [], *row[_EDGE_GEOMETRY_POSITION:]))
        edges[edge.edge_id] = edge
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
        `_rebuild_lean_road_graph`がコンストラクタ呼び出しで行う。

        デフォルトのpickle復元は`nodes`/`edges`辞書の値（いずれもslotted frozen dataclass）を
        1個ずつ`__setstate__`経由で再構築するため、Edge数万〜数十万件規模のタイルでは
        このオブジェクト単位の復元コストが支配的になる。

        pickle化されるのはタイルキャッシュ経路のグラフだけで、そこでは`geometry`が常に
        空リストのため列に持たせず、復元時に固定で補う。
        """
        node_rows = [_node_row(node) for node in self.nodes.values()]
        edge_rows = [_edge_row(edge) for edge in self.edges.values()]
        return (_rebuild_lean_road_graph, (self.graph_version, node_rows, edge_rows))
