from app.domain.region import BoundingBox
from app.infrastructure.overpass_client import OVERPASS_URLS, OverpassClient


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


class FakeMultiMirrorHttpClient:
    """ミラーURLごとに異なる応答(データ・例外)を返せるフェイク。
    レート制限で最初のミラーだけ0件になる等、ミラーフォールバックの検証に使う。
    """

    def __init__(self, responses_by_url: dict[str, dict | Exception]):
        self._responses_by_url = responses_by_url
        self.requested_urls: list[str] = []

    async def post(self, url, data=None, headers=None):
        self.requested_urls.append(url)
        response = self._responses_by_url[url]
        if isinstance(response, Exception):
            raise response
        return FakeResponse(response)


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


async def test_get_ways_and_nodes_parses_topology_with_ids():
    data = {
        "elements": [
            {"type": "node", "id": 1, "lat": 35.70, "lon": 139.70},
            {"type": "node", "id": 2, "lat": 35.701, "lon": 139.701},
            {
                "type": "way",
                "id": 100,
                "tags": {"highway": "residential"},
                "nodes": [1, 2],
            },
            {"type": "way", "id": 101, "tags": {"highway": "track"}, "nodes": []},  # nodesが空なら無視
        ]
    }
    client = OverpassClient()

    result = await client.get_ways_and_nodes(FakeHttpClient(data=data), BBOX)

    assert result is not None
    ways, nodes = result
    assert ways == [{"id": 100, "tags": {"highway": "residential"}, "nodes": [1, 2]}]
    assert nodes == {1: (35.70, 139.70), 2: (35.701, 139.701)}


async def test_get_ways_and_nodes_returns_none_on_request_error():
    import httpx

    client = OverpassClient()
    http_client = FakeHttpClient(raises=httpx.ConnectError("boom", request=httpx.Request("POST", "http://x")))

    result = await client.get_ways_and_nodes(http_client, BBOX)

    assert result is None


async def test_get_ways_and_nodes_returns_none_when_response_missing_elements():
    client = OverpassClient()
    http_client = FakeHttpClient(data={"unexpected": True})

    result = await client.get_ways_and_nodes(http_client, BBOX)

    assert result is None


def _way_element(way_id: int) -> dict:
    return {
        "type": "way",
        "tags": {"highway": "residential"},
        "geometry": [{"lat": 35.70, "lon": 139.70}, {"lat": 35.701, "lon": 139.701}],
    }


async def test_get_roads_uses_the_mirror_that_returns_non_zero_elements():
    # 実機(Render)で確認された現象の再現: 一部のミラーは200 OKだがelements:[]
    # (レート制限による見せかけの0件の可能性)、他のミラーは本物のデータを返す。
    # 全ミラーへ同時に問い合わせ、0件でない結果を採用する。
    assert len(OVERPASS_URLS) >= 2, "このテストは最低2つのミラーがある前提"
    responses = {url: {"elements": []} for url in OVERPASS_URLS}
    responses[OVERPASS_URLS[-1]] = {"elements": [_way_element(1)]}
    http_client = FakeMultiMirrorHttpClient(responses)
    client = OverpassClient()

    ways = await client.get_roads(http_client, BBOX)

    assert ways is not None and len(ways) == 1
    # 同時に全ミラーへ問い合わせるため、成功したミラー以外も呼ばれている。
    assert set(http_client.requested_urls) == set(OVERPASS_URLS)


async def test_get_roads_uses_the_mirror_that_succeeds_when_others_error():
    import httpx

    assert len(OVERPASS_URLS) >= 2
    responses = {url: httpx.ConnectError("boom", request=httpx.Request("POST", url)) for url in OVERPASS_URLS}
    responses[OVERPASS_URLS[-1]] = {"elements": [_way_element(1)]}
    http_client = FakeMultiMirrorHttpClient(responses)
    client = OverpassClient()

    ways = await client.get_roads(http_client, BBOX)

    assert ways is not None and len(ways) == 1


async def test_get_roads_returns_empty_list_when_all_mirrors_agree_on_zero_elements():
    # 全ミラーが揃って0件なら、本当に対象が無いケースとして空リストを返す（Noneではない）。
    http_client = FakeMultiMirrorHttpClient({url: {"elements": []} for url in OVERPASS_URLS})
    client = OverpassClient()

    ways = await client.get_roads(http_client, BBOX)

    assert ways == []
    assert set(http_client.requested_urls) == set(OVERPASS_URLS)


async def test_get_roads_returns_none_when_all_mirrors_error():
    import httpx

    http_client = FakeMultiMirrorHttpClient(
        {url: httpx.ConnectError("boom", request=httpx.Request("POST", url)) for url in OVERPASS_URLS}
    )
    client = OverpassClient()

    result = await client.get_roads(http_client, BBOX)

    assert result is None
