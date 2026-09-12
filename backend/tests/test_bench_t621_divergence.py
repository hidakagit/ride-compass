"""分岐点算出（`benchmarks/_divergence.py`）の単体テスト。

実データでの計測はローカルPostGISが要る（`benchmarks/bench_t621_divergence.py`）が、
Edge id列から分岐点を求める部分は接続無しで固定できる。
"""

from benchmarks._divergence import DivergencePoint, divergence_points, spliced_path
from benchmarks.bench_t621_divergence import _cumulative_km, _difference_km, _is_connected, _redundancy


def test_identical_paths_have_no_divergence_point():
    assert divergence_points(["a", "b", "c"], {"B": ["a", "b", "c"]}) == []


def test_paths_that_differ_from_the_start_diverge_at_the_origin():
    points = divergence_points(["a", "b"], {"B": ["x", "y"]})

    assert points == [DivergencePoint(index=0, after_edge_id=None, targets=("B",))]


def test_divergence_is_reported_after_the_last_shared_edge():
    points = divergence_points(["a", "b", "c"], {"B": ["a", "x", "y"]})

    assert points == [DivergencePoint(index=1, after_edge_id="a", targets=("B",))]


def test_paths_that_rejoin_and_split_again_report_both_points():
    displayed = ["a", "b", "c", "d", "e"]
    # bの次でcではなくpへ、その後dで合流し、dの次でeではなくqへ分かれる
    other = ["a", "b", "p", "d", "q"]

    points = divergence_points(displayed, {"B": other})

    assert [(p.index, p.after_edge_id) for p in points] == [(2, "b"), (4, "d")]


def test_targets_sharing_one_point_are_grouped_into_a_single_marker():
    points = divergence_points(["a", "b"], {"B": ["a", "x"], "C": ["a", "y"]})

    assert len(points) == 1
    assert points[0].after_edge_id == "a"
    assert sorted(points[0].targets) == ["B", "C"]


def test_no_divergence_when_the_shared_edge_is_the_last_of_the_other_path():
    # 相手はaで終点に着くため、aの直後に乗り換える先が無い
    assert divergence_points(["a", "b"], {"B": ["a"]}) == []


def test_repeated_edge_uses_the_first_traversal():
    points = divergence_points(["a", "b"], {"B": ["a", "x", "a", "y"]})

    assert points == [DivergencePoint(index=1, after_edge_id="a", targets=("B",))]


def test_repeated_edge_reports_a_divergence_even_when_the_last_traversal_agrees():
    # 相手はaを2回通り、2回目の直後はdisplayedと同じbへ進む。最初の通過ではxへ
    # 分かれるため、aの直後はxを経てbへ戻る乗り換え先として成立する。
    displayed = ["a", "b"]
    target = ["a", "x", "a", "b"]

    points = divergence_points(displayed, {"B": target})

    assert points == [DivergencePoint(index=1, after_edge_id="a", targets=("B",))]
    assert spliced_path(displayed, target, points[0]) == ["a", "x", "a", "b"]


def test_spliced_path_joins_the_displayed_prefix_with_the_target_suffix():
    displayed = ["a", "b", "c"]
    target = ["a", "x", "y"]
    point = divergence_points(displayed, {"B": target})[0]

    assert spliced_path(displayed, target, point) == ["a", "x", "y"]


def test_spliced_path_at_the_origin_is_the_target_itself():
    displayed = ["a", "b"]
    target = ["x", "y"]
    point = divergence_points(displayed, {"B": target})[0]

    assert spliced_path(displayed, target, point) == ["x", "y"]


def test_spliced_path_keeps_the_displayed_prefix_when_diverging_later():
    displayed = ["a", "b", "c", "d"]
    target = ["a", "b", "x", "y"]
    point = divergence_points(displayed, {"B": target})[0]

    assert spliced_path(displayed, target, point) == ["a", "b", "x", "y"]


class _FakeEdge:
    def __init__(self, from_node_id: str, to_node_id: str, distance_m: float):
        self.from_node_id = from_node_id
        self.to_node_id = to_node_id
        self.distance_m = distance_m


class _FakeGraph:
    def __init__(self, edges: dict[str, _FakeEdge]):
        self.edges = edges


_GRAPH = _FakeGraph(
    {
        "a": _FakeEdge("n0", "n1", 1000.0),
        "b": _FakeEdge("n1", "n2", 2000.0),
        "detached": _FakeEdge("n9", "n2", 500.0),
        "c": _FakeEdge("n2", "n3", 100.0),
        "d": _FakeEdge("n3", "n4", 100.0),
        "p": _FakeEdge("n1", "n2", 300.0),
        "q": _FakeEdge("n3", "n4", 100.0),
    }
)


def test_connectivity_check_accepts_a_path_whose_edges_meet_at_a_node():
    assert _is_connected(_GRAPH, ["a", "b"]) is True


def test_connectivity_check_rejects_a_path_with_a_gap():
    assert _is_connected(_GRAPH, ["a", "detached"]) is False


def test_cumulative_distance_sums_the_edges_before_the_divergence_point():
    assert _cumulative_km(_GRAPH, ["a", "b"], 0) == 0.0
    assert _cumulative_km(_GRAPH, ["a", "b"], 1) == 1.0
    assert _cumulative_km(_GRAPH, ["a", "b"], 2) == 3.0


def test_difference_counts_the_road_that_only_one_path_uses():
    # aは共通、bは左だけ（2.0km）、detachedは右だけ（0.5km）
    assert _difference_km(_GRAPH, ["a", "b"], ["a", "detached"]) == 2.5


def test_difference_is_zero_for_the_same_path():
    assert _difference_km(_GRAPH, ["a", "b"], ["a", "b"]) == 0.0


def test_redundancy_compares_consecutive_markers_that_offer_the_same_target():
    displayed = ["a", "b"]
    paths = {"B": ["a", "detached"]}
    points = divergence_points(displayed, paths)
    # 乗り換え先Bを持つマーカーが1つしか無いので、比べる組が無い
    assert _redundancy(_GRAPH, displayed, paths, points) == []


def test_redundancy_measures_how_different_the_two_markers_routes_are():
    # 表示中と相手はaで分かれ、cで合流し、cの直後でまた分かれる（マーカー2個、どちらもB宛て）
    displayed = ["a", "b", "c", "d"]
    paths = {"B": ["a", "p", "c", "q"]}
    points = divergence_points(displayed, paths)

    assert len(points) == 2
    # 早い方はpを走りbを走らない、遅い方はその逆。差はp(0.3km)+b(2.0km)
    assert _redundancy(_GRAPH, displayed, paths, points) == [2.3]
