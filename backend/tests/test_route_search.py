"""探索エンジンが呼ぶ domain の判断のうち、配列だけで確かめられる計算（`domain/route_search.py`と、
`domain/route.py`の形状・標高、`domain/routing.py`の繋ぎ目の候補）。

対象は、入力を配列や値で直接与えられるもの。

- 表示値の部品（ジオメトリの連結・標高の集約と逆回りの付け替え・候補の難易度の比較）
- 探索の部品（繋ぎ目の候補・同点グループの試行順・中継点の帯）

ここでは見ないもの:

- 道路網から経路を作る一連の振る舞い（スナップ・周回・目的地・経由地・候補の選び方・区間の表示）
  → `test_route_generation_behavior.py`（公開の入口`RouteGenerator`から、小さな道路網で確かめる）。
  エンジンの途中状態（`_RoadGraphContext`等）を手で組むテストはここに置かない——道路網の持ち方や
  組み立てを作り替えるたびに足場ごと書き直すことになり、振る舞いは何も守らない。
- 起点・終点の状態の引き方（CSR／遷移構造からの索引）→ 周回・目的地の経路が起点に戻る・目的地へ着くことで
  `test_route_generation_behavior.py`が通す。
- 標高属性の逆向き（`ElevationAttribute.reversed_as`）→ `test_attributes.py`。候補の難易度の距離加重平均
  （`distance_weighted_difficulty`）→ `test_difficulty.py`。
- レグごとのコスト配列の合成（`domain/leg_costs.py`）→ `test_leg_costs.py`。
- 探索カーネル（`domain/routing.py`）・評価軸（`domain/evaluation.py`）・走行モデル
  （`domain/cycling_speed.py`）・風（`domain/wind.py`）・0次フィルタ（`domain/hard_filters.py`）
  → それぞれの持ち主のテストが持つ。

このファイルが組み立てて渡し、読むデータ型（探索構造・`RouteCandidate`等）は本物で作る——代役にしても
何も切り離せず、本物が変わったときに黙ってずれるだけになる。
"""


import numpy as np
import pytest

from app.domain.attributes import ElevationAttribute
from app.domain.graph import LeanEdge
from app.domain.route import (
    RouteCandidate,
    RouteSegmentDetail,
    concat_edge_geometries,
    reverse_elevation_by_edge,
    route_elevation_gain,
)
from app.domain.routing import NodeJunction, TurnExpandedTree, add_terminal_candidate
from app.domain.route_search import (
    leg_of_edge_by_half,
    order_by_bearing_spread,
    pick_better_candidate,
    rank_by_pareto_layers,
    relay_band,
    reverse_leg_assignment,
    turnaround_ring_m,
)


# --------------------------------------------------------------------------------------
# 架空の世界（本物の型を、そのテストが読む値だけ埋めて作る）
# --------------------------------------------------------------------------------------


def lean_edge(edge_id, from_node_id="n0", to_node_id="n1", *, distance_m=100.0, geometry=None):
    """探索用グラフの区間と同じく、`geometry`を省くと空のプレースホルダになる。DBの区間の番号は
    ここを通るテストが読まないため、どの区間にも同じ値を入れる。"""
    return LeanEdge(
        edge_id=edge_id, from_node_id=from_node_id, to_node_id=to_node_id,
        geometry=[] if geometry is None else geometry, distance_m=distance_m,
        osm_way_id=1, segment_index=0, forward=True,
    )


def elevation(edge_id, **fields):
    """テストが名指さない欄は、獲得・喪失標高は0m、勾配は値が取れなかった（None）として埋める。"""
    ends = {"elevation_gain_m": 0.0, "elevation_loss_m": 0.0}
    grades = dict.fromkeys(ElevationAttribute.model_fields.keys() - {"edge_id"} - ends.keys())
    return ElevationAttribute(edge_id=edge_id, **{**ends, **grades, **fields})


