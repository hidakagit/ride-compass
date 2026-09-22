"""`domain/wbgt_points.py`——最寄りの暑さ指数（WBGT）情報提供地点を選ぶ。

選んだ地点の値を取る側は`test_wbgt_service.py`が持つ。
"""

from app.domain.wbgt_points import WbgtPoint, nearest_point


def _point(no: str, latitude: float, longitude: float) -> WbgtPoint:
    return WbgtPoint(no=no, name=f"地点{no}", latitude=latitude, longitude=longitude)


def test_the_closest_point_is_chosen():
    near = _point("1", 35.0, 139.0)
    far = _point("2", 40.0, 145.0)

    assert nearest_point(35.1, 139.1, [far, near]) is near


def test_an_empty_list_has_no_nearest_point():
    """既定の地点へ倒さない——無関係な土地の暑さ指数が出る。"""
    assert nearest_point(35.0, 139.0, []) is None


def test_a_single_point_is_always_the_nearest():
    only = _point("1", 0.0, 0.0)

    assert nearest_point(35.0, 139.0, [only]) is only


def test_longitude_differences_shrink_with_latitude():
    """緯度45度では経度1度は緯度1度の約0.71倍の距離しかない。補正が無ければ両者は
    同距離に見え、先に並んでいる北の地点が選ばれてしまう。
    """
    north = _point("north", 46.0, 140.0)
    east = _point("east", 45.0, 141.0)

    assert nearest_point(45.0, 140.0, [north, east]) is east


def test_at_the_equator_the_two_directions_weigh_the_same():
    """補正は緯度に応じたもので、赤道では効かない（cos(0)=1）。一律の係数を掛けて
    いるだけなら、ここで南北が選ばれない。
    """
    north = _point("north", 1.0, 0.0)
    east = _point("east", 0.0, 1.0)

    # 同距離のときは先に並んでいるものが返る。
    assert nearest_point(0.0, 0.0, [north, east]) is north
    assert nearest_point(0.0, 0.0, [east, north]) is east
