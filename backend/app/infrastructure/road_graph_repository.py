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

from collections.abc import Iterator
from datetime import datetime, timezone

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import LineString, Point
from sqlalchemy import BigInteger, any_, cast, delete, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
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

# バルクUPSERT1文あたりの行数。asyncpgのプリペアド文パラメータ上限（32767個）を
# 最も列数の多いテーブル（8列）でも十分下回るサイズにする。
_BULK_CHUNK_ROWS = 1000
# IN句・削除等でIDリストを分割するサイズ（1要素=1パラメータのため上限に余裕を持たせる）
_ID_CHUNK_SIZE = 10_000


def _chunked(items: list, size: int) -> Iterator[list]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


async def create_tables(engine: AsyncEngine) -> None:
    """スキーマを作成する。PostGIS拡張の有効化を含む。

    Alembic等のマイグレーションツールは導入していない（既存のcache_db.pyと同様、
    CREATE TABLE IF NOT EXISTS相当の最小構成。仕様書12章の「過剰な仕組みを導入しない」
    方針を踏襲）。将来スキーマ変更が頻繁になった段階で見直す。

    create_allは既存テーブルへの列追加を行わないため、後から追加した列は
    ADD COLUMN IF NOT EXISTSで冪等に補う（新規DBではcreate_allが列・索引ごと作るため
    no-opになる。索引名idx_osm_raw_ways_geomはGeoAlchemy2のspatial_index=Trueが
    生成する既定名に合わせている）。
    """
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.run_sync(Base.metadata.create_all)
        # PBF取込（Phase 1）で追加したosm_raw_ways.geom列（既存DB向けの冪等な追加）
        await conn.execute(
            text("ALTER TABLE osm_raw_ways ADD COLUMN IF NOT EXISTS geom geometry(LINESTRING,4326)")
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_osm_raw_ways_geom ON osm_raw_ways USING gist (geom)")
        )
        # geom列導入前に保存された既存行のバックフィル（node_ids→osm_raw_nodesから
        # LINESTRINGを再構成）。get_way_specs_with_closureはgeomを前提とした空間検索の
        # ため、NULLのままだと旧データが閉包対象から漏れる。座標が判明しているノードが
        # 2点未満の行はNULLのまま（save_raw_ways/PBF取込と同じ意味論）。
        await conn.execute(
            text(
                """
                UPDATE osm_raw_ways w
                SET geom = sub.line
                FROM (
                    SELECT w2.osm_way_id, ST_MakeLine(n.geom ORDER BY u.ord) AS line
                    FROM osm_raw_ways w2
                    JOIN LATERAL unnest(w2.node_ids) WITH ORDINALITY AS u(node_id, ord) ON true
                    JOIN osm_raw_nodes n ON n.osm_node_id = u.node_id
                    WHERE w2.geom IS NULL
                    GROUP BY w2.osm_way_id
                    HAVING count(*) >= 2
                ) sub
                WHERE w.osm_way_id = sub.osm_way_id
                """
            )
        )
        # 旧・閉包クエリ用のGINインデックス（node_ids &&）の廃止（既存DB向けの冪等な削除）。
        # geom列の空間検索への置き換えで未使用になり、実測28MB（東京都心取込時）を占めて
        # いたため、Supabaseフリープラン等の容量制約に合わせて削除する
        # （road_graph_models.py: OsmRawWayRowのdocstring参照）。
        await conn.execute(text("DROP INDEX IF EXISTS ix_osm_raw_ways_node_ids"))


def _node_row_to_domain(row: RoadNodeRow) -> Node:
    point = to_shape(row.geom)
    return Node(node_id=row.node_id, latitude=point.y, longitude=point.x, osm_node_id=row.osm_node_id)


