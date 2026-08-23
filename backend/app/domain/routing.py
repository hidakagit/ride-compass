"""Route Engine（仕様書33-34章）。

Road Graph（domain/graph.py）とEdge Cost（domain/evaluation.py）を使って、2点間の
最小コスト経路を探索する。探索アルゴリズム自体は独自実装せず、標準的なグラフ
アルゴリズムライブラリのDijkstra実装をそのまま利用する（仕様書34章「探索アルゴリズムを
独断で変更しない」「独自の経路探索アルゴリズムの実装はしない」の趣旨を踏まえ、
新規性のある独自アルゴリズムは開発しない）。当初はNetworkX（Python実装）のみを
使っていたが、改善計画T220（T12 Stage 2）で大規模グラフ（数万エッジ）向けに
scipy.sparse.csgraph（C実装のDijkstra）も追加した。どちらも標準ライブラリの実装を
そのまま使うだけで、アルゴリズム自体の独自実装ではない点は変わらない。

Route Engineは、Costの中身（勾配がきつい、路面が悪い等）を一切知らない設計とする
（仕様書33章）。ここで扱うのはRoad Graphのトポロジーと、既に計算済みのEdge Costのみ。
"""

import math
from collections.abc import Collection
from dataclasses import dataclass

import networkx as nx
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra as scipy_dijkstra

from app.domain.evaluation import EdgeCostResult
from app.domain.geo import KM_PER_DEGREE_LATITUDE, haversine_distance_km
from app.domain.graph import RoadGraphLike
from app.domain.route import Coordinates


def build_networkx_graph(graph: RoadGraphLike, edge_costs: dict[str, EdgeCostResult]) -> nx.DiGraph:
    """RoadGraphとEdge CostからNetworkXの有向グラフを構築する。

    Hard Constraintで除外されたEdge（`allowed=False`）やCostが算出できなかったEdge
    （`cost=None`）はグラフに含めない（仕様書29章：探索対象から除外する）。
    """
    nx_graph = nx.DiGraph()
    for node_id in graph.nodes:
        nx_graph.add_node(node_id)

    for edge_id, edge in graph.edges.items():
        cost_result = edge_costs.get(edge_id)
        if cost_result is None or not cost_result.allowed or cost_result.cost is None:
            continue
        nx_graph.add_edge(edge.from_node_id, edge.to_node_id, edge_id=edge_id, weight=cost_result.cost)

    return nx_graph


@dataclass
class SparseRoadGraph:
    """探索グラフのCSR（圧縮行格納）表現（改善計画T220、T12 Stage 2）。

    `RoadGraphEngine.trace_loop`が1リクエストにつき最大24回（3区間×8方位）呼ぶ
    Dijkstraを、NetworkX（Python実装）からscipy.sparse.csgraph（C実装）へ置き換える
    ために使う。`build_networkx_graph`と同じく、同一ノード間の並行Edgeは1本のみ保持する
    （後から登場したEdgeで上書き。`graph.edges`の反復順=辞書の挿入順に従う）。
    """

    matrix: csr_matrix
    node_id_to_index: dict[str, int]
    index_to_node_id: list[str]
    edge_id_by_index_pair: dict[tuple[int, int], str]


def build_sparse_graph(graph: RoadGraphLike, edge_costs: dict[str, EdgeCostResult]) -> SparseRoadGraph:
    """RoadGraphとEdge Costから`SparseRoadGraph`を構築する（`build_networkx_graph`の
    scipy版）。Hard Constraintで除外されたEdge・Costが算出できなかったEdgeは含めない
    （`build_networkx_graph`と同じ）。

    `scipy.sparse.coo_matrix`は同一(row, col)への重複エントリを合算してしまう
    （NetworkXの「後勝ちで1本化」とは異なる）ため、疎行列を組む前にPython側のdictで
    (from_index, to_index)ごとに1本へ集約してから渡す。
    """
    node_ids = list(graph.nodes.keys())
    node_id_to_index = {node_id: i for i, node_id in enumerate(node_ids)}
    size = len(node_ids)

    best_by_pair: dict[tuple[int, int], tuple[float, str]] = {}
    for edge_id, edge in graph.edges.items():
        cost_result = edge_costs.get(edge_id)
        if cost_result is None or not cost_result.allowed or cost_result.cost is None:
            continue
        from_index = node_id_to_index.get(edge.from_node_id)
        to_index = node_id_to_index.get(edge.to_node_id)
        if from_index is None or to_index is None:
            continue
        best_by_pair[(from_index, to_index)] = (cost_result.cost, edge_id)

    if best_by_pair:
        rows, cols, weights = zip(
            *((u, v, weight) for (u, v), (weight, _edge_id) in best_by_pair.items())
        )
    else:
        rows, cols, weights = (), (), ()

    matrix = csr_matrix((np.asarray(weights, dtype=float), (rows, cols)), shape=(size, size))
    edge_id_by_index_pair = {pair: edge_id for pair, (_weight, edge_id) in best_by_pair.items()}
    return SparseRoadGraph(
        matrix=matrix,
        node_id_to_index=node_id_to_index,
        index_to_node_id=node_ids,
        edge_id_by_index_pair=edge_id_by_index_pair,
    )


