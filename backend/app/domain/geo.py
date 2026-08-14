import math

from app.domain.route import Coordinates

EARTH_RADIUS_KM = 6371.0

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

    return Coordinates(latitude=math.degrees(lat2), longitude=math.degrees(lon2))


def bearing_between(origin: Coordinates, destination: Coordinates) -> float:
    """originからdestinationを見た初期方位角（0=北、時計回り、0-360）を球面三角法で求める。"""
    lat1 = math.radians(origin.latitude)
    lat2 = math.radians(destination.latitude)
    dlon = math.radians(destination.longitude - origin.longitude)

    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)

    return math.degrees(math.atan2(x, y)) % 360


def haversine_distance_km(a: Coordinates, b: Coordinates) -> float:
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


def sample_line_coordinates(geometry: dict, sample_count: int) -> list[Coordinates]:
    """GeoJSON LineStringのgeometryから、始点・終点を含む均等間隔でsample_count点をサンプリングする。"""
    raw_points = geometry["coordinates"]
    indices = sample_indices(len(raw_points), sample_count)
    return [Coordinates(latitude=raw_points[i][1], longitude=raw_points[i][0]) for i in indices]


def sample_line_points(geometry: dict, sample_count: int) -> list[tuple[int, Coordinates]]:
    """sample_line_coordinatesと同じ点を、元のgeometry内でのインデックスと組で返す。

    標高・風・路面をそれぞれ同じ点集合で評価し、区間ごとに1つの配列として整合させるために使う
    （路面種別はopenrouteserviceのインデックス範囲で返るため、インデックスの共有が必要）。
    OpenRouteServiceEngine専用（Road Graphエンジンは経路上のEdgeを直接走査するため
    使わない）。
    """
    raw_points = geometry["coordinates"]
    indices = sample_indices(len(raw_points), sample_count)
    return [(i, Coordinates(latitude=raw_points[i][1], longitude=raw_points[i][0])) for i in indices]

