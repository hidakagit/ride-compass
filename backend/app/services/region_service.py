import asyncio
import logging
import time

from app.config import settings
from app.domain.evaluation import AxisInspectorResult, RoutePreference, axis_inspector_breakdown
from app.domain.region import ROAD_GRAPH_TILE_ZOOM, tile_ancestor, tile_bounds_lonlat
from app.infrastructure.database import get_session_factory
from app.infrastructure.debug_log import error_type_label, log_external_call, log_throttled_warning
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.infrastructure.vector_tile import encode_empty_poi_tile, encode_empty_road_surface_tile
from app.services.graph_service import GraphService
from app.services.tile_serving import serve_cached_tile

logger = logging.getLogger("ridecompass.region")

# タイル配信側でもGraphService.get_or_build_graph_with_attributesと同じ構築処理を、
# z12（ROAD_GRAPH_TILE_ZOOM）タイル単位でバックグラウンド起動する（地図を眺めるだけの
# 利用でも道路グラフが構築されるようにするための機構、docs/modules/backend/
# static-road-attributes.md参照）。同期的に待たせるとNext.jsのrewritesプロキシの
# 30秒タイムアウト（docs/architecture.md参照）に触れかねないため、今回のタイル応答は
# これまでどおり即座に返し、構築は非同期に進める（次回以降の同じ地域へのアクセスから
# 反映される）。いずれもプロセス内メモリのみの状態（rate_limiter.pyと同じ割り切り、
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
    次々にDBコネクションだけ先取りして塞ぐ」ことになりかねないため。
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
                graph_service = GraphService(repository=repository)
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

# road_surface・poi両タイルで共通のMVT MIMEタイプ。
MVT_CONTENT_TYPE = "application/vnd.mapbox-vector-tile"

# タイル内容の世代。パスへ世代を含めることで、プロパティ追加前に保存された旧タイルを
# キャッシュヒットさせない（旧世代のファイルは「変わらないデータを更新」のclear_allで
# まとめて消える）。プロパティ削除を伴う世代は、対応するfrontend（regionApi.ts）の
# デプロイより先に本番へ出さないこと（旧フロントの凡例フィルタが全地物に一致し、
# 対象レイヤーが一時的に「不明・他」表示になる）。MVTへ実際に焼き込まれるプロパティは
# `infrastructure/road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQL`が正本。
# frontend側のタイルURLバージョンクエリ（regionApi.tsのROAD_SURFACE_TILE_VERSION、
# ブラウザキャッシュのバスト用）と対で上げる必要があり、export_openapi.pyが書き出す
# generated/region-tile-config.jsonとregionApi.test.tsの照合テストがドリフトを検知する。
ROAD_SURFACE_TILE_VERSION = "17"

# 停止要因POIタイルの世代。ROAD_SURFACE_TILE_VERSIONと同じ理由・同じ運用
# （フロントのregionApi.ts: POI_TILE_VERSIONと対で上げる）。
POI_TILE_VERSION = "3"


def _tile_cache_path(z: int, x: int, y: int) -> str:
    return f"region/road-surface/v{ROAD_SURFACE_TILE_VERSION}/{z}/{x}/{y}.pbf"


def _poi_tile_cache_path(z: int, x: int, y: int) -> str:
    return f"region/poi/v{POI_TILE_VERSION}/{z}/{x}/{y}.pbf"


