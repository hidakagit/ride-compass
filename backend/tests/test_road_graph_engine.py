"""探索のエンジン（`services/road_graph_engine.py`）のうち、値を受けて判断を返す部品を確かめる。

ここで見ないもの:
- 生成の結果（経路・区間の表示・所要時間）の性質 → `test_route_generation_behavior.py`
- 探索アルゴリズムそのもの → `test_routing.py`
"""

from app.services.road_graph_engine import FixedLegs


def test_the_finishing_legs_follow_the_placed_legs_in_order():
    """区間ごとのレグの添字で、区間の表示値と通過時刻を読むレグが決まる。経由地のあとの帰りが前の区間のレグを
    指すと、帰りの区間を出発時刻の値で見せる。"""
    fixed = FixedLegs(segments=[[10, 11], [12]], nodes=[0, 1, 2], length_m=3000.0)

    path, leg_of_edge = fixed.joined([20, 21], [30])

    assert path == [10, 11, 12, 20, 21, 30]
    assert leg_of_edge == [0, 0, 1, 2, 2, 3]
