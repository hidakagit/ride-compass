import pytest
from fastapi.testclient import TestClient

from app.api.routes import PREVIEW_RATE_LIMIT_PER_MINUTE, get_routing_service
from app.domain.errors import RoutingError
from app.domain.route import RouteSegment
from app.infrastructure import rate_limiter
from app.main import app

client = TestClient(app)

REQUEST_BODY = {
    "origin": {"latitude": 35.7597, "longitude": 139.7387},
    "destination": {"latitude": 35.71, "longitude": 139.75},
}


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    # rate_limiterはプロセス内グローバルの固定窓カウンタのため、テスト間で
    # 消し込まないと前のテストのリクエストが今のテストの上限に食い込む。
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


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


@pytest.mark.parametrize(
    "body",
    [
        {"origin": {"latitude": 91, "longitude": 139.7387}, "destination": REQUEST_BODY["destination"]},
        {"origin": {"latitude": 35.7597, "longitude": 181}, "destination": REQUEST_BODY["destination"]},
        {"origin": REQUEST_BODY["origin"], "destination": {"latitude": -91, "longitude": 139.75}},
    ],
)
def test_preview_route_rejects_out_of_range_coordinates(body):
    app.dependency_overrides[get_routing_service] = lambda: FakeRoutingService()

    try:
        response = client.post("/api/routes/preview", json=body)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_preview_route_is_rate_limited_per_client():
    segment = RouteSegment(
        distance_km=5.0,
        duration_minutes=10.0,
        geometry={"type": "LineString", "coordinates": [[139.7387, 35.7597], [139.75, 35.71]]},
    )
    app.dependency_overrides[get_routing_service] = lambda: FakeRoutingService(segment=segment)

    try:
        for _ in range(PREVIEW_RATE_LIMIT_PER_MINUTE):
            assert client.post("/api/routes/preview", json=REQUEST_BODY).status_code == 200
        response = client.post("/api/routes/preview", json=REQUEST_BODY)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429
