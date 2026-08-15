"""警察庁交通事故統計データのMVT生成（外部静的データソース T50、読み取り専用）。

road_graph_repository.py: RoadSurfaceTileQueryと同じST_AsMVTパターンだが、
accident_pointsはOSM由来の`road_graph_tiles`カバレッジとは無関係に独立して取り込まれる
データのため、カバレッジ判定は行わない（「PBF取込範囲外」という概念自体が無い。
`import_accidents.py`が投入した関東7都県分がそのまま常に対象になる）。
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.region import BoundingBox
from app.infrastructure.vector_tile import ACCIDENT_LAYER_NAME, TILE_EXTENT

# ST_AsMVTは集約関数のため、対象0行でもクエリ自体は1行（値NULL）を返す
# （road_graph_repository.pyの_ROAD_SURFACE_TILE_MVT_SQLと同じ挙動）。
_ACCIDENT_TILE_MVT_SQL = text(
    """
    SELECT ST_AsMVT(mvt.*, :layer_name, :extent, 'geom') FROM (
        SELECT
            ST_AsMVTGeom(
                ST_Transform(a.geom, 3857), ST_TileEnvelope(:z, :x, :y), :extent, 256, true
            ) AS geom,
            a.involves_bicycle AS involves_bicycle,
            a.fatal AS fatal,
            a.occurred_year AS occurred_year
        FROM accident_points a
        WHERE ST_Intersects(a.geom, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))
    ) mvt
    WHERE mvt.geom IS NOT NULL
    """
)


class AccidentTileQuery:
    """事故レイヤー表示用のMVT生成。読み取り専用でcommit対象の書き込みは無い。"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_accident_tile_mvt(self, z: int, x: int, y: int, bbox: BoundingBox) -> bytes:
        result = await self._session.execute(
            _ACCIDENT_TILE_MVT_SQL,
            {
                "layer_name": ACCIDENT_LAYER_NAME,
                "extent": TILE_EXTENT,
                "z": z,
                "x": x,
                "y": y,
                "xmin": bbox.min_longitude,
                "ymin": bbox.min_latitude,
                "xmax": bbox.max_longitude,
                "ymax": bbox.max_latitude,
            },
        )
        tile = result.scalar_one()
        return bytes(tile) if tile is not None else b""
