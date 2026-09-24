"""`domain/gradient.py`——道路の勾配を、指定した走行方位で辿ったときの勾配（%）へ直す。

ここで見ないもの:
- 勾配の生値を道の単位へ集約してタイルへ配ること → `test_gradient_way_service.py`

走行方位が決めるのは符号だけで、坂の急さは変えない。直角に近い向きでは値を配らない（None）。
直角からの幅は宣言（`LENS_PERPENDICULAR_BAND_DEG`）から入力を作り、数字を書き写さない。
"""

import pytest

from app.domain import gradient

BAND = gradient.LENS_PERPENDICULAR_BAND_DEG
effective = gradient.GradientCalculator.effective_gradient


@pytest.mark.parametrize(
    ("road", "travel", "expected"),
    [
        (0.0, 0.0, 6.0),  # 道路の向きに辿る
        (0.0, 180.0, -6.0),  # 逆向きに辿ると登りと下りが入れ替わる
        (350.0, 10.0, 6.0),  # 北をまたいでも向きで決まる
        (90.0, 250.0, -6.0),
    ],
)
def test_the_travel_direction_decides_only_the_sign(road, travel, expected):
    assert effective(6.0, road, travel) == expected


@pytest.mark.parametrize("off_axis", [30.0, 60.0])
def test_riding_at_an_angle_does_not_soften_the_slope(off_axis):
    # 道路は道路に沿ってしか走れず、辿る以上は坂の急さをそのまま受ける（cosで縮めない）
    assert effective(6.0, 0.0, off_axis) == 6.0
    assert effective(6.0, 0.0, 180.0 - off_axis) == -6.0


@pytest.mark.parametrize("travel", [90.0 - BAND, 90.0, 90.0 + BAND, 270.0 - BAND, 270.0 + BAND])
def test_near_perpendicular_travel_gives_no_value_including_the_edge_of_the_band(travel):
    # 0%として配ると、急な坂が地図の凡例で「平坦」の段へ入る
    assert effective(6.0, 0.0, travel) is None


@pytest.mark.parametrize(("travel", "expected"), [(90.0 - BAND - 0.5, 6.0), (90.0 + BAND + 0.5, -6.0)])
def test_just_outside_the_band_the_value_is_given(travel, expected):
    assert effective(6.0, 0.0, travel) == expected


@pytest.mark.parametrize("travel", [0.0, 40.0, 140.0, 200.0, 320.0])
def test_the_reverse_row_of_the_same_road_gives_the_same_answer(travel):
    # 逆方向の行は向きが180度回り、勾配の符号が反転している——2回の反転で元に戻る
    assert effective(6.0, 30.0, travel) == effective(-6.0, 210.0, travel)
