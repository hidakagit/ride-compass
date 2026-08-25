import logging

from app.domain.region import tile_bounds_lonlat
from app.infrastructure.accident_repository import AccidentTileQuery
from app.infrastructure.vector_tile import encode_empty_accident_tile
from app.services.tile_serving import serve_cached_tile

logger = logging.getLogger("ridecompass.accident")

ACCIDENT_TILE_CONTENT_TYPE = "application/vnd.mapbox-vector-tile"

# タイル内容の世代。region_service.pyのROAD_SURFACE_TILE_VERSIONと同じ理由
# （プロパティを追加した将来、URLを変えて旧世代タイルのブラウザキャッシュを踏まないため）。
ACCIDENT_TILE_VERSION = "1"


def _tile_cache_path(z: int, x: int, y: int) -> str:
    return f"region/accidents/v{ACCIDENT_TILE_VERSION}/{z}/{x}/{y}.pbf"


class AccidentService:
    """警察庁交通事故統計データ（外部静的データソース T50）を、地域路面レイヤーと同じ
    標準的なXYZベクタタイルとして提供する。

    `repository`（AccidentTileQuery）を渡すと`import_accidents.py`が投入済みの
    `accident_points`からPostGIS側（ST_AsMVT）でタイルを生成する。road_surfaceと違い
    「取込範囲の一部だけ取得済み」という状態が無い（バッチが関東7都県を一括で入れる）ため、
    カバレッジ判定は行わない。`repository`未接続、またはDB障害時は空タイルを返す
    （RegionServiceと同じ「地図表示という既存機能全体を落とさず安全側に倒す」方針）。
    """

    def __init__(self, repository: AccidentTileQuery | None = None):
        self._repository = repository

    async def get_accident_tile(self, z: int, x: int, y: int) -> bytes:
        async def fetch_tile(fields: dict) -> bytes | None:
            if self._repository is None:
                # repository未接続（road_graph_use_repository無効時）。データ未整備として
                # 空タイルを返す（ログ方針: 常時WARNING）。
                logger.warning("事故タイルがrepository未接続のため空タイルを返しました z=%d x=%d y=%d", z, x, y)
                return None
            try:
                tile_bytes = await self._repository.get_accident_tile_mvt(z, x, y, tile_bounds_lonlat(z, x, y))
            except Exception as exc:  # noqa: BLE001 DB障害は空タイル返却で吸収する
                logger.warning("事故タイルのPostGIS読み取りに失敗 z=%d x=%d y=%d error=%r", z, x, y, exc)
                fields["postgis"] = "error"
                fields["postgis_error"] = repr(exc)
                return None
            fields["postgis"] = "hit"
            return tile_bytes

        return await serve_cached_tile(
            z=z,
            x=x,
            y=y,
            cache_path=_tile_cache_path(z, x, y),
            empty_tile=encode_empty_accident_tile(),
            content_type=ACCIDENT_TILE_CONTENT_TYPE,
            external_call_name="accident:tile",
            fetch_tile=fetch_tile,
        )
