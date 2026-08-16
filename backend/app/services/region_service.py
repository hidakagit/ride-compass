import asyncio
import logging
import time

import httpx

from app.config import settings
from app.domain.region import ROAD_GRAPH_TILE_ZOOM, tile_ancestor, tile_bounds_lonlat
from app.domain.traffic import TrafficStressBreakdown, traffic_stress_breakdown
from app.infrastructure import tile_cache
from app.infrastructure.database import get_session_factory
from app.infrastructure.debug_log import log_external_call
from app.infrastructure.overpass_client import OverpassClient
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.infrastructure.vector_tile import encode_empty_poi_tile, encode_empty_road_surface_tile
from app.services.graph_service import GraphService

logger = logging.getLogger("ridecompass.region")

# 地図タイル閲覧（ルート生成を経ない）だけでは、road_nodes/road_edges（タイル配信が実際に
# 読む導出済み道路グラフ）が永遠に構築されない問題への対応（ユーザー指摘: ルート生成と
# 地図閲覧は別々の用途で使われうるため、構築トリガーがルート生成だけに紐づいているのはおかしい）。
# タイル配信側でもGraphService.get_or_build_graph_with_attributesと同じ構築処理を、
# z12（ROAD_GRAPH_TILE_ZOOM）タイル単位でバックグラウンド起動する。同期的に待たせると
# Next.jsのrewritesプロキシの30秒タイムアウト（docs/architecture.md参照）に触れかねないため、
# 今回のタイル応答はこれまでどおり即座に返し、構築は非同期に進める（次回以降の同じ地域への
# アクセスから反映される）。いずれもプロセス内メモリのみの状態（rate_limiter.pyと同じ割り切り、
# 再起動で消えても実害は次回アクセス時に再判定されるだけ）。
_building_graph_tiles: set[tuple[int, int, int]] = set()
# 直前に構築済み/最新確認済みのz12タイルを一定時間だけ再チェック対象から外す。無いと、
# 既に最新のタイルでも地図を眺めるたびに（表示中の全z13-15タイル×ANCESTOR分）
# is_split_up_to_date確認用の短命DBセッションを開き続けてしまう。
_last_build_check: dict[tuple[int, int, int], float] = {}
_GRAPH_CHECK_TTL_SECONDS = 300.0
# 実際の構築（closure再計算・Edge全量再UPSERT）だけを絞る同時実行数上限（config.py:
# graph_build_max_concurrentのコメント参照）。安価なis_split_up_to_date確認はここに
# 含めない（このsemaphoreの後ろで待たされる必要が無い軽いクエリのため）。
_graph_build_semaphore = asyncio.Semaphore(settings.graph_build_max_concurrent)


async def _build_graph_for_tile_background(ancestor_tile: tuple[int, int, int], checked_at: float) -> None:
    """指定z12タイルの道路グラフが未構築・古ければ、GraphServiceの通常経路
    （is_split_up_to_date→必要なら再構築）でバックグラウンド構築する。リクエストの
    セッションとは別の新規セッションを使う（HTTPレスポンスが返った後もタスクを続けるため）。

    鮮度確認（軽い）と実構築（重い、DBセッションを長時間保持）を別セッションに分け、
    実構築だけを`_graph_build_semaphore`で絞る。1つのセッションを保持したまま
    semaphore待ちにすると、密集した未構築エリアへの一斉アクセスで「順番待ちのタスクが
    次々にDBコネクションだけ先取りして塞ぐ」ことになりかねないため（改善計画T59の
    最初の実装で、無制限の同時構築がDBコネクションプールを枯渇させ無関係な他タイル・
    API呼び出しまで502化した実障害を踏まえた対応）。
    """
    zoom, x, y = ancestor_tile
    bbox = tile_bounds_lonlat(zoom, x, y)
    try:
        async with get_session_factory()() as session:
            if await RoadGraphRepository(session).is_split_up_to_date(bbox):
                return

        async with _graph_build_semaphore:
            started = time.monotonic()
            async with get_session_factory()() as session:
                repository = RoadGraphRepository(session)
                async with httpx.AsyncClient() as http_client:
                    graph_service = GraphService(OverpassClient(), http_client, repository=repository)
                    built = await graph_service.get_or_build_graph_with_attributes(bbox)
            elapsed_ms = round((time.monotonic() - started) * 1000)
            edge_count = len(built[0].edges) if built else 0
            logger.info(
                "地図閲覧起点の道路グラフ構築完了 z=%d x=%d y=%d edges=%d elapsed_ms=%d",
                zoom, x, y, edge_count, elapsed_ms,
            )
    except Exception as exc:  # noqa: BLE001 バックグラウンド構築の失敗はタイル応答に影響させない
        logger.warning("地図閲覧起点の道路グラフ構築に失敗 z=%d x=%d y=%d error=%r", zoom, x, y, exc)
    finally:
        _building_graph_tiles.discard(ancestor_tile)
        _last_build_check[ancestor_tile] = checked_at


