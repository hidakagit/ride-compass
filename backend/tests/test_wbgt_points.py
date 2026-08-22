from app.domain.wbgt_points import WbgtPoint, nearest_point

TOKYO = WbgtPoint(no="44132", name="東京", latitude=35.6917, longitude=139.75)
SAPPORO = WbgtPoint(no="14163", name="札幌", latitude=43.0621, longitude=141.3544)
NAHA = WbgtPoint(no="91197", name="那覇", latitude=26.2124, longitude=127.6809)

POINTS = [TOKYO, SAPPORO, NAHA]


def test_nearest_point_picks_the_closest_of_multiple_candidates():
    # 東京駅付近
    result = nearest_point(35.6812, 139.7671, POINTS)
    assert result == TOKYO


def test_nearest_point_works_at_high_latitude():
    # 札幌市街地付近。高緯度でも経度差の補正により正しく最寄りを選べることを確認する
    # （cos(緯度)補正が無いと、経度方向の距離を過大評価して誤った地点を選びうる）。
    result = nearest_point(43.0642, 141.3469, POINTS)
    assert result == SAPPORO


def test_nearest_point_works_at_low_latitude():
    result = nearest_point(26.2, 127.68, POINTS)
    assert result == NAHA


def test_nearest_point_returns_none_for_empty_list():
    assert nearest_point(35.0, 139.0, []) is None
