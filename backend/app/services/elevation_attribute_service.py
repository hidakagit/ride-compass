import asyncio
import logging

import httpx

from app.domain.attributes import ElevationAttribute, compute_elevation_attribute
from app.domain.graph import DirectedEdge, RoadGraphLike
from app.domain.route import Coordinates
from app.infrastructure.elevation_client import ElevationClient
from app.infrastructure.road_graph_repository import RoadGraphRepository

DATA_SOURCE = "gsi-dem"
#: DEMを読み切ったうえで標高が得られなかったEdgeの記録。海上・整備区域外にかかる線が該当し、
#: 何度計算し直しても値は出ない。`DATA_SOURCE`と分けることで、記録のうえで
#: 「試したが値が無い」と「値が取れた」を後から見分けられる。
NO_COVERAGE_DATA_SOURCE = "gsi-dem:no-coverage"

logger = logging.getLogger("ridecompass.elevation_attribute_service")


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

        computed, resolved_edges = await self._compute_attributes(missing)

        if self._repository is not None and computed:
            # 標高が1つも得られなかったEdge（start_elevation_mがNoneのまま）は、理由で
            # 扱いを分ける。**一時障害と、DEMに値が無いことを区別しないと、どちらかを
            # 必ず取り違える**:
            # - GSIの一時障害で読めなかっただけなら、永続化してはいけない。
            #   get_elevation_attributesのキャッシュ判定は行の存在だけを見るため、
            #   障害が復旧しても二度と再問い合わせされなくなる。
            # - DEMの側を読み切ったうえで値が無い（海上・整備区域外）なら、永続化する。
            #   永続化しないと毎回の再計算対象に残り続け、鮮度台帳も「未計算」と数え続ける
            #   ——「試したが値が無い」と「まだ試していない」が区別できない。
            # 後者はdata_sourceで見分けられるようにする（値は全てNoneのままで、ルート生成が
            # 標高情報無しを許容する既存の設計はそのまま）。
            persistable: dict[str, ElevationAttribute] = {}
            for edge_id, attribute in computed.items():
                if attribute.start_elevation_m is not None:
                    persistable[edge_id] = attribute
                elif resolved_edges.get(edge_id):
                    persistable[edge_id] = attribute.model_copy(update={"data_source": NO_COVERAGE_DATA_SOURCE})
            no_coverage = sum(1 for a in persistable.values() if a.data_source == NO_COVERAGE_DATA_SOURCE)
            if no_coverage:
                logger.info("標高: DEMに値が無いEdgeを記録 count=%d", no_coverage)
            if persistable:
                async with self._repository_lock:
                    await self._repository.save_elevation_attributes(list(persistable.values()))
                    # repositoryはcommitしない規約（road_graph_repository.pyのdocstring参照）のため、
                    # 保存のまとまりをここで確定する。
                    await self._repository.commit()

        return {**cached, **computed}

    async def _compute_attributes(
        self, edges: list[DirectedEdge]
    ) -> tuple[dict[str, ElevationAttribute], dict[str, bool]]:
        """複数Edgeぶんの形状点をまとめ、1回の`ElevationClient`呼び出しで標高を取得する。

        併せて返すのは、Edgeの形状点を**すべて読み切れたか**（DEMの側から確かに得たか）。
        1点でも一時障害で読めなかったEdgeはFalseで、呼び出し側が永続化を見送る。
        """
        all_points: list[Coordinates] = []
        edge_point_ranges: list[tuple[int, int]] = []
        for edge in edges:
            start = len(all_points)
            all_points.extend(Coordinates(latitude=lat, longitude=lon) for lat, lon in edge.geometry)
            edge_point_ranges.append((start, len(all_points)))

        lookups = await self._client.get_elevations_with_coverage(self._http_client, all_points)
        elevations = [value for value, _ in lookups]

        computed: dict[str, ElevationAttribute] = {}
        resolved_edges: dict[str, bool] = {}
        for edge, (start, end) in zip(edges, edge_point_ranges):
            points = all_points[start:end]
            computed[edge.edge_id] = compute_elevation_attribute(
                edge.edge_id, points, elevations[start:end], data_source=DATA_SOURCE
            )
            resolved_edges[edge.edge_id] = all(resolved for _, resolved in lookups[start:end])
        return computed, resolved_edges
