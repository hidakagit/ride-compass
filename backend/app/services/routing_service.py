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
        except KeyError as exc:
            raise RoutingError(f"unexpected routing response shape: missing {exc}") from exc

        # surfaceはextra_infoで要求した付随情報。無くても致命的ではないため欠損を許容する。
        surface_extras = feature.get("properties", {}).get("extras", {}).get("surface", {})
        surface_summary = surface_extras.get("summary")
        surface_values = surface_extras.get("values")

        return RouteSegment(
            distance_km=summary["distance"] / 1000,
            duration_minutes=summary["duration"] / 60,
            geometry=geometry,
            surface_summary=surface_summary,
            surface_values=surface_values,
        )
