"""Road Graph・Road AttributeのPostGIS永続化層。

node_id/edge_idはdomain/graph.pyでOSM IDから決定論的に導出されるため、同じ現実の
交差点・道路区間に対する保存は常に同じ主キーへのUPSERT（`Session.merge`）になる。

`get_graph_in_bbox`自体は「指定bboxと交差するEdgeを返す」単純な空間検索であり、
「そのbboxが過去に完全に取得済みかどうか」は判定しない。正確なキャッシュカバレッジ判定は
`RoadGraphTileRow`（タイル取得済みマーカー、is_tile_cached/mark_tile_cached）が担う。
呼び出し側（GraphService）は、対象bboxを覆う全タイルが取得済みであることを先に保証してから
`get_graph_in_bbox`を呼ぶ（地域路面レイヤー/RegionServiceがXYZタイル境界を単位に厳密な
キャッシュ単位を実現しているのと同じ考え方。詳細はdocs/architecture.md参照）。

`save_raw_ways`/`get_way_specs_with_closure`は、タイル境界依存の交差点分割不一致問題
（docs/architecture.md参照）への根本対応として追加した。生のOSM Way/Nodeデータ
（`osm_raw_ways`/`osm_raw_nodes`）は取得元タイルに依存しない安定した永続化層とし、
交差点分割（`build_road_graph`）はDB上の既知の生データ全体から都度計算する。
`save_graph`は`way_ids_to_replace`を指定すると、そのosm_way_id群の既存Edge行を
全削除してから新しい分割結果を挿入し直す（delete-then-reinsert）ことで、Wayの
分割結果が変わった場合に孤立した古いEdge行が残らないようにする。
"""

from datetime import datetime, timezone

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import LineString, Point
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.domain.attributes import ElevationAttribute, SurfaceAttribute
from app.domain.graph import DirectedEdge, Node, RoadGraph, WaySpec
from app.domain.region import BoundingBox
from app.infrastructure.road_graph_models import (
    Base,
    ElevationAttributeRow,
    OsmRawNodeRow,
    OsmRawWayRow,
    RoadEdgeRow,
    RoadGraphTileRow,
    RoadNodeRow,
    SurfaceAttributeRow,
)

CACHED_GRAPH_VERSION = "cached"


async def create_tables(engine: AsyncEngine) -> None:
    """スキーマを作成する（未接続の開発環境では未検証）。PostGIS拡張の有効化を含む。

    Alembic等のマイグレーションツールは導入していない（既存のcache_db.pyと同様、
    CREATE TABLE IF NOT EXISTS相当の最小構成。仕様書12章の「過剰な仕組みを導入しない」
    方針を踏襲）。将来スキーマ変更が頻繁になった段階で見直す。
    """
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.run_sync(Base.metadata.create_all)


def _node_domain_to_row(node: Node, now: datetime) -> RoadNodeRow:
    return RoadNodeRow(
        node_id=node.node_id,
        osm_node_id=node.osm_node_id,
        geom=from_shape(Point(node.longitude, node.latitude), srid=4326),
        updated_at=now,
    )


def _node_row_to_domain(row: RoadNodeRow) -> Node:
    point = to_shape(row.geom)
    return Node(node_id=row.node_id, latitude=point.y, longitude=point.x, osm_node_id=row.osm_node_id)


def _edge_domain_to_row(edge: DirectedEdge, now: datetime) -> RoadEdgeRow:
    # DirectedEdge.geometryは[[lat, lon], ...]だが、Shapely/PostGISの座標順は(lon, lat)。
    line = LineString([(lon, lat) for lat, lon in edge.geometry])
    return RoadEdgeRow(
        edge_id=edge.edge_id,
        from_node_id=edge.from_node_id,
        to_node_id=edge.to_node_id,
        geom=from_shape(line, srid=4326),
        distance_m=edge.distance_m,
        osm_way_id=edge.osm_way_id,
        highway=edge.highway,
        updated_at=now,
    )