def turn_tree(state_count, *, node_cost, node_length_m, node_seconds, node_best_state):
    """一対全木。エンジンが読むのはNode側だけで、状態側を辿る経路の復元は各テストが差し替えるため、
    状態側はどの状態にも届いていない値（inf・NaN・-1）で埋める。"""
    return TurnExpandedTree(
        state_cost=np.full(state_count, np.inf),
        state_length_m=np.full(state_count, np.nan), state_seconds=np.full(state_count, np.nan),
        node_cost=np.asarray(node_cost, dtype=float), node_best_state=np.asarray(node_best_state, dtype=np.int64),
        node_length_m=np.asarray(node_length_m, dtype=float), node_seconds=np.asarray(node_seconds, dtype=float),
        predecessor_list=[-1] * state_count,
    )


def segment_detail(difficulty, distance_km):
    return RouteSegmentDetail(
        start_latitude=35.0, start_longitude=139.0, end_latitude=35.0, end_longitude=139.0,
        cumulative_distance_km=0.0, distance_km=distance_km, difficulty=difficulty,
    )


def route_candidate(name, segments=()):
    """`name`は候補を見分けるためだけのid。"""
    return RouteCandidate(id=name, direction_label=name, distance_km=1.0, geometry={}, segments=list(segments))


# --------------------------------------------------------------------------------------
# ジオメトリの連結と境界点
# --------------------------------------------------------------------------------------


def test_concat_edge_geometries_offsets_slice_back_to_each_edge():
    """隣接Edgeの境界点を二重に持たせない（線が同じ点で折り返して見える）ため、境界の位置は座標列からは
    復元できない。offsetsが各Edgeの形状を切り出せること。"""
    edges = [
        lean_edge("e1", geometry=[[35.0, 139.0], [35.1, 139.1], [35.2, 139.2]]),
        lean_edge("e2", geometry=[[35.2, 139.2], [35.3, 139.3]]),
    ]
    geometry, offsets = concat_edge_geometries(edges)
    coordinates = geometry["coordinates"]

    assert coordinates[offsets[0]:offsets[1] + 1] == [[139.0, 35.0], [139.1, 35.1], [139.2, 35.2]]
    assert coordinates[offsets[1]:offsets[2] + 1] == [[139.2, 35.2], [139.3, 35.3]]


def test_concat_edge_geometries_keeps_both_points_when_edges_do_not_touch():
    edges = [
        lean_edge("e1", geometry=[[35.0, 139.0]]),
        lean_edge("e2", geometry=[[36.0, 140.0]]),
    ]
    geometry, _ = concat_edge_geometries(edges)
    assert geometry["coordinates"] == [[139.0, 35.0], [140.0, 36.0]]


# --------------------------------------------------------------------------------------
# 標高の集約と、逆回りの区間への付け替え
# --------------------------------------------------------------------------------------


def test_route_elevation_gain_sums_only_present_values():
    """標高の無い区間は集計の母集団から外す。"""

    edges = [lean_edge("e1"), lean_edge("e2"), lean_edge("e3"), lean_edge("e4")]
    attributes = {
        "e1": elevation("e1", elevation_gain_m=10.0),
        "e4": elevation("e4", elevation_gain_m=2.0),
    }

    assert route_elevation_gain(edges, attributes) == 12.0


def test_route_elevation_gain_without_any_value_is_none_not_zero():
    """標高が1つも取れなかった経路は、0mではなく「取れなかった」として返す。"""
    assert route_elevation_gain([lean_edge("e1")], {}) is None


def test_reverse_elevation_by_edge_pairs_the_path_in_reverse_order():
    """逆方向Edgeの並びは順方向の逆。対応がずれると別の坂の値が付く。"""
    forward_edges = [lean_edge("f1"), lean_edge("f2")]
    reverse_edges = [lean_edge("r2"), lean_edge("r1")]
    attributes = {"f2": elevation("f2", elevation_gain_m=1.0, elevation_loss_m=9.0)}

    result = reverse_elevation_by_edge(forward_edges, reverse_edges, attributes)

    assert set(result) == {"r2"}
    assert result["r2"].elevation_gain_m == 9.0


# --------------------------------------------------------------------------------------
# レグ番号の振り直しと、順方向／逆回りの採否
# --------------------------------------------------------------------------------------


def test_reverse_leg_assignment_renumbers_as_well_as_reverses():
    """並びだけ反転すると、走り始めを帰着時刻の風で評価することになる。"""
    assert reverse_leg_assignment([0, 0, 0, 1, 1]) == [0, 0, 1, 1, 1]


