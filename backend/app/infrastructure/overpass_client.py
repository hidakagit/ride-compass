import asyncio

import httpx

from app.domain.region import BoundingBox
from app.infrastructure.debug_log import log_external_call

# 複数の公開Overpassミラーへ同時に問い合わせる。実機（Renderデプロイ）で、既定の
# overpass-api.de単独だと「同一クエリを別経路（開発機）から直接叩くと数千件のwayが
# 数秒〜十秒程度で返るのに、Render経由だと2〜3秒で0件（elements: []、remarkも無し）」
# という現象が確認された。HTTPエラーにはならないため既存の例外ハンドリングでは
# 検知できず、その「0件」がタイル永続キャッシュへそのまま焼き付いてしまい、
# そのタイルだけ永久に空表示になっていた（当時は地域路面レイヤーもOverpass経由。
# 現在は`get_ways_and_nodes`＝Road Graph構築専用だが、同じ問題が起こりうる点は変わらない）。
# 単一ミラーの
# 「200 OKだが0件」を信用せず、他のミラーでも0件と分かるまでは「本当に対象が無い」と
# 判断しない。
#
# 当初は順に問い合わせていたが、実機で公開Overpassエコシステム全体がRender経由の
# 送信元IPに対して広く遅延・失敗する状況（1ミラーあたり平均10〜20秒、3ミラー合計で
# 最大90秒）が観測され、順次フォールバックだと1タイルの応答に1分以上かかる悪化を招いた。
# 全ミラーへ同時に問い合わせ、最初に0件でない結果が返った時点で採用し残りは打ち切る
# 方式に変更した。最悪ケースの所要時間が「ミラー数×タイムアウト」から「タイムアウト1回分」
# に短縮される（成功率そのものは変わらないが、失敗する場合も速く失敗できる）。
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# httpxの既定User-Agent（python-httpx/x.x.x）だとOverpassの公開インスタンスに406を返される
# ことを実機確認したため、利用ポリシーに沿ってアプリを識別できるUser-Agentを明示する。
REQUEST_HEADERS = {"User-Agent": "RideCompass/0.1 (dev; road-graph construction)"}


class OverpassClient:
    """OSMのOverpass API（複数の公開ミラーへ同時フォールバック）のクライアント。

    `GraphService`の`repository`未接続時（DBなし構成）のRoad Graph構築でのみ使う
    （改善計画T22でOverpassフォールバックを撤去済みのため、それ以外の経路からは呼ばれない）。
    """

    async def _query_one(
        self, client: httpx.AsyncClient, url: str, query: str, log_category: str, log_fields: dict
    ) -> dict | None:
        with log_external_call(log_category, mirror=url, **log_fields) as fields:
            try:
                response = await client.post(url, data={"data": query}, headers=REQUEST_HEADERS)
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                fields["result"] = "error"
                fields["error"] = repr(exc)
                return None

            elements = data.get("elements")
            if elements is None:
                # elementsキー自体が無いのはこのミラーのプロトコル異常。result="error"にして
                # 常時WARNINGへ乗せる（道路が無い地域は空のelementsが返るためここには来ない）。
                fields["result"] = "error"
                fields["error"] = "no_elements_in_response"
                return None

            fields["result"] = "ok"
            fields["element_count"] = len(elements)
            return data

    async def _query(self, client: httpx.AsyncClient, query: str, log_category: str, **log_fields) -> dict | None:
        """queryを全ミラーへ同時に問い合わせ、最初に0件でない結果を返したミラーのdataを採用する。

        非同期タスクとして並行実行し、`asyncio.as_completed`で完了順に確認する。0件でない
        結果が見つかり次第、残りのタスクはキャンセルして打ち切る（無駄な問い合わせを続けない）。
        全ミラーがエラー、または「elementsキー自体が無い」場合はNone。全ミラーが成功したが
        0件だった場合は、そのdataをそのまま返す（本当に対象が無いケースとして扱う）。
        """
        tasks = [
            asyncio.create_task(self._query_one(client, url, query, log_category, log_fields)) for url in OVERPASS_URLS
        ]
        last_empty_data: dict | None = None
        try:
            for finished in asyncio.as_completed(tasks):
                data = await finished
                if data is None:
                    continue
                if data["elements"]:
                    return data
                # このミラーは成功したが0件。レート制限による見せかけの0件の可能性が
                # あるため、他のミラーの結果を待ってから判断する。
                last_empty_data = data
            return last_empty_data
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

    async def get_ways_and_nodes(
        self, client: httpx.AsyncClient, bbox: BoundingBox
    ) -> tuple[list[dict], dict[int, tuple[float, float]]] | None:
        """指定bbox内の道路（highwayタグを持つway）を、Way ID・Node IDとノード間の参照関係
        （トポロジー）を保持したまま取得する。

        Road Graph構築（交差点でのWay分割）にはどのノードをどのWayが共有しているかが
        必要なため、`(._;>;)`でwayが参照する全nodeを再帰的に取得し、ID付きで返す
        （`GraphService`の`repository`未接続時のみ使う。地域路面レイヤーはPostGISのみを
        参照し、Overpassへは問い合わせない。改善計画T22）。
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
