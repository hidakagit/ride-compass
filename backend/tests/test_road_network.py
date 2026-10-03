"""`domain/road_network.py`——取込範囲全体の道路網を番号で引く配列と、その切り出し。

入口は次のとおり。
- `RoadNetwork`: 組み立てた時点で行数・列数の食い違いを断る
- `slice_network`: 範囲に掛かる区間と、その両端のノードを取り出す
- `material_arrays_of`: 切り出した区間の材料
- `elevation_attribute`: 1区間の標高属性
- `edge_row_of`: `(道, 区間番号, 向き)`から区間の行

ここで見ないもの:
- 道路網をDBから組み立てて置いておくこと → `test_road_network_store.py`
- 材料の列の型（`EdgeMaterialArrays`・`CategoricalColumn`・`ElevationAttribute`）の振る舞い → `test_attributes.py`
- 切り出した範囲で経路を探すこと → `test_route_generation_behavior.py`

材料の名前は架空（`num_a` 等）。平均勾配だけは区間の材料の列から読むため、その材料の名前を対象の名前空間から読む。
"""

from dataclasses import replace

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain import road_network
from app.domain.road_network import RoadNetwork, edge_row_of, elevation_attribute, material_arrays_of, slice_network

NAN = float("nan")
GRADE = road_network.GRADIENT_PERCENT

# ノード（osm_node_id の昇順）。すべて北緯35度の上に東西に並ぶ。
NODES = [
    (100, 139.000),
    (101, 139.004),
    (102, 139.010),
    (103, 139.020),
    (104, 139.100),
    (105, 139.120),
    (106, 139.140),
]
# 区間（道・区間番号の昇順、同じ区間は順方向が先）: (道, 区間番号, 順方向, 始点の行, 終点の行)。
# 道10は両方向、道20は一方通行、道30は区間が2つの一方通行。
EDGES = [
    (10, 0, True, 0, 1),
    (10, 0, False, 1, 0),
    (20, 0, True, 2, 3),
    (30, 0, True, 4, 5),
    (30, 1, True, 5, 6),
]


def network() -> RoadNetwork:
    """西に道10・道20（139.00〜139.02E）、東に道30（139.10〜139.14E）がある道路網。"""
    lat = np.full(len(NODES), 35.0)
    lon = np.array([node_lon for _, node_lon in NODES])
    edge_from = np.array([tail for *_, tail, _ in EDGES], dtype=np.int32)
    edge_to = np.array([head for *_, head in EDGES], dtype=np.int32)
    n = len(EDGES)
    row = np.arange(n, dtype=np.float64)
    return RoadNetwork(
        revision=7,
        node_osm_id=np.array([osm_id for osm_id, _ in NODES], dtype=np.int64),
        node_lat=lat,
        node_lon=lon,
        node_has_signals=np.zeros(len(NODES), dtype=bool),
        node_max_rank=np.zeros(len(NODES), dtype=np.int64),
        edge_way_id=np.array([way for way, *_ in EDGES], dtype=np.int64),
        edge_segment=np.array([segment for _, segment, *_ in EDGES], dtype=np.int32),
        edge_forward=np.array([forward for _, _, forward, *_ in EDGES], dtype=bool),
        edge_from=edge_from,
        edge_to=edge_to,
        edge_highway=np.ones(n, dtype=np.int16),
        highway_vocab=(None, "residential"),
        edge_min_lon=np.minimum(lon[edge_from], lon[edge_to]),
        edge_min_lat=np.minimum(lat[edge_from], lat[edge_to]),
        edge_max_lon=np.maximum(lon[edge_from], lon[edge_to]),
        edge_max_lat=np.maximum(lat[edge_from], lat[edge_to]),
        numeric_ids=("num_a", GRADE),
        numeric_values=np.column_stack([row * 10, [3.0, -3.0, NAN, 1.5, 2.5]]),
        boolean_ids=("bool_a",),
        boolean_values=np.array([[True], [False], [True], [False], [True]]),
        categorical_ids=("cat_a",),
        categorical_codes=np.array([[1], [1], [2], [0], [2]], dtype=np.int16),
        categorical_vocab=((None, "x", "y"),),
        hard_filter_ids=("filter_a",),
        hard_filter_flags=np.array([[False], [False], [True], [False], [False]]),
        distance_m=row * 100 + 100,
        bearing_deg=np.array([90.0, 270.0, 90.0, 90.0, NAN]),
        mid_lat=lat[edge_from],
        mid_lon=(lon[edge_from] + lon[edge_to]) / 2,
        elevation_present=np.array([True, True, True, False, True]),
        elevation_start_m=np.array([10.0, 22.0, 5.0, NAN, NAN]),
        elevation_end_m=np.array([22.0, 10.0, 5.0, NAN, 8.0]),
        elevation_gain_m=np.array([12.0, 0.0, 0.0, NAN, NAN]),
        elevation_loss_m=np.array([0.0, 12.0, 0.0, NAN, NAN]),
        elevation_max_grade=np.array([4.0, -2.0, 0.0, NAN, NAN]),
        elevation_min_grade=np.array([2.0, -4.0, 0.0, NAN, NAN]),
    )


def test_the_network_counts_its_nodes_and_edges():
    built = network()

    assert (built.node_count, built.edge_count) == (len(NODES), len(EDGES))