def shortest_path_node_ids_sparse(
    sparse_graph: SparseRoadGraph, start_node_id: str, end_node_id: str
) -> list[str] | None:
    """`shortest_path_node_ids`のscipy版。挙動（到達不能・始点=終点の扱い）は同一。"""
    if start_node_id == end_node_id:
        return [start_node_id] if start_node_id in sparse_graph.node_id_to_index else None

    start_index = sparse_graph.node_id_to_index.get(start_node_id)
    end_index = sparse_graph.node_id_to_index.get(end_node_id)
    if start_index is None or end_index is None:
        return None

    distances, predecessors = scipy_dijkstra(
        sparse_graph.matrix, directed=True, indices=start_index, return_predecessors=True
    )
    if not math.isfinite(distances[end_index]):
        return None

    path_indices = [end_index]
    current = end_index
    while current != start_index:
        current = predecessors[current]
        if current < 0:  # scipyの到達不能センチネル（負値）。理論上ここには来ないはず
            return None  # （distancesが有限だった時点で到達可能）だが安全側で扱う。
        path_indices.append(current)
    path_indices.reverse()
    return [sparse_graph.index_to_node_id[i] for i in path_indices]


def path_to_edge_ids_sparse(sparse_graph: SparseRoadGraph, path_node_ids: list[str]) -> list[str]:
    """`path_to_edge_ids`のscipy版。Node ID列を、それらを結ぶDirected EdgeのID列へ変換する。"""
    return [
        sparse_graph.edge_id_by_index_pair[
            (sparse_graph.node_id_to_index[u], sparse_graph.node_id_to_index[v])
        ]
        for u, v in zip(path_node_ids, path_node_ids[1:])
    ]


def routable_node_ids(sparse_graph: SparseRoadGraph) -> set[str]:
    """`sparse_graph`上で最低1本のEdge（発/着どちらでも可）を持つNode ID集合を返す
    （改善計画T256）。

    `build_sparse_graph`はHard Constraintで除外されたEdgeを含めないため、幹線道路
    （`highway=trunk`等）にしか接続していないNodeは、除外後のグラフ上では次数0の
    孤立点になる。孤立Nodeを最近傍探索の候補に含めたまま`find_nearest_node_indexed`を
    呼ぶと、地理的には最も近くても実際には出発・経由不能なNodeが選ばれ、そこから先の
    Dijkstra探索が常に失敗する（主要駅が国道の交差点に直接面している新宿駅・渋谷駅等で
    実機確認、8方位すべてが`no path found`になる）。`build_node_spatial_index`へ
    この集合を渡すことで、索引の候補を「実際に経路探索可能なNode」だけに絞れる。
    """
    rows, cols = sparse_graph.matrix.nonzero()
    connected_indices = set(rows.tolist()) | set(cols.tolist())
    return {sparse_graph.index_to_node_id[i] for i in connected_indices}


def find_nearest_node(graph: RoadGraphLike, point: Coordinates) -> str | None:
    """総当たりで指定地点に最も近いNodeを探す。

    1回のRoad Graph構築（1リクエスト分のbbox）あたりのNode数は数千程度を想定しており、
    この規模であれば線形探索でも実用上問題にならない。ノードが1つも無い場合はNoneを返す。

    同じgraphに対して複数回呼ぶ場合（`RoadGraphEngine`は1リクエストにつき最大17回、
    改善計画T219参照）は、都度線形走査するこの関数ではなく`build_node_spatial_index`＋
    `find_nearest_node_indexed`を使うと索引を使い回せる。
    """
    nearest_node_id: str | None = None
    nearest_distance: float | None = None
    for node_id, node in graph.nodes.items():
        # 改善計画T262: nodeは既にlatitude/longitudeを持つ（NodeLike）ため、
        # Coordinates（Pydantic）へ包み直さずそのまま渡す（haversine_distance_kmは
        # LatLon Protocolで受ける）。
        distance = haversine_distance_km(point, node)
        if nearest_distance is None or distance < nearest_distance:
            nearest_distance = distance
            nearest_node_id = node_id
    return nearest_node_id


@dataclass
class NodeSpatialIndex:
    """`find_nearest_node`の線形探索を高速化する緯度経度グリッドバケット索引
    （改善計画T219、T12 Stage 1）。

    `RoadGraphEngine`は1リクエストの同じRoad Graphに対し最大17回`find_nearest_node`
    相当の呼び出しを行う（`prepare`で1回・`trace_loop`で方位ごとに2回）。ノード数が
    増えるとこの繰り返しが線形探索×17回ぶん積み上がるため、索引を1回だけ構築して
    使い回す。新規外部ライブラリ（scipy.spatial.cKDTree等）は導入せず、既定の
    `dict`だけで組めるグリッドバケット方式にする（PostGIS空間インデックスが無い
    構成でも同じロジックで動く）。
    """

    graph: RoadGraphLike
    cell_size_deg: float
    buckets: dict[tuple[int, int], list[str]]