def _edge_row_to_domain(row: RoadEdgeRow) -> DirectedEdge:
    line = to_shape(row.geom)
    geometry = [[lat, lon] for lon, lat in line.coords]
    return DirectedEdge(
        edge_id=row.edge_id,
        from_node_id=row.from_node_id,
        to_node_id=row.to_node_id,
        geometry=geometry,
        distance_m=row.distance_m,
        osm_way_id=row.osm_way_id,
        highway=row.highway,
    )


def _elevation_domain_to_row(attribute: ElevationAttribute) -> ElevationAttributeRow:
    return ElevationAttributeRow(
        edge_id=attribute.edge_id,
        start_elevation_m=attribute.start_elevation_m,
        end_elevation_m=attribute.end_elevation_m,
        elevation_gain_m=attribute.elevation_gain_m,
        elevation_loss_m=attribute.elevation_loss_m,
        average_grade=attribute.average_grade,
        max_grade=attribute.max_grade,
        min_grade=attribute.min_grade,
        data_source=attribute.data_source,
        data_version=attribute.data_version,
        calculated_at=datetime.fromisoformat(attribute.calculated_at),
    )


def _elevation_row_to_domain(row: ElevationAttributeRow) -> ElevationAttribute:
    return ElevationAttribute(
        edge_id=row.edge_id,
        start_elevation_m=row.start_elevation_m,
        end_elevation_m=row.end_elevation_m,
        elevation_gain_m=row.elevation_gain_m,
        elevation_loss_m=row.elevation_loss_m,
        average_grade=row.average_grade,
        max_grade=row.max_grade,
        min_grade=row.min_grade,
        data_source=row.data_source,
        data_version=row.data_version,
        calculated_at=row.calculated_at.isoformat(),
    )


def _surface_domain_to_row(attribute: SurfaceAttribute) -> SurfaceAttributeRow:
    return SurfaceAttributeRow(
        edge_id=attribute.edge_id,
        surface_type=attribute.surface_type,
        confidence=attribute.confidence,
        data_source=attribute.data_source,
        data_version=attribute.data_version,
        calculated_at=datetime.fromisoformat(attribute.calculated_at),
    )


def _surface_row_to_domain(row: SurfaceAttributeRow) -> SurfaceAttribute:
    return SurfaceAttribute(
        edge_id=row.edge_id,
        surface_type=row.surface_type,
        confidence=row.confidence,
        data_source=row.data_source,
        data_version=row.data_version,
        calculated_at=row.calculated_at.isoformat(),
    )


def _raw_node_row_to_coords(row: OsmRawNodeRow) -> tuple[float, float]:
    point = to_shape(row.geom)
    return point.y, point.x  # (latitude, longitude)


def _way_spec_row_to_domain(row: OsmRawWayRow) -> WaySpec:
    return WaySpec(
        osm_way_id=row.osm_way_id,
        node_ids=list(row.node_ids),
        highway=row.highway,
        surface=row.surface,
        direction=row.direction,
    )


