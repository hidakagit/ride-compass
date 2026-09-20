"""`road_graph_repository`のうち、DBを要さない契約。

このモジュールは読み取り専用で、仕事の大半はSQLの組み立てと行→オブジェクトの変換である。
ここで見るのは後者と、SQLの並び・向きの読み替えが宣言と食い違っていないこと。
"""

from types import SimpleNamespace

import shapely
from shapely.geometry import LineString

from app.infrastructure.road_graph_repository import MATERIAL_ARRAY_COLUMN_ORDER, _REVERSED_ELEVATION_COLUMNS, _rows_to_directed_edges, _topology_rows_to_road_graph, edge_key, node_key, parse_edge_feature_key, reversed_material_expression


def _node(osm_node_id: int, lat: float = 35.0, lon: float = 139.0):
    return SimpleNamespace(osm_node_id=osm_node_id, latitude=lat, longitude=lon,
                           has_traffic_signals=False, max_highway_rank=0)


def _edge(direction: str = "both", from_node: int = 1, to_node: int = 2):
    return SimpleNamespace(osm_way_id=100, segment_index=0,
                           from_node_id=from_node, to_node_id=to_node,
                           distance_m=50.0, bearing_deg=30.0, reverse_bearing_deg=210.0,
                           highway="residential", direction=direction)


# --- 鍵 ---------------------------------------------------------------------


def test_way丸ごとの鍵は区間の鍵として読まない():
    """タイルはway単位と区間単位の両方を同じ`feature_key`という名前で出す。"""
    assert parse_edge_feature_key("12345") is None


def test_区間の鍵として読めない文字列はNone():
    assert parse_edge_feature_key("way-abc") is None


def test_有向な枝の鍵は向きを含む():
    assert edge_key(100, 3, True) != edge_key(100, 3, False)
    assert node_key(42) == "osm-node-42"


# --- 向きの読み替え ---------------------------------------------------------

def test_対になる語を入れ替える():
    assert reversed_material_expression("start_elevation_m") == "m.end_elevation_m"
    assert reversed_material_expression("end_elevation_m") == "m.start_elevation_m"
    assert reversed_material_expression("elevation_gain_m") == "m.elevation_loss_m"
    assert reversed_material_expression("elevation_loss_m") == "m.elevation_gain_m"


def test_勾配は符号を返す():
    assert reversed_material_expression("average_grade") == "-m.average_grade"
    assert reversed_material_expression("max_grade") == "-m.min_grade"
    assert reversed_material_expression("min_grade") == "-m.max_grade"


def test_向きで変わらない列はNone():
    """`_m`で終わっても反転するとは限らない。距離は向きに依らない。"""
    for name in ("distance_m", "accident_count", "lc_water", "poi_signal", "osm_way_id"):
        assert reversed_material_expression(name) is None


def test_向きの読み替えは2回かけると元に戻る():
    """逆向きの逆向きは順方向。対応表が対になっていないとここで落ちる。"""
    for name, reversed_expression in _REVERSED_ELEVATION_COLUMNS.items():
        negated = reversed_expression.startswith("-")
        source = reversed_expression.lstrip("-").removeprefix("m.")
        back = _REVERSED_ELEVATION_COLUMNS[source]

        assert back.lstrip("-").removeprefix("m.") == name
        assert back.startswith("-") == negated


# --- 材料の配列 -------------------------------------------------------------

def test_材料の配列の並びが重複していない():
    """呼び出し側は位置で読む。同じ名前が2つあると、片方が黙って無視される。"""
    assert len(MATERIAL_ARRAY_COLUMN_ORDER) == len(set(MATERIAL_ARRAY_COLUMN_ORDER))


def test_材料の配列に向きで変わる列が入っている():
    """向きの読み替えを通った値が配列に載らないと、逆向きの枝が順方向の値を使う。"""
    for name in ("bearing_deg", "elevation_gain_m", "elevation_loss_m"):
        assert name in MATERIAL_ARRAY_COLUMN_ORDER


# --- 行からグラフを組む -----------------------------------------------------

def test_両方向の区間は2本の枝になる():
    graph = _topology_rows_to_road_graph([_edge("both")], [_node(1), _node(2)])

    assert set(graph.edges) == {edge_key(100, 0, True), edge_key(100, 0, False)}


def test_一方通行は走れる向きの枝だけを作る():
    forward_only = _topology_rows_to_road_graph([_edge("forward")], [_node(1), _node(2)])
    backward_only = _topology_rows_to_road_graph([_edge("backward")], [_node(1), _node(2)])

    assert set(forward_only.edges) == {edge_key(100, 0, True)}
    assert set(backward_only.edges) == {edge_key(100, 0, False)}


def test_逆向きの枝は端点が入れ替わる():
    graph = _topology_rows_to_road_graph([_edge("both")], [_node(1), _node(2)])
    forward = graph.edges[edge_key(100, 0, True)]
    backward = graph.edges[edge_key(100, 0, False)]

    assert (forward.from_node_id, forward.to_node_id) == (node_key(1), node_key(2))
    assert (backward.from_node_id, backward.to_node_id) == (node_key(2), node_key(1))


def test_端点のノードが揃わない区間は枝にしない():
    """bboxの外にあるノードは読まれない。片端しか無い枝を作ると探索が壊れる。"""
    graph = _topology_rows_to_road_graph([_edge("both")], [_node(1)])

    assert graph.edges == {}


# --- ジオメトリ付きの枝 -----------------------------------------------------

def test_逆向きの枝は形状点列が逆順になる():
    line = LineString([(139.0, 35.0), (139.1, 35.1), (139.2, 35.2)])
    row = SimpleNamespace(osm_way_id=100, segment_index=0, from_node_id=1, to_node_id=2,
                          distance_m=50.0, bearing_deg=30.0, reverse_bearing_deg=210.0,
                          wkb=shapely.to_wkb(line))

    edges = _rows_to_directed_edges([row], {(100, 0): [True, False]})

    forward = edges[edge_key(100, 0, True)].geometry
    backward = edges[edge_key(100, 0, False)].geometry
    assert forward == list(reversed(backward))
    assert forward[0] == [35.0, 139.0]


def test_要求した向きの枝だけを返す():
    line = LineString([(139.0, 35.0), (139.1, 35.1)])
    row = SimpleNamespace(osm_way_id=100, segment_index=0, from_node_id=1, to_node_id=2,
                          distance_m=50.0, bearing_deg=30.0, reverse_bearing_deg=210.0,
                          wkb=shapely.to_wkb(line))

    edges = _rows_to_directed_edges([row], {(100, 0): [False]})

    assert set(edges) == {edge_key(100, 0, False)}
