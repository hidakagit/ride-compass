from app.domain.geo import destination_point
from app.domain.route import Coordinates
from app.services.elevation_service import ElevationService

ORIGIN = Coordinates(latitude=35.7597, longitude=139.7387)


def make_points(count: int) -> list[Coordinates]:
    # 北方向に1kmずつ離れた点を並べる（各点が確実に異なる座標になるようにする）
    return [destination_point(ORIGIN, bearing_deg=0, distance_km=i) for i in range(count)]


class FakeElevationClient:
    def __init__(self, elevations_by_index: dict[int, float | None]):
        self._elevations_by_index = elevations_by_index
        self._call_count = 0

    async def get_elevation(self, http_client, point):
        index = self._call_count
        self._call_count += 1
        return self._elevations_by_index.get(index)


async def test_get_profile_computes_gain_min_max():
    points = make_points(4)
    # 標高: 10 -> 30 -> 20 -> 40 (獲得標高 = 20 + 20 = 40, min=10, max=40)
    client = FakeElevationClient({0: 10.0, 1: 30.0, 2: 20.0, 3: 40.0})
    service = ElevationService(client, http_client=None)

    profile = await service.get_profile(points)

    assert profile["elevation_gain_m"] == 40.0
    assert profile["min_elevation_m"] == 10.0
    assert profile["max_elevation_m"] == 40.0
    assert profile["max_gradient_percent"] is not None


async def test_get_profile_returns_raw_elevations_aligned_with_points():
    points = make_points(4)
    client = FakeElevationClient({0: 10.0, 1: 30.0, 2: 20.0, 3: 40.0})
    service = ElevationService(client, http_client=None)

    profile = await service.get_profile(points)

    assert profile["elevations"] == [10.0, 30.0, 20.0, 40.0]


async def test_get_profile_ignores_missing_elevation_points():
    points = make_points(4)
    # 2点目はデータなし(None)。有効な点(10 -> 30 -> 40)から獲得標高を計算する
    client = FakeElevationClient({0: 10.0, 1: None, 2: 30.0, 3: 40.0})
    service = ElevationService(client, http_client=None)

    profile = await service.get_profile(points)

    assert profile["elevation_gain_m"] == 30.0
    assert profile["min_elevation_m"] == 10.0
    assert profile["max_elevation_m"] == 40.0
    assert profile["elevations"] == [10.0, None, 30.0, 40.0]


async def test_get_profile_returns_all_none_when_insufficient_data():
    points = make_points(4)
    client = FakeElevationClient({0: 10.0})  # 有効な点が1つしかない

    service = ElevationService(client, http_client=None)

    profile = await service.get_profile(points)

    assert profile == {
        "elevation_gain_m": None,
        "min_elevation_m": None,
        "max_elevation_m": None,
        "max_gradient_percent": None,
        "elevations": [10.0, None, None, None],
    }
