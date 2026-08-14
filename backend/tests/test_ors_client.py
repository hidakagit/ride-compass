import httpx
import pytest

from app.domain.errors import RoutingError
from app.domain.route import Coordinates
from app.infrastructure.ors_client import ORSClient

WAYPOINTS = [
    Coordinates(latitude=35.7597, longitude=139.7387),
    Coordinates(latitude=35.71, longitude=139.75),
]


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, headers=None, text="error body"):
        self.status_code = status_code
        self._json_data = json_data
        self.headers = headers or {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://x")
            response = httpx.Response(self.status_code, request=request, text=self.text)
            raise httpx.HTTPStatusError(f"status {self.status_code}", request=request, response=response)

    def json(self):
        return self._json_data


class FakeHttpClient:
    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises
        self.last_call = None

    async def post(self, url, json=None, headers=None):
        self.last_call = {"url": url, "json": json, "headers": headers}
        if self._raises:
            raise self._raises
        return self._response


def _feature(distance_m=5000, duration_s=600):
    return {
        "properties": {"summary": {"distance": distance_m, "duration": duration_s}},
        "geometry": {"type": "LineString", "coordinates": [[139.7387, 35.7597], [139.75, 35.71]]},
    }


async def test_get_directions_returns_first_feature_on_success():
    response = FakeResponse(status_code=200, json_data={"features": [_feature()]})
    http_client = FakeHttpClient(response=response)
    client = ORSClient("test-key", http_client)

    result = await client.get_directions(WAYPOINTS)

    assert result == _feature()


async def test_get_directions_sends_coordinates_as_lon_lat_pairs_with_auth_header():
    response = FakeResponse(status_code=200, json_data={"features": [_feature()]})
    http_client = FakeHttpClient(response=response)
    client = ORSClient("test-key", http_client)

    await client.get_directions(WAYPOINTS)

    assert http_client.last_call["json"]["coordinates"] == [[139.7387, 35.7597], [139.75, 35.71]]
    assert http_client.last_call["headers"]["Authorization"] == "test-key"


async def test_get_directions_raises_routing_error_on_http_status_error():
    response = FakeResponse(status_code=429, text="quota exceeded")
    http_client = FakeHttpClient(response=response)
    client = ORSClient("test-key", http_client)

    with pytest.raises(RoutingError, match="429"):
        await client.get_directions(WAYPOINTS)


async def test_get_directions_raises_routing_error_on_request_error():
    http_client = FakeHttpClient(raises=httpx.ConnectError("boom", request=httpx.Request("POST", "http://x")))
    client = ORSClient("test-key", http_client)

    with pytest.raises(RoutingError, match="request failed"):
        await client.get_directions(WAYPOINTS)


async def test_get_directions_raises_routing_error_when_no_features():
    response = FakeResponse(status_code=200, json_data={"features": []})
    http_client = FakeHttpClient(response=response)
    client = ORSClient("test-key", http_client)

    with pytest.raises(RoutingError, match="no route"):
        await client.get_directions(WAYPOINTS)


async def test_get_directions_raises_routing_error_when_features_key_missing():
    response = FakeResponse(status_code=200, json_data={})
    http_client = FakeHttpClient(response=response)
    client = ORSClient("test-key", http_client)

    with pytest.raises(RoutingError, match="no route"):
        await client.get_directions(WAYPOINTS)