@pytest.mark.parametrize(
    ("weights", "expected"),
    [
        ([1.0, 1.0, 1.0, 1.0], [0, 0, 1, 1]),  # 半分ちょうどから始まる区間は復路
        ([1.0, 2.0, 1.0], [0, 0, 1]),  # 半分をまたぐ区間は往路
    ],
)
def test_leg_of_edge_by_half_switches_where_the_accumulated_weight_reaches_half(weights, expected):
    """境目がずれると、帰りの時刻の風で評価する区間が変わる。"""
    assert leg_of_edge_by_half(weights) == expected


@pytest.mark.parametrize(
    ("forward_difficulty", "reverse_difficulty", "picked"),
    [
        (5.0, 3.0, "reverse"),
        (3.0, 5.0, "forward"),
        # 比較できないときは「逆回りの方が良い」と読まない（安全側）
        (5.0, None, "forward"),
        (None, 7.0, "reverse"),
    ],
)
def test_pick_better_candidate_takes_the_lower_difficulty(forward_difficulty, reverse_difficulty, picked):
    """難易度は区間から求める。区間が無い候補は比較できない。"""
    def candidate(name, difficulty):
        return route_candidate(name, segments=[] if difficulty is None else [segment_detail(difficulty, 1.0)])

    forward = candidate("forward", forward_difficulty)
    reverse = candidate("reverse", reverse_difficulty)

    assert pick_better_candidate(forward, reverse).id == picked


# --------------------------------------------------------------------------------------
# 目的地そのものを経由Nodeとする候補
# --------------------------------------------------------------------------------------


def make_junction(count):
    return NodeJunction(
        cost=np.full(count, np.inf), length_m=np.zeros(count), seconds=np.zeros(count),
        forward_state=np.full(count, -1, dtype=np.int64),
        backward_state=np.full(count, -1, dtype=np.int64),
    )


def test_add_terminal_candidate_copies_every_field_from_the_forward_tree():
    """1つでも繋ぎ目側の値が残ると、difficultyの逆算が別経路のコストと秒で行われる。"""
    junction = make_junction(2)
    junction.cost[1] = 999.0
    junction.length_m[1] = 111.0
    junction.seconds[1] = 222.0
    junction.backward_state[1] = 42
    forward = turn_tree(
        4, node_cost=[0.0, 5.0], node_length_m=[0.0, 60.0], node_seconds=[0.0, 4.0], node_best_state=[-1, 3],
    )

    add_terminal_candidate(junction, forward, 1)

    assert junction.cost[1] == 5.0
    assert junction.length_m[1] == 60.0
    assert junction.seconds[1] == 4.0
    assert junction.forward_state[1] == 3
    assert junction.backward_state[1] == -1


def test_add_terminal_candidate_does_nothing_when_the_forward_tree_never_arrived():
    junction = make_junction(2)
    forward = turn_tree(
        4, node_cost=[0.0, np.inf], node_length_m=[0.0, np.nan], node_seconds=[0.0, np.nan], node_best_state=[-1, -1],
    )

    add_terminal_candidate(junction, forward, 1)

    assert not np.isfinite(junction.cost[1])
    assert junction.forward_state[1] == -1


# --------------------------------------------------------------------------------------
# 同点グループ内の試行順（方位の散らし）
# --------------------------------------------------------------------------------------


def test_order_by_bearing_spread_uses_ring_centre_closeness_before_anything_is_selected():
    order = order_by_bearing_spread(
        [10, 11, 12], [], {10: 0.0, 11: 90.0, 12: 180.0}, {10: 500.0, 11: 10.0, 12: 100.0}
    )
    assert order == [11, 12, 10]


def test_order_by_bearing_spread_puts_the_most_distant_bearing_on_the_circle_first():
    """同点候補が同じ方角に並ぶと、周回一覧が「似た向き」ばかりになる。方位の差は360度を跨ぐ——単純な
    引き算だと350度と10度が「遠い」と誤判定される。"""
    order = order_by_bearing_spread(
        [10, 11], [99], {10: 10.0, 11: 90.0, 99: 350.0}, {10: 0.0, 11: 0.0}
    )
    assert order == [11, 10]


