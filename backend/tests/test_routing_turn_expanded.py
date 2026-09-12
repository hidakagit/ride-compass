"""状態＝有向Edge・辺＝ターンの展開構造（`domain/routing.py`）のテスト。"""

import numpy as np
import pytest
from scipy.sparse.csgraph import dijkstra as scipy_dijkstra

from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.domain.routing import (
    TurnCostSpec,
    build_csr_structure,
    build_lazy_road_graph,
    build_turn_expanded_csr,
    build_turn_expanded_structure,
    build_turn_expanded_tree,
    combine_forward_backward_at_nodes,
    edge_bearings,
    node_costs_from_state_costs,
    turn_expanded_path_edge_indices,
    turn_expanded_shortest_path,
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


def test_one_to_all_gives_the_distance_along_the_path_when_turns_are_free():
    """ターンの費用が0なら、Nodeごとのコストは経路上の区間の長さの和になる。"""
    graph = _crossroads()
    free = TurnCostSpec(left_seconds=0.0, right_seconds=0.0, uturn_seconds=0.0)
    lazy_graph, csr, structure = _structure_for(graph, free)
    cost = np.array([float(graph.edges[edge_id].distance_m) for edge_id in lazy_graph.edge_ids])

    origin_index = lazy_graph.node_id_to_index["S"]
    origin_edges = csr.entry_edge_index[csr.indptr[origin_index]:csr.indptr[origin_index + 1]]
    matrix = build_turn_expanded_csr(structure, cost, origin_edges, SPEED_MS)
    state_cost = scipy_dijkstra(matrix, directed=True, indices=structure.state_count)
    per_node = node_costs_from_state_costs(state_cost, structure, csr.node_count)

    assert per_node[lazy_graph.node_id_to_index["C"]] == 100.0
    for node_id in ("N", "E", "W"):
        assert per_node[lazy_graph.node_id_to_index[node_id]] == 200.0
    # 起点は「戻ってくるコスト」になる（状態の空間に「まだ走っていない」が無いため）。
    assert per_node[origin_index] == 200.0


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


def _tree_for(graph: RoadGraph, origin_id: str, spec: TurnCostSpec, reverse: bool = False):
    lazy_graph, csr, structure = _structure_for(graph, spec)
    cost = np.array([float(graph.edges[edge_id].distance_m) for edge_id in lazy_graph.edge_ids])
    length = cost.copy()
    node_index = lazy_graph.node_id_to_index[origin_id]
    if reverse:
        # 目的地へ入る状態（＝終点がそのNodeの有向Edge）を始点にする。
        entry = np.flatnonzero(structure.edge_to == node_index)
    else:
        entry = csr.entry_edge_index[csr.indptr[node_index]:csr.indptr[node_index + 1]].astype(np.int64)
    tree = build_turn_expanded_tree(
        structure, cost, length, entry, SPEED_MS, csr.node_count, reverse=reverse
    )
    return lazy_graph, structure, tree


def test_turn_expanded_tree_costs_and_lengths_follow_the_path():
    graph = _crossroads()
    free = TurnCostSpec(left_seconds=0.0, right_seconds=0.0, uturn_seconds=0.0)
    lazy_graph, _, tree = _tree_for(graph, "S", free)

    center = lazy_graph.node_id_to_index["C"]
    east = lazy_graph.node_id_to_index["E"]
    assert tree.node_cost[center] == 100.0
    assert tree.node_length_m[center] == 100.0
    assert tree.node_cost[east] == 200.0
    assert tree.node_length_m[east] == 200.0


def test_turn_expanded_tree_path_returns_edge_indices():
    graph = _crossroads()
    free = TurnCostSpec(left_seconds=0.0, right_seconds=0.0, uturn_seconds=0.0)
    lazy_graph, _, tree = _tree_for(graph, "S", free)

    edges = turn_expanded_path_edge_indices(tree, lazy_graph.node_id_to_index["E"])
    assert [lazy_graph.edge_ids[index] for index in edges] == ["S-C", "C-E"]


def test_turn_expanded_tree_reverse_gives_cost_to_the_destination():
    """逆向きの木は「その区間から目的地まで」のコストを返す。"""
    graph = _crossroads()
    free = TurnCostSpec(left_seconds=0.0, right_seconds=0.0, uturn_seconds=0.0)
    lazy_graph, _, tree = _tree_for(graph, "E", free, reverse=True)

    # WからEまではW→C→Eの200m。木の始点（E）側からは、その区間を遡って積算する。
    west = lazy_graph.node_id_to_index["W"]
    assert tree.node_cost[west] == 200.0


def test_turn_expanded_tree_marks_unreachable_states():
    nodes = {name: _node(name, 35.700, 139.700) for name in ("S", "C", "X")}
    edges = {
        "S-C": _edge("S-C", "S", "C", 0.0),
        # Xはどこからも入れない孤立Node（X-Cのみ）。
        "X-C": _edge("X-C", "X", "C", 0.0),
    }
    graph = RoadGraph(graph_version="v1", nodes=nodes, edges=edges)
    lazy_graph, _, tree = _tree_for(graph, "S", TurnCostSpec())

    assert np.isfinite(tree.node_cost[lazy_graph.node_id_to_index["C"]])
    assert not np.isfinite(tree.node_cost[lazy_graph.node_id_to_index["X"]])
    assert turn_expanded_path_edge_indices(tree, lazy_graph.node_id_to_index["X"]) is None


def test_combining_forward_and_backward_trees_includes_the_turn_at_the_junction():
    """繋ぎ目のNodeで曲がる費用が合計へ入る（単に前向き＋後ろ向きを足すと抜ける）。"""
    graph = _crossroads()
    spec = TurnCostSpec(right_seconds=60.0, left_seconds=0.0, uturn_seconds=600.0)
    lazy_graph, csr, structure = _structure_for(graph, spec)
    cost = np.array([float(graph.edges[edge_id].distance_m) for edge_id in lazy_graph.edge_ids])

    origin = lazy_graph.node_id_to_index["S"]
    destination = lazy_graph.node_id_to_index["E"]
    forward_entry = csr.entry_edge_index[csr.indptr[origin]:csr.indptr[origin + 1]].astype(np.int64)
    backward_entry = np.flatnonzero(structure.edge_to == destination)
    forward = build_turn_expanded_tree(
        structure, cost, cost, forward_entry, SPEED_MS, csr.node_count
    )
    backward = build_turn_expanded_tree(
        structure, cost, cost, backward_entry, SPEED_MS, csr.node_count, reverse=True
    )
    junction = combine_forward_backward_at_nodes(structure, forward, backward, SPEED_MS, csr.node_count)

    center = lazy_graph.node_id_to_index["C"]
    # S-C(100m) → Cで右折(60秒=333.33m相当) → C-E(100m)
    assert junction.cost[center] == pytest.approx(200.0 + 60.0 * SPEED_MS)
    assert junction.length_m[center] == pytest.approx(200.0)
    assert lazy_graph.edge_ids[junction.forward_state[center]] == "S-C"
    assert lazy_graph.edge_ids[junction.backward_state[center]] == "C-E"
    # Nodeごとのコストを単に足すとターンぶんが抜ける（この関数が解いている問題）。
    assert forward.node_cost[center] + backward.node_cost[center] == pytest.approx(200.0)


def test_turn_expanded_tree_length_counts_every_edge_on_a_shallow_path():
    """深さ2の経路（他に深い枝が無い）でも、始点の区間の長さが積算から落ちない。"""
    nodes = {name: _node(name, 35.700, 139.700) for name in ("S", "V", "D")}
    edges = {
        "S-V": _edge("S-V", "S", "V", 0.0, distance_m=300.0),
        "V-D": _edge("V-D", "V", "D", 0.0, distance_m=400.0),
    }
    graph = RoadGraph(graph_version="v1", nodes=nodes, edges=edges)
    lazy_graph, _, tree = _tree_for(graph, "S", TurnCostSpec())

    assert tree.node_length_m[lazy_graph.node_id_to_index["V"]] == 300.0
    assert tree.node_length_m[lazy_graph.node_id_to_index["D"]] == 700.0


def _astar_path(graph: RoadGraph, origin_id: str, goal_id: str, spec: TurnCostSpec) -> list[str]:
    lazy_graph, csr, structure = _structure_for(graph, spec)
    cost = np.array([float(graph.edges[edge_id].distance_m) for edge_id in lazy_graph.edge_ids])
    origin_index = lazy_graph.node_id_to_index[origin_id]
    origin_states = csr.entry_edge_index[csr.indptr[origin_index]:csr.indptr[origin_index + 1]].astype(np.int64)
    edges = turn_expanded_shortest_path(
        structure, cost, np.zeros(csr.node_count), origin_states,
        lazy_graph.node_id_to_index[goal_id], SPEED_MS,
    )
    return [] if edges is None else [lazy_graph.edge_ids[index] for index in edges]


def test_turn_expanded_astar_finds_the_shortest_path():
    free = TurnCostSpec(left_seconds=0.0, right_seconds=0.0, uturn_seconds=0.0)
    assert _astar_path(_crossroads(), "S", "E", free) == ["S-C", "C-E"]


def test_turn_expanded_astar_avoids_expensive_right_turn():
    """一対全木と同じ判断を2点間探索でもする（右折が高ければ直進だけの遠回りを選ぶ）。"""
    nodes = {name: _node(name, 35.700, 139.700) for name in ("S", "C", "E", "A", "B")}
    edges = {
        "S-C": _edge("S-C", "S", "C", 0.0),
        "C-E": _edge("C-E", "C", "E", 90.0),
        "S-A": _edge("S-A", "S", "A", 45.0),
        "A-B": _edge("A-B", "A", "B", 45.0),
        "B-E": _edge("B-E", "B", "E", 45.0),
    }
    graph = RoadGraph(graph_version="v1", nodes=nodes, edges=edges)

    cheap = TurnCostSpec(right_seconds=0.0, left_seconds=0.0, uturn_seconds=600.0)
    expensive = TurnCostSpec(right_seconds=60.0, left_seconds=0.0, uturn_seconds=600.0)
    assert _astar_path(graph, "S", "E", cheap) == ["S-C", "C-E"]
    assert _astar_path(graph, "S", "E", expensive) == ["S-A", "A-B", "B-E"]


def test_turn_expanded_astar_returns_none_when_unreachable():
    nodes = {name: _node(name, 35.700, 139.700) for name in ("S", "C", "X", "Y")}
    edges = {
        "S-C": _edge("S-C", "S", "C", 0.0),
        "X-Y": _edge("X-Y", "X", "Y", 0.0),
    }
    graph = RoadGraph(graph_version="v1", nodes=nodes, edges=edges)
    assert _astar_path(graph, "S", "Y", TurnCostSpec()) == []
