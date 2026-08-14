from fastapi.testclient import TestClient

from app.api.routes import get_route_generator
from app.domain.route import RouteCandidate
from app.main import app

client = TestClient(app)

REQUEST_BODY = {
    "latitude": 35.7597,
    "longitude": 139.7387,
    "distance_km": 30,
    "distance_tolerance_km": 5,
    "route_type": "loop",
}


class FakeRouteGenerator:
    def __init__(self, candidates: list[RouteCandidate]):
        self._candidates = candidates

    async def generate_loops(self, origin, distance_km, distance_tolerance_km):
        return self._candidates


def test_generate_routes_returns_candidates():
    candidates = [
        RouteCandidate(
            id="route-000",
            direction_label="北",
            distance_km=29.8,
            geometry={"type": "LineString", "coordinates": [[139.7387, 35.7597], [139.75, 35.8]]},
        )
    ]
    app.dependency_overrides[get_route_generator] = lambda: FakeRouteGenerator(candidates)

    try:
        response = client.post("/api/routes/generate", json=REQUEST_BODY)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert len(body["routes"]) == 1
    assert body["routes"][0]["id"] == "route-000"
    assert body["routes"][0]["direction_label"] == "北"


def test_generate_routes_returns_empty_list_when_no_candidates_match():
    app.dependency_overrides[get_route_generator] = lambda: FakeRouteGenerator([])

    try:
        response = client.post("/api/routes/generate", json=REQUEST_BODY)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"routes": []}
