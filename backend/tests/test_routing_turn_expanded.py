"""状態＝有向Edge・辺＝ターンの展開構造（`domain/routing.py`）のテスト。"""

import numpy as np
from scipy.sparse.csgraph import dijkstra as scipy_dijkstra

from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.domain.routing import (
    TurnCostSpec,
    build_csr_structure,
    build_lazy_road_graph,
    build_shortest_path_tree,
    build_turn_expanded_csr,
    build_turn_expanded_structure,
    edge_bearings,
    node_costs_from_state_costs,
    turn_seconds_for,
)

SPEED_MS = 20.0 / 3.6


def _node(node_id: str, lat: float, lon: float) -> Node:
    return Node(node_id=node_id, latitude=lat, longitude=lon)


def _edge(edge_id: str, from_id: str, to_id: str, bearing_deg: float, distance_m: float = 100.0) -> DirectedEdge:
    return DirectedEdge(
        edge_id=edge_id, from_node_id=from_id, to_node_id=to_id,
        geometry=[[35.700, 139.700], [35.701, 139.700]], distance_m=distance_m,
        bearing_deg=bearing_deg,
    )


def _crossroads() -> RoadGraph:
    """中心Cで交わる十字路（各方向とも双方向）。方位は北0度・東90度・南180度・西270度。"""
    nodes = {
        "C": _node("C", 35.700, 139.700),
        "N": _node("N", 35.701, 139.700),
        "S": _node("S", 35.699, 139.700),
        "E": _node("E", 35.700, 139.701),
        "W": _node("W", 35.700, 139.699),
    }
    edges = {
        "S-C": _edge("S-C", "S", "C", 0.0),
        "C-N": _edge("C-N", "C", "N", 0.0),
        "C-S": _edge("C-S", "C", "S", 180.0),
        "N-C": _edge("N-C", "N", "C", 180.0),
        "C-E": _edge("C-E", "C", "E", 90.0),
        "E-C": _edge("E-C", "E", "C", 270.0),
        "C-W": _edge("C-W", "C", "W", 270.0),
        "W-C": _edge("W-C", "W", "C", 90.0),
    }
    return RoadGraph(graph_version="v1", nodes=nodes, edges=edges)


def _structure_for(graph: RoadGraph, spec: TurnCostSpec = TurnCostSpec()):
    lazy_graph = build_lazy_road_graph(graph)
    csr = build_csr_structure(lazy_graph)
    structure = build_turn_expanded_structure(csr, lazy_graph, edge_bearings(graph, lazy_graph), spec)
    return lazy_graph, csr, structure


def test_turn_seconds_classifies_straight_left_right_and_uturn():
    spec = TurnCostSpec()
    from_bearing = np.array([0.0, 0.0, 0.0, 0.0, 350.0])
    to_bearing = np.array([10.0, 90.0, 270.0, 180.0, 20.0])
    is_uturn = np.array([False, False, False, True, False])
    seconds = turn_seconds_for(from_bearing, to_bearing, is_uturn, spec)
    assert seconds[0] == 0.0, "方位差10度は直進"
    assert seconds[1] == spec.right_seconds, "東へ曲がるのは右折"
    assert seconds[2] == spec.left_seconds, "西へ曲がるのは左折"
    assert seconds[3] == spec.uturn_seconds
    assert seconds[4] == 0.0, "350度から20度への30度差は直進（0度をまたぐ）"


def test_turn_expanded_structure_assigns_costs_by_direction():
    graph = _crossroads()
    lazy_graph, _, structure = _structure_for(graph)
    spec = TurnCostSpec()

    state = lazy_graph.edge_ids.index("S-C")
    transitions = {
        lazy_graph.edge_ids[structure.target_state[i]]: structure.turn_seconds[i]
        for i in range(structure.indptr[state], structure.indptr[state + 1])
    }
    assert transitions == {
        "C-N": 0.0, "C-E": spec.right_seconds, "C-W": spec.left_seconds, "C-S": spec.uturn_seconds,
    }


