import asyncio

import httpx

from app.domain.attributes import ElevationAttribute, compute_elevation_attribute
from app.domain.graph import DirectedEdge, RoadGraph
from app.domain.route import Coordinates
from app.infrastructure.elevation_client import ElevationClient

MAX_CONCURRENT_REQUESTS = 5
DATA_SOURCE = "gsi-dem"


class ElevationAttributeService:
    """Road GraphのDirected Edgeへ標高属性（ElevationAttribute）を紐付ける（仕様書13-15章、Phase 3）。

    既存の`ElevationService`（ルート単位、12点サンプリングに合わせた設計）とは別に、
    Edgeの形状点（geometry、交差点間のシェイプポイントをそのまま使う）を国土地理院APIへ
    問い合わせる。使用する`ElevationClient`は既存と同じ（緯度経度キャッシュを共有するため、
    ルート生成側で既に問い合わせ済みの地点はキャッシュヒットする）。

    既知の制約: 広いbboxのRoad Graphは形状点数が多く、初回はGSIへの問い合わせ数が
    比例して増える（`MAX_CONCURRENT_REQUESTS`で同時実行数を抑えるのみ）。

    `repository`（infrastructure/road_graph_repository.RoadGraphRepository）を渡すと、
    `get_attributes_for_graph`はEdgeごとにPostGISを先に確認し、既に永続化済みの
    Attributeがあれば国土地理院APIへ問い合わせない。渡さない場合（既定）は、
    Phase 3と同じ「毎回全Edgeを問い合わせる」挙動のまま。

    重要な前提（`repository`指定時）: `elevation_attributes`テーブルは`road_edges.edge_id`
    への外部キー（ON DELETE CASCADE）を持つため、渡す`graph`は事前に同じ`repository`
    経由でDBへ保存済み（`road_edges`にそのedge_idの行が存在する状態）でなければならない。
    `GraphService.get_or_build_graph_with_attributes`で得たRoadGraphはこの条件を満たすが、
    `GraphService.build_graph_for_bbox`等の非キャッシュ系メソッドで得たRoadGraph（DB未保存）
    を`repository`指定時に渡すと、`save_elevation_attributes`が外部キー制約違反で失敗する。
    """

    def __init__(self, client: ElevationClient, http_client: httpx.AsyncClient, repository=None):
        self._client = client
        self._http_client = http_client
        self._repository = repository
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def get_attributes_for_graph(self, graph: RoadGraph) -> dict[str, ElevationAttribute]:
        edges = list(graph.edges.values())

        cached: dict[str, ElevationAttribute] = {}
        if self._repository is not None and edges:
            cached = await self._repository.get_elevation_attributes([e.edge_id for e in edges])

        missing = [e for e in edges if e.edge_id not in cached]
        if not missing:
            return cached

        results = await asyncio.gather(*(self._get_attribute(edge) for edge in missing))
        computed = {edge.edge_id: attribute for edge, attribute in zip(missing, results)}

        if self._repository is not None and computed:
            await self._repository.save_elevation_attributes(list(computed.values()))

        return {**cached, **computed}

    async def _get_attribute(self, edge: DirectedEdge) -> ElevationAttribute:
        points = [Coordinates(latitude=lat, longitude=lon) for lat, lon in edge.geometry]

        async def fetch(point: Coordinates) -> float | None:
            async with self._semaphore:
                return await self._client.get_elevation(self._http_client, point)

        elevations = await asyncio.gather(*(fetch(p) for p in points))
        return compute_elevation_attribute(edge.edge_id, points, elevations, data_source=DATA_SOURCE)
