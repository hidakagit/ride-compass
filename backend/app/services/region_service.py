import asyncio

import httpx

from app.domain.region import tile_bounds_lonlat
from app.domain.road import classify_osm_surface
from app.infrastructure import tile_cache
from app.infrastructure.debug_log import log_external_call
from app.infrastructure.overpass_client import OverpassClient
from app.infrastructure.vector_tile import encode_road_surface_tile

ROAD_SURFACE_TILE_CONTENT_TYPE = "application/vnd.mapbox-vector-tile"


def _tile_cache_path(z: int, x: int, y: int) -> str:
    return f"region/road-surface/{z}/{x}/{y}.pbf"


class RegionService:
    """候補ルートに紐づかない「地域全体」の路面レイヤーを、標準的なXYZベクタタイルとして提供する。

    標高は国土地理院の色別標高図（ラスタタイル）をフロントエンドから直接重ね描きするため、
    バックエンド側の地域取得は路面（Overpass由来）のみを扱う。
    生成したタイル（MVTバイナリ）はz/x/y単位で基礎地図タイルと同じファイルキャッシュ
    （infrastructure/tile_cache.py）に永続化する。「変わらないデータを更新」ボタンで
    基礎地図タイルと一緒にまとめてキャッシュを消去できる。
    """

    def __init__(self, overpass_client: OverpassClient, http_client: httpx.AsyncClient):
        self._overpass_client = overpass_client
        self._http_client = http_client

    async def get_road_surface_tile(self, z: int, x: int, y: int) -> bytes:
        path = _tile_cache_path(z, x, y)

        with log_external_call("region:road-surface-tile", z=z, x=x, y=y) as fields:
            cached = await asyncio.to_thread(tile_cache.get, path)
            if cached is not None:
                fields["cache"] = "hit"
                content, _content_type = cached
                return content
            fields["cache"] = "miss"

            bbox = tile_bounds_lonlat(z, x, y)
            raw_ways = await self._overpass_client.get_roads(self._http_client, bbox)
            ways = [
                {"coordinates": raw["coordinates"], "surface_good": classify_osm_surface(raw.get("tags", {}).get("surface"))}
                for raw in (raw_ways or [])
            ]
            # MVTエンコードはCPU専用の同期処理。await無しで直接呼ぶとway数の多い密集タイルで
            # イベントループを数百ms単位で塞ぎ、同時に処理中の他リクエスト（ルート生成等）を
            # 足止めすることが実測で判明したため、tile_cache.get/setと同じくasyncio.to_thread
            # 経由にする（backend/benchmarks/bench_event_loop_stall.py参照）。
            tile_bytes = await asyncio.to_thread(encode_road_surface_tile, z, x, y, ways)
            fields["way_count"] = len(ways)

            # Overpass取得に失敗した場合（raw_ways is None）はキャッシュに保存しない。
            # 次回リクエスト時に再取得を試みられるようにするため（cache_db時代の挙動を踏襲）。
            if raw_ways is not None:
                await asyncio.to_thread(tile_cache.set, path, tile_bytes, ROAD_SURFACE_TILE_CONTENT_TYPE)
            else:
                fields["overpass"] = "failed_not_cached"
            return tile_bytes
