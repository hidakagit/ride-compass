"""テスト専用の座標生成ヘルパー。

`destination_point`は元々`app/domain/geo.py`にあった本番関数（8方位固定の周回経由地計算
`_loop_waypoints`が使っていた）だが、改善計画T531で周回生成がフロンティア方式へ転換し
本番コードから未参照になったため、改善計画T555でフィクスチャ座標生成専用のヘルパーとして
ここへ移した（`test_road_graph_engine.py`の合成グラフ・`test_geo.py`の`bearing_between`/
`haversine_distance_km`検証が「起点から方位θへ距離d進んだ点」を必要とする）。
"""

import math

from app.domain.geo import EARTH_RADIUS_KM
from app.domain.route import Coordinates


def destination_point(origin: Coordinates, bearing_deg: float, distance_km: float) -> Coordinates:
    """originから方位bearing_deg（0=北、時計回り）にdistance_km進んだ地点を球面三角法で求める。

    経度は球面三角法の計算結果をそのまま度数化すると±180度を超えることがある
    （日付変更線付近が起点の場合。`Coordinates`はge=-180/le=180を検証するため
    ValidationErrorになる）ので[-180, 180)へ正規化する。
    """
    lat1 = math.radians(origin.latitude)
    lon1 = math.radians(origin.longitude)
    bearing = math.radians(bearing_deg)
    angular_distance = distance_km / EARTH_RADIUS_KM

    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular_distance) + math.cos(lat1) * math.sin(angular_distance) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(lat1),
        math.cos(angular_distance) - math.sin(lat1) * math.sin(lat2),
    )
    lon2_deg = (math.degrees(lon2) + 180) % 360 - 180
    return Coordinates(latitude=math.degrees(lat2), longitude=lon2_deg)