def _maybe_trigger_graph_build(ancestor_tile: tuple[int, int, int]) -> None:
    if ancestor_tile in _building_graph_tiles:
        return
    now = time.monotonic()
    last_checked = _last_build_check.get(ancestor_tile)
    if last_checked is not None and now - last_checked < _GRAPH_CHECK_TTL_SECONDS:
        return
    _building_graph_tiles.add(ancestor_tile)
    asyncio.create_task(_build_graph_for_tile_background(ancestor_tile, now))

# road_surface・poi両タイルで共通のMVT MIMEタイプ（改善計画T54でroad限定の名前から一般化）。
MVT_CONTENT_TYPE = "application/vnd.mapbox-vector-tile"

# タイル内容の世代。パスへ世代を含めることで、プロパティ追加前に保存された旧タイルを
# キャッシュヒットさせない（旧世代のファイルは「変わらないデータを更新」のclear_allで
# まとめて消える）。フロントエンドのタイルURLのバージョンクエリ（regionApi.tsの
# ROAD_SURFACE_TILE_VERSION、ブラウザキャッシュのバスト用）と対で上げること
# （改善計画T19: export_openapi.pyが書き出すgenerated/region-tile-config.jsonと
# regionApi.test.tsの照合テストがドリフトを検知する）。
# v6: 改善計画T74。designation_attributesをosm_way_id基準（road_edges遅延構築非依存）へ
# 変更し、designationプロパティが同一way内でN10・N12の両方に該当する場合の3値目"both"を
# 追加した世代。
# v5: 指定路線コンフレーション機構（外部静的データソース T51）でdesignationプロパティを
# 追加し、traffic_stressへKSJ N10/N12該当の+1補正を組み込んだ世代。
# v4: 静的道路属性P0（docs/static-road-attributes-plan.md）でsmoothness/tunnel/bridge/
# traffic_stress/bicycle_infraプロパティを追加した世代。
# v3: surface正準分類の拡充（chipseal/bricks=良い、rock/unhewn_cobblestone=悪い、
# 改善計画T7）でsurface_goodの値が変わった世代。
# v2: surface（正規化済み生タグ）・highwayプロパティを追加した世代。
ROAD_SURFACE_TILE_VERSION = "6"

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

    カバレッジ内（生データ取込済み）でも、実際にタイル描画が読むroad_nodes/road_edges
    （道路グラフ）は、以前はルート生成（GraphService経由）でしか構築されなかった（改善計画T59:
    ルート生成と地図閲覧は別々の用途で使われうるため不十分だった。ユーザー指摘を受けて対応）。
    このタイル配信側でも、カバレッジ内と分かったz12祖先タイルについて未構築・古ければ
    バックグラウンドで構築する（`_maybe_trigger_graph_build`。応答自体は待たせず即座に返し、
    次回以降のアクセスから反映される）。
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
        # カバレッジ内（生データ取込済み）と分かったので、このz12祖先タイルの道路グラフが
        # 未構築・古ければバックグラウンドで構築する（road-surface/poi両タイルで共通、
        # 上のモジュールdocstring参照）。応答自体はこれまでどおり待たせず即座に返す。
        # isinstanceで実リポジトリのときだけ発火させる: テストのFakeRegionRepositoryは
        # このクラスを継承しないダックタイピングのため、ここで弾かれ実DBセッションを
        # 開こうとしない（settings.road_graph_use_repositoryだけに頼ると、この開発機の
        # .envのように既定でtrueな環境ではユニットテストでも実DBへ触れてしまう）。
        if isinstance(self._repository, RoadGraphRepository):
            _maybe_trigger_graph_build((ROAD_GRAPH_TILE_ZOOM, ancestor_x, ancestor_y))
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

    async def get_traffic_stress_breakdown(self, latitude: float, longitude: float) -> TrafficStressBreakdown | None:
        """クリック地点近傍の道路の交通ストレス判定内訳を返す（改善計画T90）。

        `repository`未注入（DBなし構成）はNone。近傍（`get_nearest_way_tags`の既定
        半径=道路評価と同じSURFACE_MATCH_MAX_DISTANCE_M）に対象道路が無い、または
        highwayが判定基準に登録されていない場合はTrafficStressBreakdown(base=None,
        level=None, ...)（タイル・区間評価と同じ「不明・他」の扱い）。
        """
        if self._repository is None:
            return None
        highway, tags, is_designated = (await self._repository.get_nearest_way_tags([(latitude, longitude)]))[0]
        return traffic_stress_breakdown(highway, tags, is_designated)