def test_order_by_bearing_spread_breaks_ties_by_node_index():
    order = order_by_bearing_spread(
        [12, 11], [99], {11: 90.0, 12: 90.0, 99: 0.0}, {11: 5.0, 12: 5.0}
    )
    assert order == [11, 12]


# --------------------------------------------------------------------------------------
# 候補の並べ方と、折返し点を探す範囲
# --------------------------------------------------------------------------------------


def _ranked_ids(ids, distance, difficulty, *, tie_by_distance):
    seconds = np.full(len(ids), 100.0)
    ranking = rank_by_pareto_layers(
        np.array(ids), np.array(distance, dtype=float), seconds * (1 + np.array(difficulty) / 100), seconds, 1.0,
        max_items=10, max_examined=10, tie_by_distance=tie_by_distance,
    )
    return np.array(ids)[ranking.order].tolist()


def test_rank_puts_the_pareto_layer_before_the_difficulty():
    """遠回りして難所を避けた候補（7）だけが上位を占めず、近くて難所を通る候補（5）も一覧に残る。
    両方に負ける候補（9）は難易度が真ん中でも後ろへ回る。"""
    assert _ranked_ids([5, 7, 9], [0.0, 2000.0, 2000.0], [50.0, 10.0, 30.0], tie_by_distance=False) == [7, 5, 9]


@pytest.mark.parametrize(("tie_by_distance", "expected"), [(True, [8, 3]), (False, [3, 8])])
def test_rank_breaks_ties_by_distance_only_when_asked(tie_by_distance, expected):
    """同じ層・同じ難易度の中は、周回なら距離の鍵（リング中心からのずれ）の順、目的地なら番号の順。"""
    assert _ranked_ids([3, 8], [60.0, 10.0], [20.0, 20.0], tie_by_distance=tie_by_distance) == expected


def test_turnaround_ring_falls_back_to_half_the_loop_when_the_tolerance_is_too_narrow():
    """許容が狭いと`[(目標-許容)/MIN, (目標+許容)/MAX]`が逆転し、折返し点が1つも見つからない。"""
    lower_m, upper_m, _ = turnaround_ring_m(10.0, 0.5)
    assert (lower_m, upper_m) == (4750.0, 5250.0)


@pytest.mark.parametrize(
    ("outbound_m", "shortest_m", "in_band"),
    [
        (3000.0, 4000.0, True),  # 見込み9.0〜10.2km: 下端がちょうど目標−許容
        (2900.0, 4000.0, False),  # 下端8.9kmが目標−許容より短い
        (3000.0, 4700.0, False),  # 上端11.1kmが目標＋許容より長い
        # 見込みの幅（帰り7km×0.3）が許容の幅より広いので、帰りを最短のまま見る（10.0km）。幅のままだと上端12.1kmで外れる
        (1000.0, 7000.0, True),
        (3000.0, np.nan, False),  # 終点へ届かない中継点
        (np.nan, 4000.0, False),  # 最後の固定点から届かない中継点
    ],
)
def test_relay_band_takes_relays_whose_whole_estimate_of_the_route_fits_the_distance(outbound_m, shortest_m, in_band):
    """目標10km±1km、前段2km。全長の見込みは前段＋往路＋帰りの最短×1.0〜1.3。帯から外れた中継点を選ぶと、帰りを
    探したあとの距離フィルタで落ち、候補が減る。"""
    (inside,), _ = relay_band(2000.0, np.array([outbound_m]), np.array([shortest_m]), 10.0, 1.0)
    assert bool(inside) is in_band


def test_relay_band_ranks_relays_by_how_far_the_middle_of_the_estimate_is_from_the_target():
    """見込みの中央（帰り×1.15）が目標から遠いほど後ろに並ぶ。短すぎる経路も長すぎる経路も同じに扱う。"""
    _, closeness_m = relay_band(2000.0, np.array([3000.0, 3000.0]), np.array([4000.0, 4000.0 + 800.0 / 1.15]), 10.0, 1.0)
    assert closeness_m == pytest.approx([400.0, 400.0])
