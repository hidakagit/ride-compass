from app.domain.errors import RoutingError
from app.domain.route import Coordinates, RouteSegment


class RoutingService:
    """道路ネットワーク上のルート取得を担当する。

    具体的なルーティングエンジン（現在はopenrouteservice、将来Valhalla等）は
    `get_directions(waypoints: list[Coordinates]) -> dict`（GeoJSON Feature）を実装した
    クライアントとして注入する。
    """

    def __init__(self, client):
        self._client = client

    async def get_route(self, waypoints: list[Coordinates]) -> RouteSegment:
        feature = await self._client.get_directions(waypoints)

        try:
            summary = feature["properties"]["summary"]
            geometry = feature["geometry"]
            distance_km = summary["distance"] / 1000
            duration_minutes = summary["duration"] / 60
        except (KeyError, TypeError) as exc:
            raise RoutingError(f"unexpected routing response shape: missing {exc}") from exc

        return RouteSegment(
            distance_km=distance_km,
            duration_minutes=duration_minutes,
            geometry=geometry,
        )