def _edge_row_to_domain(row: RoadEdgeRow) -> DirectedEdge:
    # DirectedEdge.geometryは[[lat, lon], ...]だが、Shapely/PostGISの座標順は(lon, lat)。
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

    async def _bulk_upsert(
        self,
        model,
        rows: list[dict],
        index_elements: list[str],
        update_columns: list[str] | None,
    ) -> None:
        """INSERT ... ON CONFLICTによるバルクUPSERT。

        行単位のSession.mergeは1行ごとにSELECT+INSERT/UPDATEのラウンドトリップが発生し、
        都心部のbbox（数万Node・十数万Edge）では1リクエストが数十分オーダーになることを
        実機で確認したため（設計レビュー指摘7）、複数行VALUESの一括文に置き換えた。
        update_columns=Noneは競合時に何もしない（DO NOTHING）。
        """
        for chunk in _chunked(rows, _BULK_CHUNK_ROWS):
            stmt = pg_insert(model).values(chunk)
            if update_columns:
                stmt = stmt.on_conflict_do_update(
                    index_elements=index_elements,
                    set_={column: stmt.excluded[column] for column in update_columns},
                )
            else:
                stmt = stmt.on_conflict_do_nothing(index_elements=index_elements)
            await self._session.execute(stmt)

    async def get_graph_in_bbox(self, bbox: BoundingBox) -> RoadGraph | None:
        envelope = func.ST_MakeEnvelope(
            bbox.min_longitude, bbox.min_latitude, bbox.max_longitude, bbox.max_latitude, 4326
        )
        edge_stmt = select(RoadEdgeRow).where(func.ST_Intersects(RoadEdgeRow.geom, envelope))
        edge_rows = (await self._session.execute(edge_stmt)).scalars().all()
        if not edge_rows:
            return None

        node_ids = sorted({row.from_node_id for row in edge_rows} | {row.to_node_id for row in edge_rows})
        # 都心部のbboxではNode数が数万件になり、IN句展開はasyncpgのパラメータ上限
        # （32767個）を超えうるためチャンク分割する。
        node_rows = []
        for id_chunk in _chunked(node_ids, _ID_CHUNK_SIZE):
            node_stmt = select(RoadNodeRow).where(RoadNodeRow.node_id.in_(id_chunk))
            node_rows.extend((await self._session.execute(node_stmt)).scalars().all())

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
        # Edgeがroad_nodes.node_idを外部キー参照するため、先にNodeを一括UPSERTする
        # （同一トランザクション内のため文の実行順で制約を満たせる）。
        node_rows = [
            {
                "node_id": node.node_id,
                "osm_node_id": node.osm_node_id,
                "geom": from_shape(Point(node.longitude, node.latitude), srid=4326),
                "updated_at": now,
            }
            for node in graph.nodes.values()
        ]
        await self._bulk_upsert(RoadNodeRow, node_rows, ["node_id"], ["osm_node_id", "geom", "updated_at"])

        if way_ids_to_replace:
            for id_chunk in _chunked(sorted(way_ids_to_replace), _ID_CHUNK_SIZE):
                await self._session.execute(delete(RoadEdgeRow).where(RoadEdgeRow.osm_way_id.in_(id_chunk)))

        edge_rows = [
            {
                "edge_id": edge.edge_id,
                "from_node_id": edge.from_node_id,
                "to_node_id": edge.to_node_id,
                "geom": from_shape(LineString([(lon, lat) for lat, lon in edge.geometry]), srid=4326),
                "distance_m": edge.distance_m,
                "osm_way_id": edge.osm_way_id,
                "highway": edge.highway,
                "updated_at": now,
            }
            for edge in graph.edges.values()
            if way_ids_to_replace is None or edge.osm_way_id in way_ids_to_replace
        ]
        await self._bulk_upsert(
            RoadEdgeRow,
            edge_rows,
            ["edge_id"],
            ["from_node_id", "to_node_id", "geom", "distance_m", "osm_way_id", "highway", "updated_at"],
        )
        await self._session.commit()

    async def save_raw_ways(self, way_specs: list[WaySpec], node_coords: dict[int, tuple[float, float]]) -> None:
        """生のOSM Way/Nodeデータを永続化する。Wayのタグ・ノード列は取得元タイルに
        依存せず一意に決まるため、build_road_graphの分割結果とは異なり素直にUPSERTしてよい。
        """
        if not way_specs:
            return
        now = datetime.now(timezone.utc)
        referenced_node_ids = {node_id for way in way_specs for node_id in way.node_ids}
        node_rows = []
        for node_id in sorted(referenced_node_ids):
            coords = node_coords.get(node_id)
            if coords is None:
                continue
            lat, lon = coords
            node_rows.append(
                {
                    "osm_node_id": node_id,
                    "geom": from_shape(Point(lon, lat), srid=4326),
                    "updated_at": now,
                }
            )
        await self._bulk_upsert(OsmRawNodeRow, node_rows, ["osm_node_id"], ["geom", "updated_at"])

        way_rows_by_id: dict[int, dict] = {}
        for way in way_specs:
            if way.osm_way_id is None:
                continue
            # 実体化済みLINESTRING（座標が判明しているノードが2点未満ならNULL）。
            # PBF取込バッチと同じ意味論（road_graph_models.py: OsmRawWayRow.geomのコメント参照）。
            way_coords = [node_coords[n] for n in way.node_ids if n in node_coords]
            geom = (
                from_shape(LineString([(lon, lat) for lat, lon in way_coords]), srid=4326)
                if len(way_coords) >= 2
                else None
            )
            way_rows_by_id[way.osm_way_id] = {
                "osm_way_id": way.osm_way_id,
                "node_ids": way.node_ids,
                "highway": way.highway,
                "surface": way.surface,
                "direction": way.direction,
                "geom": geom,
                "updated_at": now,
            }
        await self._bulk_upsert(
            OsmRawWayRow,
            list(way_rows_by_id.values()),
            ["osm_way_id"],
            ["node_ids", "highway", "surface", "direction", "geom", "updated_at"],
        )
        await self._session.commit()

    async def get_way_specs_with_closure(
        self, bbox: BoundingBox
    ) -> tuple[list[WaySpec], dict[int, tuple[float, float]], set[int]]:
        """bboxとジオメトリが交差する「主対象Way」と、それらの周辺文脈となる「近傍Way」を
        合わせて返す。近傍Wayとの重ね合わせによって、build_road_graphがタイル境界や
        要求bboxの境界に関わらず正しく交差点を判定できるようにする
        （タイル境界依存の分割不一致問題への根本対応）。

        当初の実装は「bbox内にノードを持つWay」→「そのノード配列と重なるWay」という
        node_ids配列のGIN検索（&&）だったが、都心部のbboxでは配列パラメータが数十万
        要素になり実用的な速度が出ないことを実機で確認した。現在は次の空間検索へ
        置き換えている（geom列＝Phase 1で追加した実体化済みLINESTRINGが前提。
        NULLのままの旧データはcreate_tablesのバックフィルで補われる）:

        1. 主対象Way: bboxのenvelopeとST_Intersectsで交差するWay（旧実装の「bbox内に
           ノードを持つ」の上位互換。頂点がbbox内に無くてもbboxを横切るWayを含む）
        2. 近傍Way: 主対象Way全体のextent（全長分の外接矩形、bbox外の部分も含む）と
           交差するWay。「主対象とノードを共有するWay」の厳密な上位集合であり、
           余分に含まれるWayは交差点判定の文脈情報が増えるだけで正しさを損なわない
           （近傍Wayはこの呼び出しでは永続化しないため）

        戻り値は(WaySpec一覧, それらが参照する全ノードの座標, 主対象WayのosmWay ID集合)。
        3つ目の要素は`save_graph`の`way_ids_to_replace`にそのまま渡す想定。

        既知の残存制約: 近傍の探索は1ホップ相当に限定している（近傍Wayのさらに先の
        接続は辿らない）。間接的に関係するWay同士の交差点は、そのWay自身が別の
        リクエストで「主対象」として処理されるまで更新されない（結果整合的、
        docs/architecture.md参照）。
        """
        bbox_params = {
            "xmin": bbox.min_longitude,
            "ymin": bbox.min_latitude,
            "xmax": bbox.max_longitude,
            "ymax": bbox.max_latitude,
        }
        envelope = func.ST_MakeEnvelope(
            bbox.min_longitude, bbox.min_latitude, bbox.max_longitude, bbox.max_latitude, 4326
        )
        primary_id_stmt = select(OsmRawWayRow.osm_way_id).where(
            OsmRawWayRow.geom.is_not(None), func.ST_Intersects(OsmRawWayRow.geom, envelope)
        )
        primary_way_ids = set((await self._session.execute(primary_id_stmt)).scalars().all())
        if not primary_way_ids:
            return [], {}, set()

        # 主対象Wayの全長分のextent（1回の集約クエリでbbox外へのはみ出し範囲を得る）
        extent_row = (
            await self._session.execute(
                text(
                    "SELECT ST_XMin(e) AS xmin, ST_YMin(e) AS ymin, ST_XMax(e) AS xmax, ST_YMax(e) AS ymax "
                    "FROM (SELECT ST_Extent(geom) AS e FROM osm_raw_ways "
                    "WHERE geom IS NOT NULL "
                    "AND ST_Intersects(geom, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))) s"
                ),
                bbox_params,
            )
        ).one()

        extent_envelope = func.ST_MakeEnvelope(
            extent_row.xmin, extent_row.ymin, extent_row.xmax, extent_row.ymax, 4326
        )
        way_stmt = select(OsmRawWayRow).where(
            OsmRawWayRow.geom.is_not(None), func.ST_Intersects(OsmRawWayRow.geom, extent_envelope)
        )
        way_rows = (await self._session.execute(way_stmt)).scalars().all()
        way_specs = [_way_spec_row_to_domain(row) for row in way_rows]

        # ノード座標はWayが実際に参照するIDで正確に引く（=ANY(配列)は1パラメータで済み、
        # IN句のようなパラメータ数上限の問題を起こさない）。
        final_node_ids = sorted({node_id for way in way_specs for node_id in way.node_ids})
        node_coords: dict[int, tuple[float, float]] = {}
        for id_chunk in _chunked(final_node_ids, 50_000):
            node_stmt = select(OsmRawNodeRow).where(
                OsmRawNodeRow.osm_node_id == any_(cast(id_chunk, ARRAY(BigInteger)))
            )
            for row in (await self._session.execute(node_stmt)).scalars().all():
                node_coords[row.osm_node_id] = _raw_node_row_to_coords(row)

        return way_specs, node_coords, primary_way_ids

    async def get_road_surface_ways_in_bbox(
        self, bbox: BoundingBox
    ) -> list[tuple[list[list[float]], str | None]]:
        """地域路面レイヤー（RegionServiceのMVTタイル生成）用に、bboxと交差するWayの
        ジオメトリ（[[lat, lon], ...]）とsurfaceタグを返す（docs/osm-pbf-import.md Phase 2）。

        Road Graph構築（get_way_specs_with_closure）と異なり交差点分割・近傍closureは
        不要で、表示に必要な「線とsurfaceタグ」だけを実体化済みgeom列から直接引く。
        カバレッジ判定（このbboxのデータが取込済みか）は行わない。呼び出し側
        （RegionService）がis_tile_cachedで先に保証すること。
        """
        envelope = func.ST_MakeEnvelope(
            bbox.min_longitude, bbox.min_latitude, bbox.max_longitude, bbox.max_latitude, 4326
        )
        stmt = select(OsmRawWayRow.geom, OsmRawWayRow.surface).where(
            OsmRawWayRow.geom.is_not(None), func.ST_Intersects(OsmRawWayRow.geom, envelope)
        )
        rows = (await self._session.execute(stmt)).all()
        ways: list[tuple[list[list[float]], str | None]] = []
        for geom, surface in rows:
            line = to_shape(geom)
            ways.append(([[lat, lon] for lon, lat in line.coords], surface))
        return ways

    async def get_elevation_attributes(self, edge_ids: list[str]) -> dict[str, ElevationAttribute]:
        if not edge_ids:
            return {}
        result: dict[str, ElevationAttribute] = {}
        for id_chunk in _chunked(edge_ids, _ID_CHUNK_SIZE):
            stmt = select(ElevationAttributeRow).where(ElevationAttributeRow.edge_id.in_(id_chunk))
            for row in (await self._session.execute(stmt)).scalars().all():
                result[row.edge_id] = _elevation_row_to_domain(row)
        return result

    async def save_elevation_attributes(self, attributes: list[ElevationAttribute]) -> None:
        if not attributes:
            return
        rows = [
            {
                "edge_id": a.edge_id,
                "start_elevation_m": a.start_elevation_m,
                "end_elevation_m": a.end_elevation_m,
                "elevation_gain_m": a.elevation_gain_m,
                "elevation_loss_m": a.elevation_loss_m,
                "average_grade": a.average_grade,
                "max_grade": a.max_grade,
                "min_grade": a.min_grade,
                "data_source": a.data_source,
                "data_version": a.data_version,
                "calculated_at": datetime.fromisoformat(a.calculated_at),
            }
            for a in attributes
        ]
        await self._bulk_upsert(
            ElevationAttributeRow,
            rows,
            ["edge_id"],
            [
                "start_elevation_m", "end_elevation_m", "elevation_gain_m", "elevation_loss_m",
                "average_grade", "max_grade", "min_grade", "data_source", "data_version", "calculated_at",
            ],
        )
        await self._session.commit()

    async def get_surface_attributes(self, edge_ids: list[str]) -> dict[str, SurfaceAttribute]:
        if not edge_ids:
            return {}
        result: dict[str, SurfaceAttribute] = {}
        for id_chunk in _chunked(edge_ids, _ID_CHUNK_SIZE):
            stmt = select(SurfaceAttributeRow).where(SurfaceAttributeRow.edge_id.in_(id_chunk))
            for row in (await self._session.execute(stmt)).scalars().all():
                result[row.edge_id] = _surface_row_to_domain(row)
        return result

    async def save_surface_attributes(self, attributes: list[SurfaceAttribute]) -> None:
        if not attributes:
            return
        rows = [
            {
                "edge_id": a.edge_id,
                "surface_type": a.surface_type,
                "confidence": a.confidence,
                "data_source": a.data_source,
                "data_version": a.data_version,
                "calculated_at": datetime.fromisoformat(a.calculated_at),
            }
            for a in attributes
        ]
        await self._bulk_upsert(
            SurfaceAttributeRow,
            rows,
            ["edge_id"],
            ["surface_type", "confidence", "data_source", "data_version", "calculated_at"],
        )
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