def test_turn_expanded_structure_transition_count_matches_in_times_out_degree():
    graph = _crossroads()
    lazy_graph, csr, structure = _structure_for(graph)
    # 中心Cは入次数4・出次数4、端の4Nodeは入次数1・出次数1。
    assert len(structure.target_state) == 4 * 4 + 4 * 1
    assert structure.state_count == len(lazy_graph.edge_ids)
    assert len(structure.indptr) == structure.state_count + 1
    assert int(structure.indptr[-1]) == len(structure.target_state)


def test_one_to_all_matches_node_based_tree_when_turns_are_free():
    """ターンの費用が0なら、状態＝有向Edgeの木から導いたNodeごとの最小コストは、
    状態＝Nodeの木と一致する（起点Nodeを除く。起点は「戻ってくるコスト」になるため）。"""
    graph = _crossroads()
    free = TurnCostSpec(left_seconds=0.0, right_seconds=0.0, uturn_seconds=0.0)
    lazy_graph, csr, structure = _structure_for(graph, free)
    cost = np.array([float(graph.edges[edge_id].distance_m) for edge_id in lazy_graph.edge_ids])

    origin_index = lazy_graph.node_id_to_index["S"]
    node_tree = build_shortest_path_tree(
        csr, cost.tolist(), np.array([float(graph.edges[e].distance_m) for e in lazy_graph.edge_ids]), origin_index
    )
    origin_edges = csr.entry_edge_index[csr.indptr[origin_index]:csr.indptr[origin_index + 1]]
    matrix = build_turn_expanded_csr(structure, cost, origin_edges, SPEED_MS)
    state_cost = scipy_dijkstra(matrix, directed=True, indices=structure.state_count)
    per_node = node_costs_from_state_costs(state_cost, structure, csr.node_count)

    for node_id, node_index in lazy_graph.node_id_to_index.items():
        if node_index == origin_index:
            continue
        assert per_node[node_index] == node_tree.cost[node_index], f"{node_id}のコストが一致しない"


def test_expensive_right_turn_makes_the_search_avoid_it():
    """右折が高ければ、遠回りでも右折を避ける経路が選ばれる（ターンの費用が効いていること）。

    起点Sから目的地Eへ2通り置く: S→C→E（Cで右折、200m）と、S→A→B→E（方位が揃った直進
    だけ、300m）。右折が安ければ短い方、高ければ直進だけの方が選ばれる。
    """
    nodes = {name: _node(name, 35.700, 139.700) for name in ("S", "C", "E", "A", "B")}
    edges = {
        "S-C": _edge("S-C", "S", "C", 0.0),
        "C-E": _edge("C-E", "C", "E", 90.0),
        "S-A": _edge("S-A", "S", "A", 45.0),
        "A-B": _edge("A-B", "A", "B", 45.0),
        "B-E": _edge("B-E", "B", "E", 45.0),
    }
    graph = RoadGraph(graph_version="v1", nodes=nodes, edges=edges)

    results = {}
    for label, right_seconds in (("安い右折", 0.0), ("高い右折", 60.0)):
        spec = TurnCostSpec(right_seconds=right_seconds, left_seconds=0.0, uturn_seconds=600.0)
        lazy_graph, csr, structure = _structure_for(graph, spec)
        cost = np.array([float(graph.edges[edge_id].distance_m) for edge_id in lazy_graph.edge_ids])
        origin_index = lazy_graph.node_id_to_index["S"]
        origin_edges = csr.entry_edge_index[csr.indptr[origin_index]:csr.indptr[origin_index + 1]]
        matrix = build_turn_expanded_csr(structure, cost, origin_edges, SPEED_MS)
        state_cost = scipy_dijkstra(matrix, directed=True, indices=structure.state_count)
        per_node = node_costs_from_state_costs(state_cost, structure, csr.node_count)
        results[label] = per_node[lazy_graph.node_id_to_index["E"]]

    assert results["安い右折"] == 200.0, "右折が無料ならS→C→Eの200m"
    # 右折60秒は時速20kmで333m相当のため、300mの直進ルートの方が安くなる。
    assert results["高い右折"] == 300.0
