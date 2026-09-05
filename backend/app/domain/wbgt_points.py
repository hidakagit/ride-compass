"""緯度経度→最寄りの暑さ指数（WBGT）情報提供地点の解決。

環境省の情報提供地点はJMA警報のような行政区画ベースではなくアメダス観測所ベース
（全国約840地点、都市部は密・山間部は疎）のため、行政区画の親子関係を辿るjma_area.pyの
方式は使えず、素直な最近傍点探索を行う。840点程度なので毎リクエスト全走査しても
コストは無視できる（空間索引は不要）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class WbgtPoint:
    no: str
    name: str
    latitude: float
    longitude: float


def nearest_point(latitude: float, longitude: float, points: list[WbgtPoint]) -> WbgtPoint | None:
    """出発地点に最も近い情報提供地点を返す。

    日本は緯度帯が広く（北海道〜沖縄で経度1度あたりの実距離が最大14%程度変わる）、
    単純な(緯度差)^2+(経度差)^2だと高緯度で経度方向の距離を過大評価しうる。
    cos(緯度)で経度差を補正した簡易距離で十分な精度が出る（数百m単位の誤差は、
    観測所間隔が数十km規模のこの用途では問題にならない）。
    """
    if not points:
        return None
    lat_rad = math.radians(latitude)
    cos_lat = math.cos(lat_rad)

    def squared_distance(point: WbgtPoint) -> float:
        dx = (point.longitude - longitude) * cos_lat
        dy = point.latitude - latitude
        return dx * dx + dy * dy

    return min(points, key=squared_distance)