class RegionService:
    """候補ルートに紐づかない「地域全体」のレイヤー（路面、停止要因POI）を、
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
    渡さない場合（既定）は空タイルを返す（Overpassフォールバックを持たない設計の背景は
    docs/decisions/pre-static-attributes-gate.md 決定2参照）。

    カバレッジ内（生データ取込済み）でも、実際にタイル描画が読むroad_nodes/road_edges
    （道路グラフ）は、地図を眺めるだけ（ルート生成を経ない）の利用では構築されない
    ままになりうる。このタイル配信側でも、カバレッジ内と分かったz12祖先タイルについて
    未構築・古ければバックグラウンドで構築する（`_maybe_trigger_graph_build`。応答自体は
    待たせず即座に返し、次回以降のアクセスから反映される）。
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
        同じ契約のため、路面タイル・POIタイルで本メソッドを共有する。

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
            # パン/ズームのたびに大量のタイルリクエストが飛びうる高頻度な経路のため
            # 抑制ヘルパー経由で出す。
            log_throttled_warning(
                f"region:{label}-error", "%sタイルのPostGIS読み取りに失敗 z=%d x=%d y=%d error=%r", label, z, x, y, exc,
            )
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
        async def fetch_tile(fields: dict) -> bytes | None:
            if self._repository is None:
                # repository未接続。DB障害時のWARNING（_tile_from_repository側で既に
                # 出している）と表記を揃え、ここでは「取込範囲外」表記で常時WARNINGを出す
                # （ログ方針: 取込漏れ・範囲外アクセスを運用で気づけるようにする）。
                # 地図を眺めるだけで未取込エリアへ何度もアクセスされうる高頻度WARNINGの
                # ため、抑制ヘルパー経由にする（他の外部I/O系WARNINGと同じ方針）。
                log_throttled_warning(
                    f"{external_call_name}-uncovered", "[%s] %sタイルがPostGIS取込範囲外 z=%d x=%d y=%d",
                    external_call_name, label, z, x, y,
                )
                return None
            postgis_tile = await self._tile_from_repository(repository_method, z, x, y, fields, label)
            if postgis_tile is None and fields.get("postgis") != "error":
                # PostGISのカバレッジ外。DB障害の詳細は_tile_from_repository側で既に
                # WARNING済みのため、ここでは「取込範囲外」表記が誤解を招くerror時は出さない。
                log_throttled_warning(
                    f"{external_call_name}-uncovered", "[%s] %sタイルがPostGIS取込範囲外 z=%d x=%d y=%d",
                    external_call_name, label, z, x, y,
                )
            return postgis_tile

        # 取得不可の場合、後からPBF取込された際に正しいタイルを再生成できるよう
        # キャッシュには保存しない（serve_cached_tileはfetch_tileがNoneを返したときのみ
        # 空タイルを返し、キャッシュ書き込みを行わない）。
        return await serve_cached_tile(
            z=z,
            x=x,
            y=y,
            cache_path=cache_path,
            empty_tile=empty_tile,
            content_type=MVT_CONTENT_TYPE,
            external_call_name=external_call_name,
            fetch_tile=fetch_tile,
        )

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
        """停止要因POIレイヤー用のMVTタイルを返す。get_road_surface_tileと同じキャッシュ・
        カバレッジ判定・エラー処理を、対象データが違うだけの_get_tileへ共通化して使う。
        """
        return await self._get_tile(
            repository_method="get_poi_tile_mvt",
            cache_path=_poi_tile_cache_path(z, x, y),
            empty_tile=encode_empty_poi_tile(),
            external_call_name="region:poi-tile",
            label="POI",
            z=z,
            x=x,
            y=y,
        )

    async def get_axis_inspector(self, osm_way_id: int) -> AxisInspectorResult | None:
        """区間インスペクタ。クリックされた道路（osm_way_id）について、一次属性→二次軸
        スコア→三次合成コスト（取得可能な軸だけの参考値）を返す（詳細はdocs/modules/backend/
        static-road-attributes.md参照）。

        フィーチャーのプロパティに含まれるosm_way_id（`_ROAD_SURFACE_TILE_MVT_SQL`が
        焼き込み済み）で該当行を曖昧さ無く引き直す（クリック地点の緯度経度からの空間マッチ
        [半径内最近傍]だと、交差点付近など複数の道路が近接する場所で、実際にクリックされた
        フィーチャーとは別の道路を拾いうるため採用しない）。

        `repository`未注入、該当way自体が存在しない場合はNone。DB例外もNoneへ倒す
        （get_road_surface_tile等の`_tile_from_repository`と同じグレースフルデグレード
        方針。ログ・統計も同様に`log_external_call`＋`/api/debug/stats`計上へ揃える）。
        """
        if self._repository is None:
            return None
        with log_external_call("region:axis-inspector", osm_way_id=osm_way_id) as fields:
            try:
                way_tags_result = await self._repository.get_way_tags_by_osm_way_id(osm_way_id)
                if way_tags_result is None:
                    fields["lookup"] = "not_found"
                    return None
                way_counts = await self._repository.get_way_attribute_counts(osm_way_id)
                accident_years_covered = await self._repository.get_accident_years_covered()
            except Exception as exc:  # noqa: BLE001 DB障害は安全側(None)へ倒す（他タイル系と同じ方針）
                fields["result"] = "error"
                fields["warned"] = True
                fields["error_type"] = error_type_label(exc)
                # 区間インスペクタは地図クリックのたびに呼ばれうるため、他のPostGIS読み取り
                # 失敗WARNINGと同じ抑制ヘルパー経由へ揃える。
                log_throttled_warning(
                    "region:axis-inspector", "区間インスペクタのPostGIS読み取りに失敗 osm_way_id=%d error=%r",
                    osm_way_id, exc,
                )
                return None
            fields["lookup"] = "ok"
            fields["way_counts_available"] = way_counts is not None
            highway, tags, is_designated = way_tags_result
            return axis_inspector_breakdown(highway, tags, is_designated, way_counts, accident_years_covered, RoutePreference())

    async def get_accident_years_covered(self) -> int:
        """`GET /api/axis-catalog`が地図表示の実行時スケール定数
        （`material_runtime_scales`）を組み立てるために使う。事故データの収録年数
        （accident_import_runsの成功run、年重複なし）——`domain/axis_display.py:
        derive_ramp_inputs`が自動導出したaccident軸のtile_input（`accident_per_km`の
        生値、年正規化前）を、フロントのJS式が`1/accident_years_covered`倍して
        材料スケール（件/(km・年)）へ変換する。

        `repository`未注入・DB例外はいずれも0へ倒す（get_material_valuesと同じ
        グレースフルデグレード方針）。呼び出し元（axis_catalog.py）は0を「解決不能」
        として扱い、`material_runtime_scales`に該当エントリを含めない（0除算を避ける
        安全側の判断。この場合accident軸のtile_inputはneeds_runtime_scale=Trueのまま
        スケール定数を持たないため、フロント側は寄与0[常に緑]として描画する——事故データ
        自体が0件収録という実運用ではまず起こらない縮退ケースのため、軽微な誤表示として
        許容する）。
        """
        if self._repository is None:
            return 0
        with log_external_call("region:accident-years-covered") as fields:
            try:
                years = await self._repository.get_accident_years_covered()
            except Exception as exc:  # noqa: BLE001 DB障害は安全側(0)へ倒す（他メソッドと同じ方針）
                fields["result"] = "error"
                fields["warned"] = True
                fields["error_type"] = error_type_label(exc)
                log_throttled_warning("region:accident-years-covered", "事故データ収録年数のPostGIS読み取りに失敗 error=%r", exc)
                return 0
            fields["years_covered"] = years
            return years

    async def get_material_values(self, material_id: str) -> list[str]:
        """軸スタジオ（AxisComposer.tsx）の値入力UX向け。指定した材料id
        （highway/surface/smoothness、`infrastructure/road_graph_repository.py:
        _MATERIAL_VALUE_COLUMN_EXPR`参照）についてDBへ実際に取り込まれている値の一覧を
        返す。`repository`未注入・DB例外はいずれも空リストへ倒す（get_axis_inspectorと
        同じグレースフルデグレード方針。空リストは呼び出し元routerが「未知の材料id」と
        区別できるよう、材料idの妥当性自体はrouter側`is_known_material`が事前に検証する
        前提）。
        """
        if self._repository is None:
            return []
        with log_external_call("region:material-values", material_id=material_id) as fields:
            try:
                values = await self._repository.get_distinct_material_values(material_id)
            except Exception as exc:  # noqa: BLE001 DB障害は安全側(空リスト)へ倒す（他メソッドと同じ方針）
                fields["result"] = "error"
                fields["warned"] = True
                fields["error_type"] = error_type_label(exc)
                log_throttled_warning(
                    "region:material-values", "材料値一覧のPostGIS読み取りに失敗 material_id=%s error=%r",
                    material_id, exc,
                )
                return []
            fields["value_count"] = len(values)
            return values
