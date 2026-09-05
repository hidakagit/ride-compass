import asyncio

import httpx

from app.domain.attributes import ElevationAttribute, compute_elevation_attribute
from app.domain.graph import DirectedEdge, RoadGraphLike
from app.domain.route import Coordinates
from app.infrastructure.elevation_client import ElevationClient
from app.infrastructure.road_graph_repository import RoadGraphRepository

DATA_SOURCE = "gsi-dem"


class ElevationAttributeService:
    """Road GraphのDirected Edgeへ標高属性（ElevationAttribute）を紐付ける。

    Edgeの形状点（geometry、交差点間のシェイプポイントをそのまま使う）を国土地理院APIへ
    問い合わせる。使用する`ElevationClient`はキャッシュを共有する（緯度経度キャッシュを
    共有するため、同じ地点への問い合わせはキャッシュヒットする）。広いbboxのRoad Graphは
    形状点数が多く、初回はGSIへの問い合わせ数が比例して増える
    （`ElevationClient.MAX_CONCURRENT_REQUESTS`で同時実行数を抑えるのみ）。

    `repository`（infrastructure/road_graph_repository.RoadGraphRepository）を渡すと、
    `get_attributes_for_graph`はEdgeごとにPostGISを先に確認し、既に永続化済みの
    Attributeがあれば国土地理院APIへ問い合わせない。渡さない場合（既定）は、
    毎回全Edgeを問い合わせる。`repository`指定時の前提はdocs/modules/backend/
    elevation.md「事前計算バッチ」節参照（`road_edges`への保存が先に必要）。
    """

    def __init__(
        self,
        client: ElevationClient,
        http_client: httpx.AsyncClient,
        repository: RoadGraphRepository | None = None,
    ):
        self._client = client
        self._http_client = http_client
        self._repository = repository
        # repositoryのAsyncSessionは複数コルーチンからの同時使用が不可なため、
        # repositoryアクセスだけをロックで直列化する（docs/modules/backend/elevation.md
        # 「同時実行制御」参照。GSIへのHTTP問い合わせはロック外のまま並列に走る）。
        self._repository_lock = asyncio.Lock()

    async def get_attributes_for_graph(self, graph: RoadGraphLike) -> dict[str, ElevationAttribute]:
        edges = list(graph.edges.values())

        cached: dict[str, ElevationAttribute] = {}
        if self._repository is not None and edges:
            async with self._repository_lock:
                cached = await self._repository.get_elevation_attributes([e.edge_id for e in edges])

        missing = [e for e in edges if e.edge_id not in cached]
        if not missing:
            return cached

        computed = await self._compute_attributes(missing)

        if self._repository is not None and computed:
            # GSIの一時障害等で該当Edgeの形状点すべてが標高取得に失敗した場合、
            # compute_elevation_attribute（domain/attributes.py）はstart_elevation_m等
            # 全フィールドNoneのAttributeを返す。これをそのまま永続化すると、次回以降
            # get_elevation_attributesのキャッシュ判定（edge_idの行が存在するかのみを見る）
            # がヒットしてしまい、GSI障害が復旧した後も二度と再問い合わせされなくなる。
            # 有効な標高を1つも得られなかった（=start_elevation_mがNoneのまま）Attributeは
            # 永続化せず、次回のget_attributes_for_graph呼び出しで missing 扱いとなり
            # 再試行されるようにする（今回の呼び出し元へは、そのままcomputedに含めて返す。
            # ルート生成側は標高情報無しを許容する既存の設計を踏襲する）。
            persistable = {
                edge_id: attribute for edge_id, attribute in computed.items() if attribute.start_elevation_m is not None
            }
            if persistable:
                async with self._repository_lock:
                    await self._repository.save_elevation_attributes(list(persistable.values()))
                    # repositoryはcommitしない規約（road_graph_repository.pyのdocstring参照）のため、
                    # 保存のまとまりをここで確定する。
                    await self._repository.commit()

        return {**cached, **computed}

    async def _compute_attributes(self, edges: list[DirectedEdge]) -> dict[str, ElevationAttribute]:
        """複数Edgeぶんの形状点をまとめ、1回の`ElevationClient.get_elevations`呼び出しで
        標高を取得する。"""
        all_points: list[Coordinates] = []
        edge_point_ranges: list[tuple[int, int]] = []
        for edge in edges:
            start = len(all_points)
            all_points.extend(Coordinates(latitude=lat, longitude=lon) for lat, lon in edge.geometry)
            edge_point_ranges.append((start, len(all_points)))

        elevations = await self._client.get_elevations(self._http_client, all_points)

        computed: dict[str, ElevationAttribute] = {}
        for edge, (start, end) in zip(edges, edge_point_ranges):
            points = all_points[start:end]
            computed[edge.edge_id] = compute_elevation_attribute(
                edge.edge_id, points, elevations[start:end], data_source=DATA_SOURCE
            )
        return computed