class RoadGraphRepository:
    """Road Graph・Road AttributeのPostGIS読み書き。1リクエスト（1トランザクション）に
    つき1インスタンスを想定し、`AsyncSession`をDIで受け取る。
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_graph_in_bbox(self, bbox: BoundingBox) -> RoadGraph | None:
        envelope = func.ST_MakeEnvelope(
            bbox.min_longitude, bbox.min_latitude, bbox.max_longitude, bbox.max_latitude, 4326
        )
        edge_stmt = select(RoadEdgeRow).where(func.ST_Intersects(RoadEdgeRow.geom, envelope))
        edge_rows = (await self._session.execute(edge_stmt)).scalars().all()
        if not edge_rows:
            return None

        node_ids = {row.from_node_id for row in edge_rows} | {row.to_node_id for row in edge_rows}
        node_stmt = select(RoadNodeRow).where(RoadNodeRow.node_id.in_(node_ids))
        node_rows = (await self._session.execute(node_stmt)).scalars().all()

        nodes = {row.node_id: _node_row_to_domain(row) for row in node_rows}
        edges = {row.edge_id: _edge_row_to_domain(row) for row in edge_rows}
        return RoadGraph(graph_version=CACHED_GRAPH_VERSION, nodes=nodes, edges=edges)

    async def save_graph(self, graph: RoadGraph, way_ids_to_replace: set[int] | None = None) -> None:
        """RoadGraphをroad_nodes/road_edgesへ永続化する。

        `way_ids_to_replace`を指定した場合、それらのosm_way_idを持つ既存Edge行を
        全削除してから`graph`内の該当Edgeを挿入し直す（delete-then-reinsert）。
        `build_road_graph`は渡されたWay集合全体から交差点を再計算するため、
        Wayの分割結果が前回と変わっていた場合でも、古い分割によるEdge行が
        孤立して残らないようにするための措置（タイル境界依存の分割不一致問題への対応、
        本ファイル冒頭のdocstring参照）。`way_ids_to_replace`外のosm_way_idを持つEdge
        （closureで近傍として取得しただけのWay）はこの呼び出しでは保存しない
        （不完全な文脈で計算した分割結果によって、他のリクエストが正しく永続化した
        Edgeを誤って上書き・破壊しないため）。
        Noneの場合は`graph`内の全Edgeを単純にUPSERTする（従来の挙動）。
        """
        now = datetime.now(timezone.utc)
        for node in graph.nodes.values():
            await self._session.merge(_node_domain_to_row(node, now))
        # Edgeがroad_nodes.node_idを外部キー参照するため、先にNodeをflushしておく。
        await self._session.flush()

        if way_ids_to_replace:
            await self._session.execute(delete(RoadEdgeRow).where(RoadEdgeRow.osm_way_id.in_(way_ids_to_replace)))
            await self._session.flush()

        for edge in graph.edges.values():
            if way_ids_to_replace is not None and edge.osm_way_id not in way_ids_to_replace:
                continue
            await self._session.merge(_edge_domain_to_row(edge, now))
        await self._session.commit()

    async def save_raw_ways(self, way_specs: list[WaySpec], node_coords: dict[int, tuple[float, float]]) -> None:
        """生のOSM Way/Nodeデータを永続化する。Wayのタグ・ノード列は取得元タイルに
        依存せず一意に決まるため、build_road_graphの分割結果とは異なり素直にUPSERTしてよい。
        """
        if not way_specs:
            return
        now = datetime.now(timezone.utc)
        referenced_node_ids = {node_id for way in way_specs for node_id in way.node_ids}
        for node_id in referenced_node_ids:
            coords = node_coords.get(node_id)
            if coords is None:
                continue
            lat, lon = coords
            await self._session.merge(
                OsmRawNodeRow(osm_node_id=node_id, geom=from_shape(Point(lon, lat), srid=4326), updated_at=now)
            )
        await self._session.flush()

        for way in way_specs:
            if way.osm_way_id is None:
                continue
            await self._session.merge(
                OsmRawWayRow(
                    osm_way_id=way.osm_way_id,
                    node_ids=way.node_ids,
                    highway=way.highway,
                    surface=way.surface,
                    direction=way.direction,
                    updated_at=now,
                )
            )
        await self._session.commit()

    async def get_way_specs_with_closure(
        self, bbox: BoundingBox
    ) -> tuple[list[WaySpec], dict[int, tuple[float, float]], set[int]]:
        """bbox内に少なくとも1つノードを持つ「主対象Way」と、それらのWayが参照する
        全ノード（Way全長分、bbox外の部分も含む）を1つでも共有する「近傍Way」を
        合わせて返す。この近傍Wayとの重ね合わせによって、build_road_graphが
        タイル境界や要求bboxの境界に関わらず正しく交差点を判定できるようにする
        （タイル境界依存の分割不一致問題への根本対応）。

        戻り値は(WaySpec一覧, それらが参照する全ノードの座標, 主対象WayのosmWay ID集合)。
        3つ目の要素は`save_graph`の`way_ids_to_replace`にそのまま渡す想定（近傍Wayは
        文脈情報としてのみ使い、この呼び出しでは永続化し直さないため）。

        既知の残存制約: 近傍Wayの探索は1ホップに限定している（近傍Wayがさらに別のWayと
        共有するノードは辿らない）。そのため、主対象Wayでも近傍Wayでもない、間接的に
        関係するWay同士の交差点は、そのWay自身が別のリクエストで「主対象」として
        処理されるまで最新の状態に更新されない（結果整合的）。これは、道路網全体の
        連結成分を毎回たどる完全な整合性チェックとのトレードオフとして許容している
        （docs/architecture.md参照）。
        """
        envelope = func.ST_MakeEnvelope(
            bbox.min_longitude, bbox.min_latitude, bbox.max_longitude, bbox.max_latitude, 4326
        )
        primary_node_stmt = select(OsmRawNodeRow.osm_node_id).where(func.ST_Intersects(OsmRawNodeRow.geom, envelope))
        primary_node_ids = list((await self._session.execute(primary_node_stmt)).scalars().all())
        if not primary_node_ids:
            return [], {}, set()

        primary_way_stmt = select(OsmRawWayRow).where(OsmRawWayRow.node_ids.overlap(primary_node_ids))
        primary_way_rows = (await self._session.execute(primary_way_stmt)).scalars().all()
        primary_way_ids = {row.osm_way_id for row in primary_way_rows}

        all_referenced_node_ids = list({node_id for row in primary_way_rows for node_id in row.node_ids})
        neighbor_way_stmt = select(OsmRawWayRow).where(OsmRawWayRow.node_ids.overlap(all_referenced_node_ids))
        neighbor_way_rows = (await self._session.execute(neighbor_way_stmt)).scalars().all()

        combined_rows_by_id = {row.osm_way_id: row for row in [*primary_way_rows, *neighbor_way_rows]}
        way_specs = [_way_spec_row_to_domain(row) for row in combined_rows_by_id.values()]

        final_node_ids = list({node_id for way in way_specs for node_id in way.node_ids})
        node_stmt = select(OsmRawNodeRow).where(OsmRawNodeRow.osm_node_id.in_(final_node_ids))
        node_rows = (await self._session.execute(node_stmt)).scalars().all()
        node_coords = {row.osm_node_id: _raw_node_row_to_coords(row) for row in node_rows}

        return way_specs, node_coords, primary_way_ids

    async def get_elevation_attributes(self, edge_ids: list[str]) -> dict[str, ElevationAttribute]:
        if not edge_ids:
            return {}
        stmt = select(ElevationAttributeRow).where(ElevationAttributeRow.edge_id.in_(edge_ids))
        rows = (await self._session.execute(stmt)).scalars().all()
        return {row.edge_id: _elevation_row_to_domain(row) for row in rows}

    async def save_elevation_attributes(self, attributes: list[ElevationAttribute]) -> None:
        if not attributes:
            return
        for attribute in attributes:
            await self._session.merge(_elevation_domain_to_row(attribute))
        await self._session.commit()

    async def get_surface_attributes(self, edge_ids: list[str]) -> dict[str, SurfaceAttribute]:
        if not edge_ids:
            return {}
        stmt = select(SurfaceAttributeRow).where(SurfaceAttributeRow.edge_id.in_(edge_ids))
        rows = (await self._session.execute(stmt)).scalars().all()
        return {row.edge_id: _surface_row_to_domain(row) for row in rows}

    async def save_surface_attributes(self, attributes: list[SurfaceAttribute]) -> None:
        if not attributes:
            return
        for attribute in attributes:
            await self._session.merge(_surface_domain_to_row(attribute))
        await self._session.commit()

    async def is_tile_cached(self, zoom: int, x: int, y: int) -> bool:
        stmt = select(RoadGraphTileRow).where(
            RoadGraphTileRow.zoom == zoom, RoadGraphTileRow.x == x, RoadGraphTileRow.y == y
        )
        row = (await self._session.execute(stmt)).scalars().first()
        return row is not None

    async def mark_tile_cached(self, zoom: int, x: int, y: int) -> None:
        await self._session.merge(
            RoadGraphTileRow(zoom=zoom, x=x, y=y, fetched_at=datetime.now(timezone.utc))
        )
        await self._session.commit()
