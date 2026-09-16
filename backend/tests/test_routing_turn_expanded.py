"""状態＝有向Edge・辺＝ターンの展開構造（`domain/routing.py`）のテスト。"""

import numpy as np
import pytest

from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.domain.routing import (
    TurnCostSpec,
    build_csr_structure,
    build_lazy_road_graph,
    build_turn_expanded_structure,
    build_turn_expanded_tree,
    combine_forward_backward_at_nodes,
    edge_bearings,
    turn_expanded_path_edge_indices,
    turn_expanded_shortest_path,
    turn_seconds_for,
)
from app.domain.traffic import MAJOR_CROSSING_MIN_RANK

SPEED_MS = 20.0 / 3.6


def _seconds(graph, lazy_graph):
    """区間の長さを時速20kmで走ったときの秒。探索のコストは秒で揃える（ターンの待ちと
    同じ単位で足せることがこの設計の要件）。"""
    return np.array([float(graph.edges[edge_id].distance_m) / SPEED_MS for edge_id in lazy_graph.edge_ids])


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
    structure = build_turn_expanded_structure(csr, lazy_graph, edge_bearings(graph, lazy_graph), spec=spec)
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


def test_expensive_right_turn_makes_the_search_avoid_it():
    """右折が高ければ、遠回りでも右折を避ける経路が選ばれる（ターンの費用が効いていること）。

    起点Sから目的地Eへ2通り置く: S→C→E（Cで右折、200m＝36秒）と、S→A→B→E（方位が揃った
    直進だけ、300m＝54秒）。右折が安ければ短い方、高ければ直進だけの方が選ばれる。
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
        lazy_graph, csr, tree = _tree_for(graph, "S", spec)
        results[label] = tree.node_cost[lazy_graph.node_id_to_index["E"]]

    assert results["安い右折"] == pytest.approx(200.0 / SPEED_MS), "右折が無料ならS→C→Eの36秒"
    # 右折60秒は2経路の差（54-36=18秒）を上回るため、直進だけの経路の方が安くなる。
    assert results["高い右折"] == pytest.approx(300.0 / SPEED_MS)


def _tree_for(graph: RoadGraph, origin_id: str, spec: TurnCostSpec, reverse: bool = False):
    lazy_graph, csr, structure = _structure_for(graph, spec)
    cost = _seconds(graph, lazy_graph)
    length = np.array([float(graph.edges[edge_id].distance_m) for edge_id in lazy_graph.edge_ids])
    node_index = lazy_graph.node_id_to_index[origin_id]
    if reverse:
        # 目的地へ入る状態（＝終点がそのNodeの有向Edge）を始点にする。
        entry = np.flatnonzero(structure.edge_to == node_index)
    else:
        entry = csr.entry_edge_index[csr.indptr[node_index]:csr.indptr[node_index + 1]].astype(np.int64)
    tree = build_turn_expanded_tree(
        structure, cost, length, entry, csr.node_count, reverse=reverse, edge_seconds=cost
    )
    return lazy_graph, (csr, structure), tree


def test_turn_expanded_tree_costs_and_lengths_follow_the_path():
    graph = _crossroads()
    free = TurnCostSpec(left_seconds=0.0, right_seconds=0.0, uturn_seconds=0.0)
    lazy_graph, _, tree = _tree_for(graph, "S", free)

    center = lazy_graph.node_id_to_index["C"]
    east = lazy_graph.node_id_to_index["E"]
    assert tree.node_cost[center] == pytest.approx(100.0 / SPEED_MS)
    assert tree.node_length_m[center] == 100.0
    assert tree.node_cost[east] == pytest.approx(200.0 / SPEED_MS)
    assert tree.node_length_m[east] == 200.0
    # ターンが無料なので、積算した所要時間はコストと一致する（割増が乗っていないこと）。
    assert tree.node_seconds[east] == pytest.approx(tree.node_cost[east])


def test_turn_expanded_tree_path_returns_edge_indices():
    graph = _crossroads()
    free = TurnCostSpec(left_seconds=0.0, right_seconds=0.0, uturn_seconds=0.0)
    lazy_graph, _, tree = _tree_for(graph, "S", free)

    edges = turn_expanded_path_edge_indices(tree, lazy_graph.node_id_to_index["E"])
    assert [lazy_graph.edge_ids[index] for index in edges] == ["S-C", "C-E"]


def _two_route_graph() -> RoadGraph:
    """S→C→E（200m）とS→A→B→E（300m）の2通りで同じEへ着くグラフ。"""
    nodes = {name: _node(name, 35.700, 139.700) for name in ("S", "C", "E", "A", "B")}
    edges = {
        "S-C": _edge("S-C", "S", "C", 0.0),
        "C-E": _edge("C-E", "C", "E", 0.0),
        "S-A": _edge("S-A", "S", "A", 0.0),
        "A-B": _edge("A-B", "A", "B", 0.0),
        "B-E": _edge("B-E", "B", "E", 0.0),
    }
    return RoadGraph(graph_version="v1", nodes=nodes, edges=edges)


def test_turn_expanded_tree_switches_route_on_the_elapsed_time_bin():
    """経過時間のビンでコストが変われば、木も同じ起点から別の経路を選ぶ。

    本番の周回生成・目的地ルートの前向き木はどちらも時刻ビン付きで木を張る（風が到達時刻で
    変わるため）。ビン0では短い方を安く、ビン1ではその区間だけ極端に高いコストを渡し、
    1区間（100m＝18秒）でビン1へ移る幅（10秒）に置くと、「出発時点では短い方が安いが
    そこへ着く頃には高くなっている」を見て遠回りを選ぶ。
    """
    graph = _two_route_graph()
    free = TurnCostSpec(left_seconds=0.0, right_seconds=0.0, uturn_seconds=0.0)
    lazy_graph, csr, structure = _structure_for(graph, free)
    seconds = _seconds(graph, lazy_graph)
    length = np.array([float(graph.edges[edge_id].distance_m) for edge_id in lazy_graph.edge_ids])
    origin = lazy_graph.node_id_to_index["S"]
    entry = csr.entry_edge_index[csr.indptr[origin]:csr.indptr[origin + 1]].astype(np.int64)

    def path_for(cost_bins):
        tree = build_turn_expanded_tree(
            structure, cost_bins, length, entry, csr.node_count,
            edge_seconds=np.vstack([seconds, seconds]), bin_seconds=10.0,
        )
        edges = turn_expanded_path_edge_indices(tree, lazy_graph.node_id_to_index["E"])
        return [lazy_graph.edge_ids[index] for index in edges]

    expensive_later = seconds.copy()
    expensive_later[lazy_graph.edge_ids.index("C-E")] *= 100.0

    assert path_for(np.vstack([seconds, seconds])) == ["S-C", "C-E"]
    assert path_for(np.vstack([seconds, expensive_later])) == ["S-A", "A-B", "B-E"]


def test_turn_expanded_tree_accumulates_seconds_from_the_bin_it_arrives_in():
    """所要時間の積算は、その状態へ着いた時刻のビンの秒を足す。

    経路は1本しか無いグラフで、2区間目の秒だけビン1で倍にする。ビンを引く側（コスト）と
    秒を積む側が同じビンを見ていなければ、Eの所要時間がこの値にならない。
    """
    nodes = {name: _node(name, 35.700, 139.700) for name in ("S", "C", "E")}
    edges = {"S-C": _edge("S-C", "S", "C", 0.0), "C-E": _edge("C-E", "C", "E", 0.0)}
    graph = RoadGraph(graph_version="v1", nodes=nodes, edges=edges)
    free = TurnCostSpec(left_seconds=0.0, right_seconds=0.0, uturn_seconds=0.0)
    lazy_graph, csr, structure = _structure_for(graph, free)
    seconds = _seconds(graph, lazy_graph)
    length = np.array([float(graph.edges[edge_id].distance_m) for edge_id in lazy_graph.edge_ids])
    origin = lazy_graph.node_id_to_index["S"]
    entry = csr.entry_edge_index[csr.indptr[origin]:csr.indptr[origin + 1]].astype(np.int64)

    slower_later = seconds.copy()
    slower_later[lazy_graph.edge_ids.index("C-E")] *= 2.0
    tree = build_turn_expanded_tree(
        structure, np.vstack([seconds, seconds]), length, entry, csr.node_count,
        edge_seconds=np.vstack([seconds, slower_later]), bin_seconds=10.0,
    )

    one_edge = 100.0 / SPEED_MS
    # S-Cはビン0（出発時点）の18秒、C-EはS-Cを走り終えた後＝ビン1の36秒。
    assert tree.node_seconds[lazy_graph.node_id_to_index["E"]] == pytest.approx(one_edge * 3.0)


def test_turn_expanded_tree_rejects_time_bins_on_the_reverse_tree():
    """逆向きの木へビンを渡すのは黙って誤った経路になるため、実装が弾く。"""
    graph = _two_route_graph()
    free = TurnCostSpec(left_seconds=0.0, right_seconds=0.0, uturn_seconds=0.0)
    lazy_graph, csr, structure = _structure_for(graph, free)
    seconds = _seconds(graph, lazy_graph)
    length = np.array([float(graph.edges[edge_id].distance_m) for edge_id in lazy_graph.edge_ids])
    entry = np.flatnonzero(structure.edge_to == lazy_graph.node_id_to_index["E"])

    with pytest.raises(ValueError, match="time bins"):
        build_turn_expanded_tree(
            structure, np.vstack([seconds, seconds]), length, entry, csr.node_count,
            reverse=True, edge_seconds=np.vstack([seconds, seconds]), bin_seconds=10.0,
        )

    # 1本のビン（=時刻に依存しないコスト）なら逆向きでも通る。
    tree = build_turn_expanded_tree(
        structure, seconds, length, entry, csr.node_count, reverse=True, edge_seconds=seconds
    )
    assert np.isfinite(tree.node_cost[lazy_graph.node_id_to_index["S"]])


def test_turn_expanded_tree_reverse_gives_cost_to_the_destination():
    """逆向きの木は「その区間から目的地まで」のコストを返す。"""
    graph = _crossroads()
    free = TurnCostSpec(left_seconds=0.0, right_seconds=0.0, uturn_seconds=0.0)
    lazy_graph, _, tree = _tree_for(graph, "E", free, reverse=True)

    # WからEまではW→C→Eの200m＝36秒。木の始点（E）側からは、その区間を遡って積算する。
    west = lazy_graph.node_id_to_index["W"]
    assert tree.node_cost[west] == pytest.approx(200.0 / SPEED_MS)


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
    cost = _seconds(graph, lazy_graph)
    length = np.array([float(graph.edges[edge_id].distance_m) for edge_id in lazy_graph.edge_ids])

    origin = lazy_graph.node_id_to_index["S"]
    destination = lazy_graph.node_id_to_index["E"]
    forward_entry = csr.entry_edge_index[csr.indptr[origin]:csr.indptr[origin + 1]].astype(np.int64)
    backward_entry = np.flatnonzero(structure.edge_to == destination)
    forward = build_turn_expanded_tree(
        structure, cost, length, forward_entry, csr.node_count, edge_seconds=cost
    )
    backward = build_turn_expanded_tree(
        structure, cost, length, backward_entry, csr.node_count, reverse=True, edge_seconds=cost
    )
    junction = combine_forward_backward_at_nodes(structure, forward, backward, csr.node_count)

    center = lazy_graph.node_id_to_index["C"]
    # S-C(100m=18秒) → Cで右折(60秒) → C-E(100m=18秒)
    assert junction.cost[center] == pytest.approx(200.0 / SPEED_MS + 60.0)
    assert junction.length_m[center] == pytest.approx(200.0)
    assert junction.seconds[center] == pytest.approx(200.0 / SPEED_MS + 60.0)
    assert lazy_graph.edge_ids[junction.forward_state[center]] == "S-C"
    assert lazy_graph.edge_ids[junction.backward_state[center]] == "C-E"
    # Nodeごとのコストを単に足すとターンぶんが抜ける（この関数が解いている問題）。
    assert forward.node_cost[center] + backward.node_cost[center] == pytest.approx(200.0 / SPEED_MS)


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
    cost = _seconds(graph, lazy_graph)
    origin_index = lazy_graph.node_id_to_index[origin_id]
    origin_states = csr.entry_edge_index[csr.indptr[origin_index]:csr.indptr[origin_index + 1]].astype(np.int64)
    edges = turn_expanded_shortest_path(
        structure, cost, np.zeros(csr.node_count), origin_states,
        lazy_graph.node_id_to_index[goal_id],
    )
    return [] if edges is None else [lazy_graph.edge_ids[index] for index in edges]


def test_turn_expanded_astar_switches_route_on_the_elapsed_time_bin():
    """経過時間のビンでコストが変われば、A*は同じ出発地・目的地でも別の経路を選ぶ。

    S→C→E（200m）とS→A→B→E（300m）の2通りへ、ビン0では短い方を安く、ビン1では短い方を
    高くしたコストを渡す。1区間（100m＝18秒）を走り終えた時点でビン1へ移るようビンの幅を
    10秒に置くと、探索は「出発時点では短い方が安いが、そこへ着く頃には高くなっている」を
    見て遠回りを選ぶ。
    """
    nodes = {name: _node(name, 35.700, 139.700) for name in ("S", "C", "E", "A", "B")}
    edges = {
        "S-C": _edge("S-C", "S", "C", 0.0),
        "C-E": _edge("C-E", "C", "E", 0.0),
        "S-A": _edge("S-A", "S", "A", 0.0),
        "A-B": _edge("A-B", "A", "B", 0.0),
        "B-E": _edge("B-E", "B", "E", 0.0),
    }
    graph = RoadGraph(graph_version="v1", nodes=nodes, edges=edges)
    free = TurnCostSpec(left_seconds=0.0, right_seconds=0.0, uturn_seconds=0.0)
    lazy_graph, csr, structure = _structure_for(graph, free)
    seconds = _seconds(graph, lazy_graph)

    def path_for(bins):
        origin_index = lazy_graph.node_id_to_index["S"]
        states = csr.entry_edge_index[csr.indptr[origin_index]:csr.indptr[origin_index + 1]].astype(np.int64)
        found = turn_expanded_shortest_path(
            structure, bins, np.zeros(csr.node_count), states,
            lazy_graph.node_id_to_index["E"],
            np.vstack([seconds, seconds]), 10.0,
        )
        return [lazy_graph.edge_ids[i] for i in found]

    cheap_later = seconds.copy()
    cheap_later[lazy_graph.edge_ids.index("C-E")] *= 100.0
    # ビン0（出発直後）は素の所要時間、ビン1（S-Cを走り終えた後）はC-Eだけ極端に高い。
    assert path_for(np.vstack([seconds, seconds])) == ["S-C", "C-E"]
    assert path_for(np.vstack([seconds, cheap_later])) == ["S-A", "A-B", "B-E"]


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


def test_crossing_a_higher_class_road_adds_cost_even_when_going_straight():
    """自分が走ってきた道より上位の道と交わる交差点では、直進で渡るだけでも費用が足される
    （信号が無いのに幹線を横断する場面。信号のある交差点の待ちは停止密度の材料が走行モデルへ
    運ぶため、そちらとは別物）。"""
    nodes = {name: _node(name, 35.700, 139.700) for name in ("S", "C", "E", "P1", "P2")}
    edges = {
        "S-C": _edge("S-C", "S", "C", 0.0),
        "C-E": _edge("C-E", "C", "E", 0.0),
        "P1-C": _edge("P1-C", "P1", "C", 90.0),
        "C-P2": _edge("C-P2", "C", "P2", 90.0),
    }
    graph = RoadGraph(graph_version="v1", nodes=nodes, edges=edges)
    lazy_graph = build_lazy_road_graph(graph)
    csr = build_csr_structure(lazy_graph)
    spec = TurnCostSpec(left_seconds=0.0, right_seconds=0.0, major_crossing_seconds=8.0)
    # 生活道路（rank 1）が幹線（rank 4）と交わる交差点。
    ranks = np.array([4 if edge_id in ("P1-C", "C-P2") else 1 for edge_id in lazy_graph.edge_ids], dtype=np.int64)

    with_rank = build_turn_expanded_structure(csr, lazy_graph, edge_bearings(graph, lazy_graph), ranks, spec)
    without_rank = build_turn_expanded_structure(csr, lazy_graph, edge_bearings(graph, lazy_graph), spec=spec)

    def straight_cost(structure) -> float:
        state = lazy_graph.edge_ids.index("S-C")
        for i in range(structure.indptr[state], structure.indptr[state + 1]):
            if lazy_graph.edge_ids[structure.target_state[i]] == "C-E":
                return float(structure.turn_seconds[i])
        raise AssertionError("S-C→C-Eの遷移が無い")

    assert straight_cost(without_rank) == 0.0, "階級を渡さなければ直進は無料"
    assert straight_cost(with_rank) == spec.major_crossing_seconds


def _major_crossing_fixture():
    """生活道路S-C-Eが、交差点Cで幹線（P1-C-P2）と直交する十字。"""
    nodes = {name: _node(name, 35.700, 139.700) for name in ("S", "C", "E", "P1", "P2")}
    edges = {
        "S-C": _edge("S-C", "S", "C", 0.0),
        "C-E": _edge("C-E", "C", "E", 0.0),
        "P1-C": _edge("P1-C", "P1", "C", 90.0),
        "C-P2": _edge("C-P2", "C", "P2", 90.0),
    }
    graph = RoadGraph(graph_version="v1", nodes=nodes, edges=edges)
    lazy_graph = build_lazy_road_graph(graph)
    return graph, lazy_graph, build_csr_structure(lazy_graph)


def _straight_cost(structure, lazy_graph) -> float:
    state = lazy_graph.edge_ids.index("S-C")
    for i in range(structure.indptr[state], structure.indptr[state + 1]):
        if lazy_graph.edge_ids[structure.target_state[i]] == "C-E":
            return float(structure.turn_seconds[i])
    raise AssertionError("S-C→C-Eの遷移が無い")


def test_a_signalised_crossing_does_not_add_the_major_crossing_cost():
    """信号のある交差点では横断の費用を足さない。

    信号での待ちは停止密度の材料が走行モデルへ運ぶ（`domain/traffic.py: stop_seconds`）。
    ここでも足すと同じ待ちを二重に数える（設計原則13）。ここが担うのは信号が無いときの
    「車列の切れ目を待つ時間」である。
    """
    graph, lazy_graph, csr = _major_crossing_fixture()
    spec = TurnCostSpec(left_seconds=0.0, right_seconds=0.0, major_crossing_seconds=8.0)
    ranks = np.array(
        [4 if edge_id in ("P1-C", "C-P2") else 1 for edge_id in lazy_graph.edge_ids], dtype=np.int64)
    bearings = edge_bearings(graph, lazy_graph)
    signals = np.array(
        [node_id == "C" for node_id in lazy_graph.index_to_node_id], dtype=bool)

    signalised = build_turn_expanded_structure(
        csr, lazy_graph, bearings, ranks, spec, node_has_signal=signals)
    unsignalised = build_turn_expanded_structure(
        csr, lazy_graph, bearings, ranks, spec,
        node_has_signal=np.zeros(len(lazy_graph.index_to_node_id), dtype=bool))

    assert _straight_cost(signalised, lazy_graph) == 0.0
    assert _straight_cost(unsignalised, lazy_graph) == spec.major_crossing_seconds


def test_not_passing_signals_keeps_the_behaviour_of_before_the_column_existed():
    """信号の列を渡さないときは、渡す前（全ノード信号なし）と同じ結果になる。

    `road_nodes`のバッチが未実行の環境（既定値false）でも経路が変わらないことの担保。
    """
    graph, lazy_graph, csr = _major_crossing_fixture()
    spec = TurnCostSpec(left_seconds=0.0, right_seconds=0.0, major_crossing_seconds=8.0)
    ranks = np.array(
        [4 if edge_id in ("P1-C", "C-P2") else 1 for edge_id in lazy_graph.edge_ids], dtype=np.int64)
    bearings = edge_bearings(graph, lazy_graph)

    omitted = build_turn_expanded_structure(csr, lazy_graph, bearings, ranks, spec)
    all_false = build_turn_expanded_structure(
        csr, lazy_graph, bearings, ranks, spec,
        node_has_signal=np.zeros(len(lazy_graph.index_to_node_id), dtype=bool),
        node_db_rank=np.zeros(len(lazy_graph.index_to_node_id), dtype=np.int64))

    assert np.array_equal(omitted.turn_seconds, all_false.turn_seconds)


def test_db_node_rank_can_only_raise_the_rank_derived_from_the_loaded_graph():
    """DB側の階級は下限を上げるだけ。bboxの外へ出た幹線を拾えるが、下げることはない。"""
    graph, lazy_graph, csr = _major_crossing_fixture()
    spec = TurnCostSpec(left_seconds=0.0, right_seconds=0.0, major_crossing_seconds=8.0)
    # 読み込んだ部分グラフには生活道路しか無い（交差する幹線がbboxの外にある状況）。
    ranks = np.ones(len(lazy_graph.edge_ids), dtype=np.int64)
    bearings = edge_bearings(graph, lazy_graph)
    db_rank = np.array(
        [4 if node_id == "C" else 0 for node_id in lazy_graph.index_to_node_id], dtype=np.int64)

    without_db = build_turn_expanded_structure(csr, lazy_graph, bearings, ranks, spec)
    with_db = build_turn_expanded_structure(
        csr, lazy_graph, bearings, ranks, spec, node_db_rank=db_rank)
    lower_db = build_turn_expanded_structure(
        csr, lazy_graph, bearings, np.full(len(lazy_graph.edge_ids), 4, dtype=np.int64), spec,
        node_db_rank=np.zeros(len(lazy_graph.index_to_node_id), dtype=np.int64))

    assert _straight_cost(without_db, lazy_graph) == 0.0, "部分グラフだけでは幹線が見えない"
    assert _straight_cost(with_db, lazy_graph) == spec.major_crossing_seconds
    assert _straight_cost(lower_db, lazy_graph) == 0.0, "未集計の0が導出値を下げてはならない"


def test_one_to_all_gives_the_distance_along_the_path_when_turns_are_free():
    """ターンの費用が0なら、Nodeごとのコストは経路上の区間の所要時間の和になる。

    畳み込みは`build_turn_expanded_tree`が木を作るときに済ませている（`node_cost`）。
    """
    graph = _crossroads()
    free = TurnCostSpec(left_seconds=0.0, right_seconds=0.0, uturn_seconds=0.0)
    lazy_graph, csr, tree = _tree_for(graph, "S", free)

    assert tree.node_cost[lazy_graph.node_id_to_index["C"]] == pytest.approx(100.0 / SPEED_MS)
    for node_id in ("N", "E", "W"):
        assert tree.node_cost[lazy_graph.node_id_to_index[node_id]] == pytest.approx(200.0 / SPEED_MS)
    # 起点は「戻ってくるコスト」になる（状態の空間に「まだ走っていない」が無いため）。
    assert tree.node_cost[lazy_graph.node_id_to_index["S"]] == pytest.approx(200.0 / SPEED_MS)


def test_crossing_a_minor_road_from_a_cycleway_does_not_add_the_major_crossing_cost():
    """自転車道から生活道路・サービス道路へ出るだけでは、横断の費用を足さない。

    判定を「自分より上位か」だけにすると、自転車道（階級表に無く0）から
    サービス道路（1）へ出る形がすべて成立する。ここが足すのは「車列の切れ目を待つ時間」で、
    通過交通の無い道を横切るのに待ちは要らない（`MAJOR_CROSSING_MIN_RANK`）。
    """
    graph, lazy_graph, csr = _major_crossing_fixture()
    spec = TurnCostSpec(left_seconds=0.0, right_seconds=0.0, major_crossing_seconds=8.0)
    bearings = edge_bearings(graph, lazy_graph)
    no_signal = np.zeros(len(lazy_graph.index_to_node_id), dtype=bool)

    # 直進する側が自転車道（0）、交差する側がサービス道路（1）。
    minor = np.array(
        [1 if edge_id in ("P1-C", "C-P2") else 0 for edge_id in lazy_graph.edge_ids], dtype=np.int64)
    # 交差する側だけをtertiary（MAJOR_CROSSING_MIN_RANK）へ上げた対照。
    major = np.array(
        [MAJOR_CROSSING_MIN_RANK if edge_id in ("P1-C", "C-P2") else 0
         for edge_id in lazy_graph.edge_ids], dtype=np.int64)

    crossing_minor = build_turn_expanded_structure(
        csr, lazy_graph, bearings, minor, spec, node_has_signal=no_signal)
    crossing_major = build_turn_expanded_structure(
        csr, lazy_graph, bearings, major, spec, node_has_signal=no_signal)

    assert _straight_cost(crossing_minor, lazy_graph) == 0.0
    assert _straight_cost(crossing_major, lazy_graph) == spec.major_crossing_seconds
