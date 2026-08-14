from app.domain.region import BoundingBox
from app.infrastructure.overpass_client import OverpassClient


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class FakeHttpClient:
    def __init__(self, data=None, raises=None):
        self._data = data
        self._raises = raises
        self.last_query = None

    async def post(self, url, data=None, headers=None):
        self.last_query = data
        if self._raises:
            raise self._raises
        return FakeResponse(self._data)


BBOX = BoundingBox(min_latitude=35.70, min_longitude=139.70, max_latitude=35.71, max_longitude=139.71)


async def test_get_roads_parses_ways_with_geometry():
    data = {
        "elements": [
            {
                "type": "way",
                "tags": {"highway": "residential", "surface": "asphalt"},
                "geometry": [{"lat": 35.70, "lon": 139.70}, {"lat": 35.701, "lon": 139.701}],
            },
            {"type": "node", "tags": {}},  # way以外は無視
            {"type": "way", "tags": {"highway": "track"}, "geometry": []},  # geometryが空なら無視
        ]
    }
    client = OverpassClient()

    ways = await client.get_roads(FakeHttpClient(data=data), BBOX)

    assert ways == [{"tags": {"highway": "residential", "surface": "asphalt"}, "coordinates": [[35.70, 139.70], [35.701, 139.701]]}]


async def test_get_roads_includes_bbox_in_query():
    client = OverpassClient()
    http_client = FakeHttpClient(data={"elements": []})

    await client.get_roads(http_client, BBOX)

    assert "35.7,139.7,35.71,139.71" in http_client.last_query["data"]


async def test_get_roads_returns_none_on_request_error():
    import httpx

    client = OverpassClient()
    http_client = FakeHttpClient(raises=httpx.ConnectError("boom", request=httpx.Request("POST", "http://x")))

    result = await client.get_roads(http_client, BBOX)

    assert result is None


async def test_get_roads_returns_none_when_response_missing_elements():
    client = OverpassClient()
    http_client = FakeHttpClient(data={"unexpected": True})

    result = await client.get_roads(http_client, BBOX)

    assert result is None
