import httpx

from app.domain.region import BoundingBox
from app.infrastructure.debug_log import log_external_call

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# httpxの既定User-Agent（python-httpx/x.x.x）だとOverpassの公開インスタンスに406を返される
# ことを実機確認したため、利用ポリシーに沿ってアプリを識別できるUser-Agentを明示する。
REQUEST_HEADERS = {"User-Agent": "RideCompass/0.1 (dev; road-surface region layer)"}


class OverpassClient:
    """OSMのOverpass API（公開インスタンス）のクライアント。

    指定bbox内の道路（highwayタグを持つway）を、ノード解決の追加往復なしにジオメトリ付きで
    取得する（`out geom`）。公開インスタンスへの配慮として、呼び出し元（RegionService）は
    未キャッシュのセルを並列化せず順に問い合わせる。
    """

    async def get_roads(self, client: httpx.AsyncClient, bbox: BoundingBox) -> list[dict] | None:
        query = (
            "[out:json][timeout:25];"
            f"way[\"highway\"]({bbox.min_latitude},{bbox.min_longitude},{bbox.max_latitude},{bbox.max_longitude});"
            "out geom;"
        )

        with log_external_call(
            "region:overpass",
            bbox=(bbox.min_latitude, bbox.min_longitude, bbox.max_latitude, bbox.max_longitude),
        ) as fields:
            try:
                response = await client.post(OVERPASS_URL, data={"data": query}, headers=REQUEST_HEADERS)
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                fields["result"] = "error"
                fields["error"] = repr(exc)
                return None

            elements = data.get("elements")
            if elements is None:
                fields["result"] = "no_elements"
                return None

            ways = []
            for element in elements:
                if element.get("type") != "way":
                    continue
                geometry = element.get("geometry")
                if not geometry:
                    continue
                ways.append(
                    {
                        "tags": element.get("tags", {}),
                        "coordinates": [[point["lat"], point["lon"]] for point in geometry],
                    }
                )
            fields["result"] = "ok"
            fields["way_count"] = len(ways)
            return ways
