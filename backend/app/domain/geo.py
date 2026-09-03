import math
from typing import NamedTuple, Protocol, runtime_checkable

import numpy as np

EARTH_RADIUS_KM = 6371.0


@runtime_checkable
class LatLon(Protocol):
    """緯度経度を持つ任意の型（`Coordinates`・`Node`・`LeanNode`等）を受け付ける
    構造的型（改善計画T262）。`bearing_between`/`haversine_distance_km`は内部で
    `.latitude`/`.longitude`を読むだけで完結しており、元は型ヒントが`Coordinates`
    （Pydantic）固定だったため、`build_road_graph`（domain/graph.py）・
    `find_nearest_node`系（domain/routing.py）のようなホットパスで、既に手元にある
    生の緯度経度ペアやNodeオブジェクトからわざわざ`Coordinates`を構築し直す
    無駄が生じていた（T248でNode/DirectedEdgeに対して確認したのと同種の問題）。
    """

    latitude: float
    longitude: float


class LatLonPoint(NamedTuple):
    """`LatLon`を満たす最小実装（改善計画T262）。Pydanticのバリデーションコストを
    避けたい内部計算専用（`Coordinates`は入力検証が必要なAPI境界向けに残す）。
    """

    latitude: float
    longitude: float

# 緯度1度あたりの概算距離（km、地球を球とみなす近似。EARTH_RADIUS_KMと同じ半径前提で
# 十分、空間索引のバケット分割・打ち切り判定・矩形マージンの見積もりという「目安」用途に
# のみ使う。実際の距離計算は常にhaversine_distance_kmで正確に行う。改善計画T228で
# domain/routing.py・services/road_graph_engine.pyの重複定義をここへ片側import化）。
KM_PER_DEGREE_LATITUDE = 111.0

COMPASS_LABELS = ["北", "北東", "東", "南東", "南", "南西", "西", "北西"]


def compass_label(bearing_deg: float) -> str:
    """任意の角度（0=北、時計回り）を8方位のラベルに変換する。"""
    index = round((bearing_deg % 360) / 45) % 8
    return COMPASS_LABELS[index]


def bearing_between(origin: LatLon, destination: LatLon) -> float:
    """originからdestinationを見た初期方位角（0=北、時計回り、0-360）を球面三角法で求める。"""
    lat1 = math.radians(origin.latitude)
    lat2 = math.radians(destination.latitude)
    dlon = math.radians(destination.longitude - origin.longitude)

    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)

    return math.degrees(math.atan2(x, y)) % 360


def bearing_between_array(origin: LatLon, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """`bearing_between`のベクトル化版。originから`(lat, lon)`の各点を見た初期方位角
    （0=北、時計回り、0-360）を配列で返す（改善計画T554、大量Nodeに対する
    `bearing_between`の繰り返し呼び出しを避ける）。"""
    lat1 = math.radians(origin.latitude)
    lat2 = np.radians(lat)
    dlon = np.radians(lon - origin.longitude)

    x = np.sin(dlon) * np.cos(lat2)
    y = math.cos(lat1) * np.sin(lat2) - math.sin(lat1) * np.cos(lat2) * np.cos(dlon)

    return np.degrees(np.arctan2(x, y)) % 360


def haversine_distance_km(a: LatLon, b: LatLon) -> float:
    """2地点間の球面距離（km）。"""
    lat1, lon1, lat2, lon2 = (
        math.radians(a.latitude),
        math.radians(a.longitude),
        math.radians(b.latitude),
        math.radians(b.longitude),
    )
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def haversine_distance_km_array(lat: np.ndarray, lon: np.ndarray, target: LatLon) -> np.ndarray:
    """`haversine_distance_km`のnumpyベクトル版（改善計画T536）。

    `lat`/`lon`は複数地点の緯度経度配列（同一形状）、`target`は単一の目的地。
    A*ヒューリスティック（`_build_estimate_cost_fn`相当）が、レグごとに目的地が
    変わるたびグラフ上の全Nodeとの距離をPythonループ無しで1回のnumpy演算で
    求め直すために使う（訪問したNodeだけ都度計算していたスカラー版と異なり、
    全Node分をまとめて計算するが、numpy演算1回のコストはNode数十万件規模でも
    数十ms程度に収まる）。式自体は`haversine_distance_km`と同一（丸め方式の
    違いによる浮動小数点の不一致はヒューリスティックの許容誤差に影響しない
    ——A*のestimate_cost_fnは下界を返しさえすれば正しく動作するadmissible
    ヒューリスティックのため、スカラー版とのビット単位一致は不要）。
    """
    lat1 = np.radians(lat)
    lon1 = np.radians(lon)
    lat2 = math.radians(target.latitude)
    lon2 = math.radians(target.longitude)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = np.sin(dlat / 2) ** 2 + np.cos(lat1) * math.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(h, 0.0, 1.0)))