# 1セルの一辺（度）。緯度で約1.1km四方（東京付近では経度方向はcos(35°)倍で約0.9km四方）。
# Road Graph構築bbox（起点半径+マージン、数km〜数十km四方）に対して、1セルあたり
# 概ね数十〜数百ノード程度に収まる粒度を狙った経験的な値（探索半径拡張のコストと
# バケット数のトレードオフ、実測は不要——グリッドバケット方式は極端に不適切な値
# でなければ正しく動作する。将来チューニングする場合はbenchmarks/bench_nearest_node.py
# へ計測を追加する）。
DEFAULT_NODE_INDEX_CELL_SIZE_DEG = 0.01


def build_node_spatial_index(
    graph: RoadGraphLike,
    cell_size_deg: float = DEFAULT_NODE_INDEX_CELL_SIZE_DEG,
    node_ids: Collection[str] | None = None,
) -> NodeSpatialIndex:
    """`graph.nodes`からグリッドバケット索引を構築する。ノードが1つも無くても
    空のbucketsを持つ索引を返す（呼び出し元は`find_nearest_node_indexed`が
    その場合Noneを返すことで区別すればよい）。

    `node_ids`省略時は`graph.nodes`全件を対象にする。指定時はその集合に含まれるNode
    のみを索引の候補にする（改善計画T256: `routable_node_ids`と組み合わせ、Hard
    Constraint通過後に孤立するNodeを最近傍探索の候補から除外するために使う）。
    """
    ids = graph.nodes.keys() if node_ids is None else node_ids
    buckets: dict[tuple[int, int], list[str]] = {}
    for node_id in ids:
        node = graph.nodes[node_id]
        key = (math.floor(node.latitude / cell_size_deg), math.floor(node.longitude / cell_size_deg))
        buckets.setdefault(key, []).append(node_id)
    return NodeSpatialIndex(graph=graph, cell_size_deg=cell_size_deg, buckets=buckets)


def find_nearest_node_indexed(index: NodeSpatialIndex, point: Coordinates) -> str | None:
    """`build_node_spatial_index`が作った索引を使い、指定地点に最も近いNodeを探す。

    グリッドバケットを中心セルから外側へリング状に広げながら探索し、既知の最近傍距離が
    「まだ調べていない外側リングのどの点までの距離よりも近い」と保証できた時点で打ち切る
    （標準的なグリッド最近傍探索の安全な停止条件）。安全マージンには緯度方向（cos補正なし、
    どの緯度でも経度方向より短くならない）の1度あたり距離を使うため、経度方向のセルが
    実際にはより狭い（高緯度ほど顕著）場合でも打ち切りが早すぎることはない。
    """
    if not index.graph.nodes:
        return None

    cell_lat = math.floor(point.latitude / index.cell_size_deg)
    cell_lon = math.floor(point.longitude / index.cell_size_deg)
    cell_size_km_lower_bound = index.cell_size_deg * KM_PER_DEGREE_LATITUDE

    nearest_node_id: str | None = None
    nearest_distance: float | None = None
    radius = 0
    max_radius = max(len(index.buckets), 1) + 1  # 理論上到達しない安全弁（無限ループ防止）
    while radius <= max_radius:
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) != radius:
                    continue  # 内側のリングは前回までのループで調べ済み
                for node_id in index.buckets.get((cell_lat + dx, cell_lon + dy), ()):
                    node = index.graph.nodes[node_id]
                    # 改善計画T262: find_nearest_node同様、Coordinatesへ包み直さない。
                    distance = haversine_distance_km(point, node)
                    if nearest_distance is None or distance < nearest_distance:
                        nearest_distance = distance
                        nearest_node_id = node_id
        if nearest_distance is not None and radius * cell_size_km_lower_bound >= nearest_distance:
            break
        radius += 1
    return nearest_node_id


def shortest_path_node_ids(nx_graph: nx.DiGraph, start_node_id: str, end_node_id: str) -> list[str] | None:
    """start_node_idからend_node_idまでの最小コスト経路をNode ID列で返す。
    経路が存在しない（到達不能）場合はNoneを返す。"""
    if start_node_id == end_node_id:
        return [start_node_id]
    try:
        return nx.dijkstra_path(nx_graph, start_node_id, end_node_id, weight="weight")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None


def path_to_edge_ids(nx_graph: nx.DiGraph, path_node_ids: list[str]) -> list[str]:
    """Node ID列を、それらを結ぶDirected EdgeのID列へ変換する。"""
    return [nx_graph[u][v]["edge_id"] for u, v in zip(path_node_ids, path_node_ids[1:])]


def concat_node_paths(paths: list[list[str]]) -> list[str]:
    """複数区間（例: 起点→経由地A、経由地A→経由地B、...）のNode ID列を1本に連結する。
    隣接する区間の境界ノード（前区間の終端＝次区間の始端）が重複しないようにする。
    """
    if not paths:
        return []
    combined = list(paths[0])
    for path in paths[1:]:
        combined.extend(path[1:])
    return combined
