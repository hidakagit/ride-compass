import httpx

from app.domain.region import BoundingBox
from app.infrastructure.debug_log import log_external_call

# 複数の公開Overpassミラーへ順に問い合わせる。実機（Renderデプロイ）で、既定の
# overpass-api.de単独だと「同一クエリを別経路（開発機）から直接叩くと数千件のwayが
# 数秒〜十秒程度で返るのに、Render経由だと2〜3秒で0件（elements: []、remarkも無し）」
# という現象が確認された。HTTPエラーにはならないため既存の例外ハンドリングでは
# 検知できず、その「0件」がRegionServiceのタイル永続キャッシュへそのまま焼き付いて
# しまい、路面レイヤーがそのタイルだけ永久に空表示になっていた。公開インスタンスの
# レート制限/優先度低下（同一IPからの短時間の連続問い合わせに対して処理予算を
# 減らし早期に打ち切る、既知の挙動）が原因と推測される。単一ミラーの「200 OKだが
# 0件」を信用せず、他のミラーでも0件と分かるまでは「本当に対象が無い」と判断しない。
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# httpxの既定User-Agent（python-httpx/x.x.x）だとOverpassの公開インスタンスに406を返される
# ことを実機確認したため、利用ポリシーに沿ってアプリを識別できるUser-Agentを明示する。
REQUEST_HEADERS = {"User-Agent": "RideCompass/0.1 (dev; road-surface region layer)"}


class OverpassClient:
    """OSMのOverpass API（複数の公開ミラーへフォールバック）のクライアント。

    指定bbox内の道路（highwayタグを持つway）を取得する。公開インスタンスへの配慮として、
    呼び出し元（RegionService/GraphService）は未キャッシュのセルを並列化せず順に問い合わせる。
    """

    async def _query(self, client: httpx.AsyncClient, query: str, log_category: str, **log_fields) -> dict | None:
        """queryを複数ミラーへ順に試行し、最初に0件でない結果を返したミラーのdataを返す。

        全ミラーがエラー、または「elementsキー自体が無い」（プロトコル異常）だった場合は
        None。全ミラーが成功したが0件だった場合は、その最後の（＝どのミラーでも変わらない
        はずの）dataをそのまま返す（本当に対象が無いケースとして扱う）。
        """
        last_empty_data: dict | None = None

        for url in OVERPASS_URLS:
            with log_external_call(log_category, mirror=url, **log_fields) as fields:
                try:
                    response = await client.post(url, data={"data": query}, headers=REQUEST_HEADERS)
                    response.raise_for_status()
                    data = response.json()
                except (httpx.HTTPError, ValueError) as exc:
                    fields["result"] = "error"
                    fields["error"] = repr(exc)
                    continue

                elements = data.get("elements")
                if elements is None:
                    # elementsキー自体が無いのはこのミラーのプロトコル異常(docstring参照)。
                    # result="error"にして常時WARNINGへ乗せる(道路が無い地域は空のelementsが
                    # 返るためここには来ない。debug_log.pyがカテゴリ単位で抑制する)。
                    fields["result"] = "error"
                    fields["error"] = "no_elements_in_response"
                    continue

                fields["result"] = "ok"
                fields["element_count"] = len(elements)
                if elements:
                    return data
                # このミラーは成功したが0件。レート制限による見せかけの0件の可能性が
                # あるため、他のミラーでも確認できるまでは即座に信用しない。
                last_empty_data = data

        return last_empty_data

    async def get_roads(self, client: httpx.AsyncClient, bbox: BoundingBox) -> list[dict] | None:
        query = (
            "[out:json][timeout:25];"
            f"way[\"highway\"]({bbox.min_latitude},{bbox.min_longitude},{bbox.max_latitude},{bbox.max_longitude});"
            "out geom;"
        )

        data = await self._query(
            client,
            query,
            "region:overpass",
            bbox=(bbox.min_latitude, bbox.min_longitude, bbox.max_latitude, bbox.max_longitude),
        )
        if data is None:
            return None

        ways = []
        for element in data["elements"]:
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

        data = await self._query(
            client,
            query,
            "graph:overpass",
            bbox=(bbox.min_latitude, bbox.min_longitude, bbox.max_latitude, bbox.max_longitude),
        )
        if data is None:
            return None

        ways: list[dict] = []
        nodes: dict[int, tuple[float, float]] = {}
        for element in data["elements"]:
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

        return ways, nodes
