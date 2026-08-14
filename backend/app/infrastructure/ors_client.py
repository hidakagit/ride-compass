import httpx

from app.domain.errors import RoutingError
from app.domain.route import Coordinates

DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/cycling-road/geojson"


class ORSClient:
    """openrouteservice Directions APIのクライアント。

    `http_client`は呼び出し元（DI）が生成・クローズを管理する共有コネクション。
    以前は呼び出しごとに新規`httpx.AsyncClient`を生成しており、8方位の周回生成では
    TLSハンドシェイクを8回やり直していた（ElevationClientで実測57秒→7秒の差を生んだ
    のと同じパターン）ため、他のクライアントと同様にコンストラクタ注入へ統一した。
    """

    def __init__(self, api_key: str, http_client: httpx.AsyncClient):
        self._api_key = api_key
        self._http_client = http_client

    async def get_directions(self, waypoints: list[Coordinates]) -> dict:
        payload = {
            "coordinates": [[point.longitude, point.latitude] for point in waypoints],
            "extra_info": ["surface"],
        }
        headers = {
            "Authorization": self._api_key,
            "Content-Type": "application/json",
        }

        try:
            response = await self._http_client.post(DIRECTIONS_URL, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RoutingError(f"openrouteservice returned {exc.response.status_code}: {exc.response.text}") from exc
        except httpx.RequestError as exc:
            raise RoutingError(f"openrouteservice request failed: {exc}") from exc

        data = response.json()
        features = data.get("features")
        if not features:
            raise RoutingError("openrouteservice returned no route")

        return features[0]
