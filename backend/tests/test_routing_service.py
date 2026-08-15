import pytest

from app.domain.errors import RoutingError
from app.domain.route import Coordinates
from app.services.routing_service import RoutingService

ORIGIN = Coordinates(latitude=35.7597, longitude=139.7387)
DESTINATION = Coordinates(latitude=35.71, longitude=139.75)


class FakeORSClient:
    def __init__(self, feature=None, error=None):
        self._feature = feature
        self._error = error

    async def get_directions(self, waypoints):
        if self._error:
            raise self._error
        return self._feature


def make_feature(distance_m: float, duration_s: float) -> dict:
    return {
        "properties": {"summary": {"distance": distance_m, "duration": duration_s}},
        "geometry": {"type": "LineString", "coordinates": [[139.7387, 35.7597], [139.75, 35.71]]},
    }


async def test_get_route_converts_units_and_geometry():
    client = FakeORSClient(feature=make_feature(distance_m=5000, duration_s=600))
    service = RoutingService(client)

    segment = await service.get_route([ORIGIN, DESTINATION])

    assert segment.distance_km == 5.0
    assert segment.duration_minutes == 10.0
    assert segment.geometry == {"type": "LineString", "coordinates": [[139.7387, 35.7597], [139.75, 35.71]]}


async def test_get_route_propagates_client_error():
    client = FakeORSClient(error=RoutingError("openrouteservice unavailable"))
    service = RoutingService(client)

    with pytest.raises(RoutingError):
        await service.get_route([ORIGIN, DESTINATION])


async def test_get_route_raises_on_malformed_response():
    client = FakeORSClient(feature={"properties": {}, "geometry": {}})
    service = RoutingService(client)

    with pytest.raises(RoutingError):
        await service.get_route([ORIGIN, DESTINATION])
