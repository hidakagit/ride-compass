import asyncio
import logging

from app.domain.region import ROAD_GRAPH_TILE_ZOOM, tile_ancestor, tile_bounds_lonlat
from app.infrastructure import tile_cache
from app.infrastructure.debug_log import log_external_call
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.infrastructure.vector_tile import encode_empty_poi_tile, encode_empty_road_surface_tile

logger = logging.getLogger("ridecompass.region")

# road_surface・poi両タイルで共通のMVT MIMEタイプ（改善計画T54でroad限定の名前から一般化）。
MVT_CONTENT_TYPE = "application/vnd.mapbox-vector-tile"

# タイル内容の世代。パスへ世代を含めることで、プロパティ追加前に保存された旧タイルを
# キャッシュヒットさせない（旧世代のファイルは「変わらないデータを更新」のclear_allで
# まとめて消える）。フロントエンドのタイルURLのバージョンクエリ（regionApi.tsの
# ROAD_SURFACE_TILE_VERSION、ブラウザキャッシュのバスト用）と対で上げること
# （改善計画T19: export_openapi.pyが書き出すgenerated/region-tile-config.jsonと
# regionApi.test.tsの照合テストがドリフトを検知する）。
# v4: 静的道路属性P0（docs/static-road-attributes-plan.md）でsmoothness/tunnel/bridge/
# traffic_stress/bicycle_infraプロパティを追加した世代。
# v3: surface正準分類の拡充（chipseal/bricks=良い、rock/unhewn_cobblestone=悪い、
# 改善計画T7）でsurface_goodの値が変わった世代。
# v2: surface（正規化済み生タグ）・highwayプロパティを追加した世代。
ROAD_SURFACE_TILE_VERSION = "4"

# 停止要因POI・交差点密度タイル（改善計画T54）の世代。ROAD_SURFACE_TILE_VERSIONと同じ理由・
# 同じ運用（フロントのregionApi.ts: POI_TILE_VERSIONと対で上げる）。
# v1: 初版（stop_poi・intersectionの2レイヤー）。
POI_TILE_VERSION = "1"


def _tile_cache_path(z: int, x: int, y: int) -> str:
    return f"region/road-surface/v{ROAD_SURFACE_TILE_VERSION}/{z}/{x}/{y}.pbf"


def _poi_tile_cache_path(z: int, x: int, y: int) -> str:
    return f"region/poi/v{POI_TILE_VERSION}/{z}/{x}/{y}.pbf"


