import httpx

from app.domain.errors import RoutingError
from app.domain.route import Coordinates

DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/cycling-road/geojson"


class ORSClient:
    def __init__(self, api_key: str):
        self._api_key = api_key

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
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(DIRECTIONS_URL, json=payload, headers=headers)
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
