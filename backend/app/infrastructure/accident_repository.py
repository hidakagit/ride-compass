"""警察庁交通事故統計データのMVT生成（読み取り専用）。

路面タイルと同じST_AsMVTのパターンだが、カバレッジ判定は行わない——事故は対象範囲を
一括で取り込むため「取込範囲の一部だけ取得済み」という状態が無い。

表示に使う値（死亡事故か・自転車が絡むか・発生年）は生データの列から都度導く。判定の
規則は`domain/accident.py`が持ち、集計（`derive_counts.py`）と同じものを使う。
"""

from sqlalchemy import Text, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.accident import (
    BICYCLE_PARTY_TYPE_CODES,
    BICYCLE_SQL,
    FATAL_SQL,
    OCCURRED_YEAR_SQL,
)
from app.domain.region import BoundingBox
from app.infrastructure.cache_identity import shape_digest
from app.infrastructure.vector_tile import ACCIDENT_LAYER_NAME, TILE_EXTENT

# ST_AsMVTは集約関数のため、対象0行でもクエリ自体は1行（値NULL）を返す。
_ACCIDENT_TILE_MVT_SQL = text(
    f"""
    SELECT ST_AsMVT(mvt.*, :layer_name, :extent, 'geom') FROM (
        SELECT
            ST_AsMVTGeom(
                ST_Transform(a.geom, 3857), ST_TileEnvelope(:z, :x, :y), :extent, 256, true
            ) AS geom,
            {BICYCLE_SQL} AS involves_bicycle,
            {FATAL_SQL} AS fatal,
            {OCCURRED_YEAR_SQL} AS occurred_year
        FROM source_features a
        WHERE a.source = 'accident'
          AND ST_Intersects(a.geom, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))
    ) mvt
    WHERE mvt.geom IS NOT NULL
    """
).bindparams(
    bindparam("bicycle_party_types", value=sorted(BICYCLE_PARTY_TYPE_CODES), type_=ARRAY(Text()))
)


# タイルのキャッシュパスへ入る形の署名（焼き込むSQLから導出する）。
ACCIDENT_TILE_SHAPE = shape_digest(_ACCIDENT_TILE_MVT_SQL)


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