class RegionService:
    """候補ルートに紐づかない「地域全体」のレイヤー（路面、停止要因POI・交差点密度）を、
    標準的なXYZベクタタイルとして提供する。

    標高は国土地理院の色別標高図（ラスタタイル）をフロントエンドから直接重ね描きするため、
    バックエンド側の地域取得はベクタタイルのみを扱う。
    生成したタイル（MVTバイナリ）はz/x/y単位で基礎地図タイルと同じファイルキャッシュ
    （infrastructure/tile_cache.py）に永続化する。「地図データを再読み込み」ボタンで
    基礎地図タイルと一緒にまとめてキャッシュを消去できる。

    データソース（docs/osm-pbf-import.md Phase 2）:
    `repository`（RoadGraphRepository）を渡すと、要求タイルのz12祖先タイルが取得済みマーク
    （road_graph_tiles、PBF取込バッチ or Road Graphのタイル取得が記録）されていれば、
    MVTエンコードまで含めてPostGIS側（ST_AsMVT）でタイルを丸ごと生成する（way行の転送と
    Python側のエンコードCPU処理を避ける。理由はroad_graph_repository.pyの
    _ROAD_SURFACE_TILE_MVT_SQLコメント参照）。カバレッジ外・DB障害時、および`repository`を
    渡さない場合（既定）は空タイルを返す（改善計画T22でOverpassフォールバックを撤去済み。
    詳細はdocs/decisions/pre-static-attributes-gate.md 決定2改定参照）。
    """

    def __init__(self, repository: RoadGraphRepository | None = None):
        self._repository = repository

    async def _tile_from_repository(
        self, repository_method: str, z: int, x: int, y: int, fields: dict, label: str
    ) -> bytes | None:
        """PostGIS側（ST_AsMVT）でタイル1枚分のMVTを丸ごと生成する。カバレッジ外はNone
        （空タイル返却へ）。

        `repository_method`はRoadGraphRepositoryの委譲メソッド名（`get_road_surface_tile_mvt`/
        `get_poi_tile_mvt`）。両者は「カバレッジ外はNone・カバレッジ内0件は空バイト列」という
        同じ契約のため、路面タイル・POI/交差点密度タイル（改善計画T54）で本メソッドを共有する。

        DB障害もNoneを返す（ログ方針: エラーは常時WARNINGで出す。PostGIS停止時も
        地図表示という既存機能全体を落とさず、空タイルで安全側に倒す）。
        """
        try:
            # カバレッジ判定（z12祖先タイルのマーク確認）はMVT生成と同じ1クエリへ
            # 畳み込まれている（遠隔DBの往復1回分を節約。repository側のdocstring参照）。
            ancestor_x, ancestor_y = tile_ancestor(z, x, y, ROAD_GRAPH_TILE_ZOOM)
            tile_bytes = await getattr(self._repository, repository_method)(
                z, x, y, tile_bounds_lonlat(z, x, y), (ROAD_GRAPH_TILE_ZOOM, ancestor_x, ancestor_y)
            )
        except Exception as exc:  # noqa: BLE001 DB障害は空タイル返却で吸収する（上記docstring）
            logger.warning("%sタイルのPostGIS読み取りに失敗 z=%d x=%d y=%d error=%r", label, z, x, y, exc)
            fields["postgis"] = "error"
            fields["postgis_error"] = repr(exc)
            return None
        if tile_bytes is None:
            fields["postgis"] = "uncovered"
            return None
        fields["postgis"] = "hit"
        return tile_bytes

    async def _get_tile(
        self,
        *,
        repository_method: str,
        cache_path: str,
        empty_tile: bytes,
        external_call_name: str,
        label: str,
        z: int,
        x: int,
        y: int,
    ) -> bytes:
        with log_external_call(external_call_name, z=z, x=x, y=y) as fields:
            cached = await asyncio.to_thread(tile_cache.get, cache_path)
            if cached is not None:
                fields["cache"] = "hit"
                content, _content_type = cached
                return content
            fields["cache"] = "miss"

            if self._repository is not None:
                postgis_tile = await self._tile_from_repository(repository_method, z, x, y, fields, label)
                if postgis_tile is not None:
                    fields["source"] = "postgis"
                    fields["tile_bytes"] = len(postgis_tile)
                    await asyncio.to_thread(tile_cache.set, cache_path, postgis_tile, MVT_CONTENT_TYPE)
                    return postgis_tile

            # PostGISのカバレッジ外・DB障害、またはrepository未接続。データ未整備として
            # 空タイルを返す（ログ方針: 常時WARNING。取込漏れ・範囲外アクセスを運用で
            # 気づけるようにする）。後からPBF取込された際に正しいタイルを再生成できるよう、
            # キャッシュには保存しない。DB障害の詳細は_tile_from_repository側で既に
            # WARNING済みのため、ここでは「取込範囲外」表記が誤解を招くerror時は出さない。
            if fields.get("postgis") != "error":
                logger.warning("%sタイルがPostGIS取込範囲外 z=%d x=%d y=%d", label, z, x, y)
            fields["source"] = "uncovered_empty"
            return empty_tile

    async def get_road_surface_tile(self, z: int, x: int, y: int) -> bytes:
        return await self._get_tile(
            repository_method="get_road_surface_tile_mvt",
            cache_path=_tile_cache_path(z, x, y),
            empty_tile=encode_empty_road_surface_tile(),
            external_call_name="region:road-surface-tile",
            label="路面",
            z=z,
            x=x,
            y=y,
        )

    async def get_poi_tile(self, z: int, x: int, y: int) -> bytes:
        """停止要因POI・交差点密度レイヤー（改善計画T54）用のMVTタイルを返す。
        get_road_surface_tileと同じキャッシュ・カバレッジ判定・エラー処理を、対象データが
        違うだけの_get_tileへ共通化して使う（osm_raw_pois/road_nodesが評価にのみ使われ
        地図上で確認できなかった問題への対応）。
        """
        return await self._get_tile(
            repository_method="get_poi_tile_mvt",
            cache_path=_poi_tile_cache_path(z, x, y),
            empty_tile=encode_empty_poi_tile(),
            external_call_name="region:poi-tile",
            label="POI・交差点密度",
            z=z,
            x=x,
            y=y,
        )
