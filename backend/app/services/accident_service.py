from app.domain.region import tile_bounds_lonlat
from app.infrastructure.accident_repository import ACCIDENT_TILE_SHAPE, AccidentTileQuery
from app.infrastructure.cache_identity import is_known_tile_version
from app.infrastructure.database import DB_UNAVAILABLE_ERRORS
from app.infrastructure.debug_log import mark_failed
from app.infrastructure.vector_tile import encode_empty_accident_tile
from app.infrastructure.media_types import MVT_CONTENT_TYPE
from app.services.tile_serving import TileResponse, serve_cached_tile
from app.services.tile_version_service import served_tile_version

class AccidentService:
    """警察庁交通事故統計データをXYZベクタタイルとして配る。

    road_surfaceと違い「取込範囲の一部だけ取得済み」という状態が無い（バッチが対象地域を
    一括で入れる）ため、カバレッジ判定を持たない。DB障害時は例外にせず
    空タイルを返し、地図表示全体を落とさない。
    """

    def __init__(self, repository: AccidentTileQuery):
        self._repository = repository

    async def get_accident_tile(self, z: int, x: int, y: int) -> TileResponse:
        async def fetch_tile(fields: dict) -> bytes | None:
            try:
                tile_bytes = await self._repository.get_accident_tile_mvt(z, x, y, tile_bounds_lonlat(z, x, y))
            except DB_UNAVAILABLE_ERRORS as exc:
                mark_failed(fields, exc)
                return None
            fields["postgis"] = "hit"
            return tile_bytes

        version = await served_tile_version(self._repository, ACCIDENT_TILE_SHAPE)
        return await serve_cached_tile(
            z=z,
            x=x,
            y=y,
            cache_path=f"region/accidents/v{version}/{z}/{x}/{y}.pbf",
            empty_tile=encode_empty_accident_tile(),
            content_type=MVT_CONTENT_TYPE,
            external_call_name="accident:tile",
            fetch_tile=fetch_tile,
            # 世代を読めていない間はディスクへ残さない（tile_servingのdocstring参照）。
            persist=is_known_tile_version(version),
        )
