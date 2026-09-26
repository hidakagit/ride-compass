"""`domain/road_network.py`——道路網全体の配列から、範囲・材料・区間の行・標高属性を取り出す。

ここで見ないもの:
- DBから配列を作る・ディスクへ置く → `test_road_network_store.py`
- 切り出した範囲で経路を探す → `test_route_generation_behavior.py`

道路網は3本の道（東西に並ぶ2本と、離れた所の1本）を持つ小さなもの。材料は**性質だけを表す架空のid**で与え、
勾配だけは標高属性が材料の列から平均勾配を引くため実idを使う。
"""

import numpy as np

from app.domain.material_catalog import GRADIENT_PERCENT
from app.domain.road_network import RoadNetwork, edge_row_of, elevation_attribute, material_arrays_of, slice_network

CAT_A = "cat_a"

#: ノード（osm_node_id, 緯度, 経度）。4と5は他から離れている。
NODES = [(1, 35.00, 139.00), (2, 35.00, 139.01), (3, 35.00, 139.02), (4, 36.00, 140.00), (5, 36.00, 140.01)]
#: 有向の区間（道, 区間番号, 順方向か, 始点, 終点）。道20は一方通行。行の並びは(道, 区間番号, 順→逆)。
EDGES = [(10, 0, True, 1, 2), (10, 0, False, 2, 1), (20, 0, True, 2, 3), (30, 0, True, 4, 5), (30, 0, False, 5, 4)]


def network(*, grades=None, elevation_present=None, starts=None) -> RoadNetwork:
    n = len(EDGES)
    node_ids = [i for i, _lat, _lon in NODES]
    row_of = {osm: i for i, osm in enumerate(node_ids)}
    lat = np.array([lat for _i, lat, _lon in NODES])
    lon = np.array([lon for _i, _lat, lon in NODES])
    tail = np.array([row_of[a] for _w, _s, _f, a, _b in EDGES], dtype=np.int32)
    head = np.array([row_of[b] for _w, _s, _f, _a, b in EDGES], dtype=np.int32)
    grades = grades if grades is not None else [1.0] * n
    return RoadNetwork(
        revision=1,
        node_osm_id=np.array(node_ids, dtype=np.int64), node_lat=lat, node_lon=lon,
        node_has_signals=np.zeros(len(NODES), dtype=bool), node_max_rank=np.zeros(len(NODES), dtype=np.int64),
        edge_way_id=np.array([w for w, *_ in EDGES], dtype=np.int64),
        edge_segment=np.array([s for _w, s, *_ in EDGES], dtype=np.int32),
        edge_forward=np.array([f for _w, _s, f, *_ in EDGES]),
        edge_from=tail, edge_to=head,
        edge_highway=np.zeros(n, dtype=np.int16), highway_vocab=(None,),
        edge_min_lon=np.minimum(lon[tail], lon[head]), edge_min_lat=np.minimum(lat[tail], lat[head]),
        edge_max_lon=np.maximum(lon[tail], lon[head]), edge_max_lat=np.maximum(lat[tail], lat[head]),
        numeric_ids=(GRADIENT_PERCENT,), numeric_values=np.array(grades, dtype=float).reshape(-1, 1),
        boolean_ids=(), boolean_values=np.zeros((n, 0), dtype=bool),
        categorical_ids=(CAT_A,), categorical_codes=np.array([[1], [1], [0], [2], [2]], dtype=np.int16),
        categorical_vocab=((None, "x", "y"),),
        hard_filter_ids=(), hard_filter_flags=np.zeros((n, 0), dtype=bool),
        distance_m=np.full(n, 900.0), bearing_deg=np.full(n, 90.0),
        mid_lat=(lat[tail] + lat[head]) / 2, mid_lon=(lon[tail] + lon[head]) / 2,
        elevation_present=np.array(elevation_present if elevation_present is not None else [True] * n),
        elevation_start_m=np.array(starts if starts is not None else [0.0] * n, dtype=float),
        elevation_end_m=np.full(n, 5.0), elevation_gain_m=np.full(n, 5.0), elevation_loss_m=np.full(n, 0.0),
        elevation_max_grade=np.full(n, 7.0), elevation_min_grade=np.full(n, -1.0),
    )


class TestSlice:
    def test_edges_whose_extent_meets_the_range_are_taken_with_their_endpoints(self):
        """範囲の端に掛かる区間は、範囲の外にある端点ごと取る（端点の無い区間は探索に載らない）。"""
        road = slice_network(network(), 139.005, 34.99, 139.015, 35.01)

        assert road.rows.tolist() == [0, 1, 2]
        osm = road.network.node_osm_id
        assert [(int(osm[road.nodes[a]]), int(osm[road.nodes[b]])) for a, b in zip(road.edge_from, road.edge_to)] == [
            (1, 2), (2, 1), (2, 3)]

    def test_nodes_are_renumbered_to_the_ones_the_range_uses(self):
        road = slice_network(network(), 139.99, 35.99, 140.02, 36.01)

        assert road.rows.tolist() == [3, 4]
        assert road.node_count == 2
        assert sorted(road.node_lat.tolist()) == [36.0, 36.0]

    def test_materials_follow_the_rows_of_the_range_and_categories_become_values_again(self):
        road = slice_network(network(grades=[1.0, 2.0, 3.0, 4.0, 5.0]), 139.99, 35.99, 140.02, 36.01)

        materials = material_arrays_of(road)

        assert materials.numeric_values[:, 0].tolist() == [4.0, 5.0]
        assert materials.categorical_values[:, 0].tolist() == ["y", "y"]


class TestEdgeRow:
    def test_a_directed_edge_is_found_by_its_way_segment_and_direction(self):
        assert edge_row_of(network(), 10, 0, False) == 1
        assert edge_row_of(network(), 30, 0, True) == 3

    def test_the_reverse_of_a_one_way_road_and_an_unknown_way_are_not_found(self):
        assert edge_row_of(network(), 20, 0, False) is None
        assert edge_row_of(network(), 99, 0, True) is None


class TestElevationAttribute:
    def test_an_edge_without_computed_elevation_has_no_attribute(self):
        """0で埋めて返すと、標高が未計算の区間が「平坦」として表示される。"""
        net = network(elevation_present=[True, False, True, True, True])

        assert elevation_attribute(net, 0, "a") is not None
        assert elevation_attribute(net, 1, "b") is None

    def test_the_average_grade_comes_from_the_gradient_material(self):
        """標高の列とは別に、勾配は材料として持っている。別の列を引くと平均勾配だけが常に空になる。"""
        net = network(grades=[3.5, -2.0, 0.0, 0.0, 0.0])

        assert elevation_attribute(net, 0, "a").average_grade == 3.5
        assert elevation_attribute(net, 1, "b").average_grade == -2.0

    def test_the_row_is_read_at_its_own_index(self):
        assert elevation_attribute(network(starts=[1.0, 2.0, 3.0, 4.0, 5.0]), 2, "c").start_elevation_m == 3.0

    def test_a_missing_number_becomes_none_instead_of_nan(self):
        """NaNをそのまま応答へ載せるとJSONにできない。フィールドごとに独立して欠損しうる。"""
        attribute = elevation_attribute(network(grades=[np.nan] * 5, starts=[np.nan] * 5), 0, "a")

        assert attribute.average_grade is None
        assert attribute.start_elevation_m is None
        assert attribute.end_elevation_m == 5.0
