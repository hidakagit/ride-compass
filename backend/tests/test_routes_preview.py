from fastapi.testclient import TestClient

from app.api.routes import get_routing_service
from app.domain.errors import RoutingError
from app.domain.route import RouteSegment
from app.main import app

client = TestClient(app)

REQUEST_BODY = {
    "origin": {"latitude": 35.7597, "longitude": 139.7387},
    "destination": {"latitude": 35.71, "longitude": 139.75},
}


class FakeRoutingService:
    def __init__(self, segment=None, error=None):
        self._segment = segment
        self._error = error

    async def get_route(self, waypoints):
        if self._error:
            raise self._error
        return self._segment


def test_preview_route_returns_segment_on_success():
    segment = RouteSegment(
        distance_km=5.0,
        duration_minutes=10.0,
        geometry={"type": "LineString", "coordinates": [[139.7387, 35.7597], [139.75, 35.71]]},
    )
    app.dependency_overrides[get_routing_service] = lambda: FakeRoutingService(segment=segment)

    try:
        response = client.post("/api/routes/preview", json=REQUEST_BODY)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["distance_km"] == 5.0
    assert body["duration_minutes"] == 10.0


def test_preview_route_returns_502_on_routing_error():
    app.dependency_overrides[get_routing_service] = lambda: FakeRoutingService(
        error=RoutingError("openrouteservice unavailable")
    )

    try:
        response = client.post("/api/routes/preview", json=REQUEST_BODY)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert "ルート取得に失敗しました" in response.json()["detail"]
