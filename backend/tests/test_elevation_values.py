"""標高と勾配の値の規則（`compute_elevation_values`）。

配信元（https://maps.gsi.go.jp/development/hyokochi.html ）:
「元となる標高モデルデータ標高点の値は、地表面の測定値に基づいているため、構造物
（建物、高架橋等）の高さを反映したものではありません。」
"""

from app.domain.attributes import MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT, compute_elevation_values
from app.domain.route import Coordinates

A = Coordinates(latitude=35.700, longitude=139.700)
B = Coordinates(latitude=35.701, longitude=139.700)
C = Coordinates(latitude=35.702, longitude=139.700)


def test_構造物では中間の頂点を捨てて両端だけで組む():
    """谷を渡る平らな橋。中間の点が指しているのは桁ではなく谷底。"""
    v = compute_elevation_values([A, B, C], [50.0, 10.0, 50.0],
                                 dem_reflects_road_surface=False)

    assert v.elevation_gain_m == 0.0
    assert v.elevation_loss_m == 0.0
    assert v.average_grade == 0.0
    assert v.max_grade == 0.0
    assert v.min_grade == 0.0
    # 橋台・坑口は道が地面と接する位置なので、両端の標高は残す。
    assert v.start_elevation_m == 50.0
    assert v.end_elevation_m == 50.0


def test_構造物でも両端の高低差は残る():
    v = compute_elevation_values([A, B, C], [50.0, 10.0, 62.0],
                                 dem_reflects_road_surface=False)

    assert v.elevation_gain_m == 12.0
    assert v.elevation_loss_m == 0.0


def test_構造物でない道は中間の起伏を積む():
    v = compute_elevation_values([A, B, C], [50.0, 10.0, 50.0],
                                 dem_reflects_road_surface=True)

    assert v.elevation_gain_m == 40.0
    assert v.elevation_loss_m == 40.0


def test_ありえない平均勾配は値を持たせない():
    """0.02度≒2.2mで20m上がると9000%になる。公道としてありえない＝DEMの読み違い。"""
    near = Coordinates(latitude=35.70002, longitude=139.700)
    v = compute_elevation_values([A, near], [10.0, 30.0])

    assert abs(30.0 - 10.0) > 0
    assert v.average_grade is None
    assert MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT == 40.0


def test_標高が取れない点は評価から外す():
    v = compute_elevation_values([A, B, C], [10.0, None, 14.0])

    # 欠損を挟む対はgain/lossへ寄与させない（欠損区間の起伏が均されてしまうため）。
    assert v.elevation_gain_m == 0.0
    assert v.start_elevation_m == 10.0
    assert v.end_elevation_m == 14.0


def test_有効な標高が2点未満なら値を持たない():
    v = compute_elevation_values([A, B], [None, 12.0])

    assert v.start_elevation_m is None
    assert v.average_grade is None


def test_欠損を挟む対は勾配へ寄与させない():
    """欠損を飛ばして隣接扱いすると、その区間の起伏が均された勾配として混入する。"""
    v = compute_elevation_values([A, B, C], [10.0, None, 40.0])

    assert v.max_grade is None
    assert v.min_grade is None
    # 距離は両端の座標から正確に出せるので、平均勾配は持てる。
    assert v.average_grade is not None
