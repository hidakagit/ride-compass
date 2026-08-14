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

    async def get_ways_and_nodes(
        self, client: httpx.AsyncClient, bbox: BoundingBox
    ) -> tuple[list[dict], dict[int, tuple[float, float]]] | None:
        """指定bbox内の道路（highwayタグを持つway）を、Way ID・Node IDとノード間の参照関係
        （トポロジー）を保持したまま取得する。

        `get_roads`（`out geom`でジオメトリのみ取得、ID無し。地域路面レイヤーの地図表示用）とは
        異なり、Road Graph構築（交差点でのWay分割）にはどのノードをどのWayが共有しているかが
        必要なため、`(._;>;)`でwayが参照する全nodeを再帰的に取得し、ID付きで返す。
        """
        query = (
            "[out:json][timeout:25];"
            f"way[\"highway\"]({bbox.min_latitude},{bbox.min_longitude},{bbox.max_latitude},{bbox.max_longitude});"
            "(._;>;);"
            "out body;"
        )

        with log_external_call(
            "graph:overpass",
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

            ways: list[dict] = []
            nodes: dict[int, tuple[float, float]] = {}
            for element in elements:
                element_type = element.get("type")
                if element_type == "node":
                    node_id, lat, lon = element.get("id"), element.get("lat"), element.get("lon")
                    if node_id is not None and lat is not None and lon is not None:
                        nodes[node_id] = (lat, lon)
                elif element_type == "way":
                    way_nodes = element.get("nodes")
                    if not way_nodes:
                        continue
                    ways.append({"id": element.get("id"), "tags": element.get("tags", {}), "nodes": way_nodes})

            fields["result"] = "ok"
            fields["way_count"] = len(ways)
            fields["node_count"] = len(nodes)
            return ways, nodes
