import asyncio
import logging

import httpx

from app.domain.region import ROAD_GRAPH_TILE_ZOOM, tile_ancestor, tile_bounds_lonlat
from app.domain.road import classify_osm_surface
from app.infrastructure import tile_cache
from app.infrastructure.debug_log import log_external_call
from app.infrastructure.overpass_client import OverpassClient
from app.infrastructure.vector_tile import encode_road_surface_tile

logger = logging.getLogger("ridecompass.region")

ROAD_SURFACE_TILE_CONTENT_TYPE = "application/vnd.mapbox-vector-tile"


def _tile_cache_path(z: int, x: int, y: int) -> str:
    return f"region/road-surface/{z}/{x}/{y}.pbf"


class RegionService:
    """候補ルートに紐づかない「地域全体」の路面レイヤーを、標準的なXYZベクタタイルとして提供する。

    標高は国土地理院の色別標高図（ラスタタイル）をフロントエンドから直接重ね描きするため、
    バックエンド側の地域取得は路面のみを扱う。
    生成したタイル（MVTバイナリ）はz/x/y単位で基礎地図タイルと同じファイルキャッシュ
    （infrastructure/tile_cache.py）に永続化する。「変わらないデータを更新」ボタンで
    基礎地図タイルと一緒にまとめてキャッシュを消去できる。

    データソース（docs/osm-pbf-import.md Phase 2）:
    `repository`（RoadGraphRepository）を渡すと**PostGISを第一系統**とする。要求タイルの
    z12祖先タイルが取得済みマーク（road_graph_tiles、PBF取込バッチ or Road Graphの
    タイル取得が記録）されていれば、MVTエンコードまで含めてPostGIS側（ST_AsMVT）で
    タイルを丸ごと生成し、Overpassへは一切問い合わせない（way行の転送とPython側の
    エンコードCPU処理を避ける。理由はroad_graph_repository.pyの
    _ROAD_SURFACE_TILE_MVT_SQLコメント参照）。カバレッジ外・DB障害時は
    `overpass_fallback_enabled`に従い従来のOverpass問い合わせへフォールバックする
    （falseなら空タイルを返し、後から取込された際に再生成できるようキャッシュには
    保存しない）。`repository`を渡さない場合（既定）は従来どおりOverpassのみで動作する。
    """

    def __init__(
        self,
        overpass_client: OverpassClient,
        http_client: httpx.AsyncClient,
        repository=None,
        overpass_fallback_enabled: bool = True,
    ):
        self._overpass_client = overpass_client
        self._http_client = http_client
        self._repository = repository
        self._overpass_fallback_enabled = overpass_fallback_enabled

    async def _tile_from_repository(self, z: int, x: int, y: int, fields: dict) -> bytes | None:
        """PostGIS側（ST_AsMVT）でタイル1枚分のMVTを丸ごと生成する。カバレッジ外はNone
        （フォールバック判定へ）。

        DB障害もNoneを返す（ログ方針: エラーは常時WARNINGで出す。障害時にOverpassへ
        フォールバックできる構造を保ち、PostGIS停止が地図の路面表示という既存機能を
        丸ごと壊さないようにする）。
        """
        try:
            ancestor_x, ancestor_y = tile_ancestor(z, x, y, ROAD_GRAPH_TILE_ZOOM)
            if not await self._repository.is_tile_cached(ROAD_GRAPH_TILE_ZOOM, ancestor_x, ancestor_y):
                fields["postgis"] = "uncovered"
                return None
            tile_bytes = await self._repository.get_road_surface_tile_mvt(z, x, y, tile_bounds_lonlat(z, x, y))
        except Exception as exc:  # noqa: BLE001 DB障害はフォールバックで吸収する（上記docstring）
            logger.warning("路面タイルのPostGIS読み取りに失敗 z=%d x=%d y=%d error=%r", z, x, y, exc)
            fields["postgis"] = "error"
            fields["postgis_error"] = repr(exc)
            return None
        fields["postgis"] = "hit"
        return tile_bytes

    async def get_road_surface_tile(self, z: int, x: int, y: int) -> bytes:
        path = _tile_cache_path(z, x, y)

        with log_external_call("region:road-surface-tile", z=z, x=x, y=y) as fields:
            cached = await asyncio.to_thread(tile_cache.get, path)
            if cached is not None:
                fields["cache"] = "hit"
                content, _content_type = cached
                return content
            fields["cache"] = "miss"

            # 第一系統: PostGISでMVTまで丸ごと生成（カバレッジ外・DB障害時はNoneが返り、
            # 以下のOverpass/空タイルへのフォールバックに続く）。
            if self._repository is not None:
                postgis_tile = await self._tile_from_repository(z, x, y, fields)
                if postgis_tile is not None:
                    fields["source"] = "postgis"
                    fields["tile_bytes"] = len(postgis_tile)
                    await asyncio.to_thread(tile_cache.set, path, postgis_tile, ROAD_SURFACE_TILE_CONTENT_TYPE)
                    return postgis_tile

            if self._overpass_fallback_enabled:
                fields["source"] = "overpass"
                bbox = tile_bounds_lonlat(z, x, y)
                raw_ways = await self._overpass_client.get_roads(self._http_client, bbox)
                ways = [
                    {
                        "coordinates": raw["coordinates"],
                        "surface_good": classify_osm_surface(raw.get("tags", {}).get("surface")),
                    }
                    for raw in (raw_ways or [])
                ]
                # Overpass取得に失敗した場合（raw_ways is None）はキャッシュに保存しない。
                # 次回リクエスト時に再取得を試みられるようにするため（cache_db時代の挙動を踏襲）。
                fetch_failed = raw_ways is None
                if fetch_failed:
                    fields["overpass"] = "failed_not_cached"
            else:
                # PostGISのカバレッジ外かつフォールバック無効。データ未整備として空タイルを
                # 返す（ログ方針: 常時WARNING。取込漏れ・範囲外アクセスを運用で気づけるようにする）。
                # 後からPBF取込された際に正しいタイルを再生成できるよう、キャッシュには保存しない。
                logger.warning(
                    "路面タイルがPostGIS取込範囲外（Overpassフォールバック無効） z=%d x=%d y=%d", z, x, y
                )
                fields["source"] = "uncovered_empty"
                ways = []
                fetch_failed = True

            # （ここから下はOverpassフォールバック・空タイルのみが通るPythonエンコード経路。
            # PostGIS第一系統はST_AsMVTがエンコードまで済ませるため通らない）
            # MVTエンコードはCPU専用の同期処理。await無しで直接呼ぶとway数の多い密集タイルで
            # イベントループを数百ms単位で塞ぎ、同時に処理中の他リクエスト（ルート生成等）を
            # 足止めすることが実測で判明したため、tile_cache.get/setと同じくasyncio.to_thread
            # 経由にする（backend/benchmarks/bench_event_loop_stall.py参照）。
            #
            # ここは_tile_from_repositoryと違いtry/exceptで保護されておらず、密集タイル・
            # 同時実行下でのメモリ圧迫等でエンコードが失敗すると素の500がクライアントへ
            # 返っていた（実機で確認: 取込範囲の境界付近でレイヤーON/OFFを繰り返した際に発生）。
            # DB読み取り失敗と同じ「常時WARNING＋安全側で空タイル返却」の方針に合わせる。
            # 空タイルはキャッシュしない（way数が変われば次回成功しうるため）。
            try:
                tile_bytes = await asyncio.to_thread(encode_road_surface_tile, z, x, y, ways)
            except Exception as exc:
                logger.warning(
                    "路面タイルのMVTエンコードに失敗 z=%d x=%d y=%d way_count=%d error=%r",
                    z,
                    x,
                    y,
                    len(ways),
                    exc,
                )
                fields["encode"] = "error"
                fields["encode_error"] = repr(exc)
                return await asyncio.to_thread(encode_road_surface_tile, z, x, y, [])
            fields["way_count"] = len(ways)

            if not fetch_failed:
                await asyncio.to_thread(tile_cache.set, path, tile_bytes, ROAD_SURFACE_TILE_CONTENT_TYPE)
            return tile_bytes
