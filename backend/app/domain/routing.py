"""Route Engine（仕様書33-34章）。

Road Graph（domain/graph.py）とEdge Cost（domain/evaluation.py）を使って、2点間の
最小コスト経路を探索する。探索アルゴリズム自体は独自実装せず、標準的なグラフ
アルゴリズムライブラリ（NetworkX）のDijkstra実装をそのまま利用する（仕様書34章
「探索アルゴリズムを独断で変更しない」「独自の経路探索アルゴリズムの実装はしない」
の趣旨を踏まえ、新規性のある独自アルゴリズムは開発しない）。

Route Engineは、Costの中身（勾配がきつい、路面が悪い等）を一切知らない設計とする
（仕様書33章）。ここで扱うのはRoad Graphのトポロジーと、既に計算済みのEdge Costのみ。
"""

import math
from dataclasses import dataclass

import networkx as nx

from app.domain.evaluation import EdgeCostResult
from app.domain.geo import haversine_distance_km
from app.domain.graph import RoadGraph
from app.domain.route import Coordinates

# 緯度1度あたりの概算距離（km、地球を球とみなす近似。haversine_distance_kmと同じ半径
# 前提で十分、空間索引のバケット分割・打ち切り判定という「目安」用途にのみ使う。
# 実際の距離計算は常にhaversine_distance_kmで正確に行う）。
_KM_PER_DEGREE_LATITUDE = 111.0


def build_networkx_graph(graph: RoadGraph, edge_costs: dict[str, EdgeCostResult]) -> nx.DiGraph:
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


def find_nearest_node(graph: RoadGraph, point: Coordinates) -> str | None:
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
        distance = haversine_distance_km(point, Coordinates(latitude=node.latitude, longitude=node.longitude))
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

    graph: RoadGraph
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
    graph: RoadGraph, cell_size_deg: float = DEFAULT_NODE_INDEX_CELL_SIZE_DEG
) -> NodeSpatialIndex:
    """`graph.nodes`からグリッドバケット索引を構築する。ノードが1つも無くても
    空のbucketsを持つ索引を返す（呼び出し元は`find_nearest_node_indexed`が
    その場合Noneを返すことで区別すればよい）。"""
    buckets: dict[tuple[int, int], list[str]] = {}
    for node_id, node in graph.nodes.items():
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
    cell_size_km_lower_bound = index.cell_size_deg * _KM_PER_DEGREE_LATITUDE

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
                    distance = haversine_distance_km(
                        point, Coordinates(latitude=node.latitude, longitude=node.longitude)
                    )
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
