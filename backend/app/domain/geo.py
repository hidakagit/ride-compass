import math
from typing import NamedTuple, Protocol, runtime_checkable

from app.domain.route import Coordinates

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


def destination_point(origin: Coordinates, bearing_deg: float, distance_km: float) -> Coordinates:
    """originから方位bearing_deg（0=北、時計回り）にdistance_km進んだ地点を球面三角法で求める。"""
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

    # 経度は球面三角法の計算結果をそのまま度数化すると±180度を超えることがある
    # （日付変更線付近が起点の場合。Coordinatesはge=-180/le=180を検証するため、
    # 正規化しないとValidationErrorが8方位分のwaypoint計算中に同期的に送出され、
    # generate_loopsのgather(return_exceptions=True)による方位単位の保護をすり抜けて
    # リクエスト全体が500になる）。[-180, 180)へ正規化する。
    lon2_deg = (math.degrees(lon2) + 180) % 360 - 180
    return Coordinates(latitude=math.degrees(lat2), longitude=lon2_deg)


def bearing_between(origin: LatLon, destination: LatLon) -> float:
    """originからdestinationを見た初期方位角（0=北、時計回り、0-360）を球面三角法で求める。"""
    lat1 = math.radians(origin.latitude)
    lat2 = math.radians(destination.latitude)
    dlon = math.radians(destination.longitude - origin.longitude)

    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)

    return math.degrees(math.atan2(x, y)) % 360


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


def sample_indices(point_count: int, sample_count: int) -> list[int]:
    """point_count個の点から、始点・終点を含む均等間隔でsample_count個のインデックスを選ぶ。"""
    if point_count <= sample_count:
        return list(range(point_count))

    step = (point_count - 1) / (sample_count - 1)
    return sorted({round(i * step) for i in range(sample_count)})


def sample_line_points(geometry: dict, sample_count: int) -> list[tuple[int, Coordinates]]:
    """GeoJSON LineStringのgeometryから、始点・終点を含む均等間隔でsample_count点を、
    元のgeometry内でのインデックスと組でサンプリングする。

    標高・風・路面をそれぞれ同じ点集合で評価し、区間ごとに1つの配列として整合させるために使う
    （路面種別はopenrouteserviceのインデックス範囲で返るため、インデックスの共有が必要）。
    OpenRouteServiceEngine専用（Road Graphエンジンは経路上のEdgeを直接走査するため
    使わない）。
    """
    raw_points = geometry["coordinates"]
    indices = sample_indices(len(raw_points), sample_count)
    return [(i, Coordinates(latitude=raw_points[i][1], longitude=raw_points[i][0])) for i in indices]

