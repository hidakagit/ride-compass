"""Route Engine（仕様書33-34章）。

Road Graph（domain/graph.py）とEdge Cost（domain/evaluation.py）を使って、2点間の
最小コスト経路を探索する。探索アルゴリズム自体は独自実装せず、標準的なグラフ
アルゴリズムライブラリ（NetworkX）のDijkstra実装をそのまま利用する（仕様書34章
「探索アルゴリズムを独断で変更しない」「独自の経路探索アルゴリズムの実装はしない」
の趣旨を踏まえ、新規性のある独自アルゴリズムは開発しない）。

Route Engineは、Costの中身（勾配がきつい、路面が悪い等）を一切知らない設計とする
（仕様書33章）。ここで扱うのはRoad Graphのトポロジーと、既に計算済みのEdge Costのみ。
"""

import networkx as nx

from app.domain.evaluation import EdgeCostResult
from app.domain.geo import haversine_distance_km
from app.domain.graph import RoadGraph
from app.domain.route import Coordinates


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

    PostGISを使わない構成（repository未指定）では空間インデックスが無いため単純な
    線形探索とする。1回のRoad Graph構築（1リクエスト分のbbox）あたりのNode数は
    数千程度を想定しており、この規模であれば線形探索でも実用上問題にならない。
    ノードが1つも無い場合はNoneを返す。
    """
    nearest_node_id: str | None = None
    nearest_distance: float | None = None
    for node_id, node in graph.nodes.items():
        distance = haversine_distance_km(point, Coordinates(latitude=node.latitude, longitude=node.longitude))
        if nearest_distance is None or distance < nearest_distance:
            nearest_distance = distance
            nearest_node_id = node_id
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