@pytest.mark.parametrize(
    "broken",
    [
        {"node_lat": np.zeros(len(NODES) - 1)},  # ノードの列が1行足りない
        {"distance_m": np.zeros(len(EDGES) + 1)},  # 区間の列が1行多い
        {"numeric_ids": ("num_a",)},  # 材料の行列の列数と名前の数が合わない
        {"hard_filter_ids": ()},
        {"categorical_vocab": ()},  # 分類の列に語彙が無い
    ],
)
def test_arrays_of_mismatched_shape_are_refused_where_they_are_built(broken):
    with pytest.raises(ValueError, match="道路網の配列の形"):
        replace(network(), **broken)


def test_a_slice_takes_the_edges_over_the_range_with_both_ends():
    """範囲は道10の途中だけに掛かるが、区間は両端のノードごと取る。"""
    road = slice_network(network(), 139.001, 34.99, 139.002, 35.01)

    assert road.rows.tolist() == [0, 1]
    assert road.node_lon.tolist() == [139.000, 139.004]
    assert road.node_lat.tolist() == [35.0, 35.0]
    assert (road.edge_count, road.node_count) == (2, 2)


def test_an_edge_touching_the_edge_of_the_range_is_taken():
    road = slice_network(network(), 139.020, 34.99, 139.100, 35.01)

    assert road.rows.tolist() == [2, 3]


def test_a_range_over_no_edge_is_an_empty_slice():
    road = slice_network(network(), 139.05, 34.99, 139.06, 35.01)

    assert (road.edge_count, road.node_count) == (0, 0)


def test_a_range_off_the_latitude_of_the_roads_takes_nothing():
    road = slice_network(network(), 138.0, 35.5, 140.0, 36.0)

    assert road.edge_count == 0


lons = st.floats(min_value=138.99, max_value=139.15, allow_nan=False)
lats = st.floats(min_value=34.98, max_value=35.02, allow_nan=False)


@given(lon_a=lons, lon_b=lons, lat_a=lats, lat_b=lats)
def test_a_slice_keeps_the_edges_and_their_ends_of_the_whole_network(lon_a, lon_b, lat_a, lat_b):
    """どの範囲でも、取る区間は各区間の両端を総当たりで範囲と比べた答えに一致し、切り出しの中の番号で引いた
    両端の座標は全体の区間の両端の座標に一致する。"""
    whole = network()
    min_lon, max_lon = sorted((lon_a, lon_b))
    min_lat, max_lat = sorted((lat_a, lat_b))

    road = slice_network(whole, min_lon, min_lat, max_lon, max_lat)

    expected = [
        index
        for index, (*_, tail, head) in enumerate(EDGES)
        if min(NODES[tail][1], NODES[head][1]) <= max_lon
        and max(NODES[tail][1], NODES[head][1]) >= min_lon
        and min_lat <= 35.0 <= max_lat
    ]
    assert road.rows.tolist() == expected
    assert road.nodes.tolist() == sorted({end for index in expected for end in EDGES[index][3:]})
    for position, global_row in enumerate(road.rows):
        assert road.node_lon[road.edge_from[position]] == whole.node_lon[whole.edge_from[global_row]]
        assert road.node_lon[road.edge_to[position]] == whole.node_lon[whole.edge_to[global_row]]


def test_the_materials_of_a_slice_follow_its_rows():
    road = slice_network(network(), 139.015, 34.99, 139.11, 35.01)

    materials = material_arrays_of(road)

    columns = materials.columns()
    assert len(materials) == 2
    assert columns["num_a"].tolist() == [20.0, 30.0]
    assert columns["bool_a"].tolist() == [True, False]
    assert [columns["cat_a"].value_at(i) for i in range(2)] == ["y", None]
    assert materials.hard_filter_columns()["filter_a"].tolist() == [True, False]
    assert materials.distance_m.tolist() == [300.0, 400.0]
    assert materials.elevation_present.tolist() == [True, False]


def test_the_elevation_attribute_reads_the_average_grade_from_the_material():
    attribute = elevation_attribute(network(), 0, "10:0:f")

    assert attribute is not None
    assert attribute.model_dump() == {
        "edge_id": "10:0:f",
        "start_elevation_m": 10.0,
        "end_elevation_m": 22.0,
        "elevation_gain_m": 12.0,
        "elevation_loss_m": 0.0,
        "average_grade": 3.0,
        "max_grade": 4.0,
        "min_grade": 2.0,
    }


def test_values_missing_in_the_arrays_are_none_in_the_attribute():
    attribute = elevation_attribute(network(), 4, "30:1:f")

    assert attribute is not None
    assert attribute.start_elevation_m is None
    assert attribute.end_elevation_m == 8.0
    assert attribute.max_grade is None
    assert attribute.average_grade == 2.5


def test_an_edge_without_computed_elevation_has_no_attribute():
    assert elevation_attribute(network(), 3, "30:0:f") is None


@pytest.mark.parametrize(
    ("way", "segment", "forward", "expected"),
    [
        (10, 0, True, 0),
        (10, 0, False, 1),
        (30, 1, True, 4),
        (20, 0, False, None),  # 一方通行の逆向き
        (30, 2, True, None),  # 道にその区間番号が無い
        (15, 0, True, None),  # 取込範囲に無い道
        (99, 0, True, None),
    ],
)
def test_an_edge_is_found_by_its_way_segment_and_direction(way, segment, forward, expected):
    assert edge_row_of(network(), way, segment, forward) == expected
