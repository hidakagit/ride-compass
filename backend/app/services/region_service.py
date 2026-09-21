import logging

from app.domain.axis_inspector import AxisInspectorResult, axis_inspector_breakdown
from app.domain.route_preference import RoutePreference
from app.domain.region import tile_bounds_lonlat
from app.infrastructure.debug_log import error_type_label, log_external_call, log_throttled_warning
from app.infrastructure.road_graph_repository import (
    POI_TILE_SHAPE,
    ROAD_SURFACE_TILE_SHAPE,
    RoadGraphRepository,
)
from app.infrastructure.vector_tile import encode_empty_poi_tile, encode_empty_road_surface_tile
from app.services import derived_data_revision_service
from app.services.tile_serving import MVT_CONTENT_TYPE, TileResponse, serve_cached_tile
from app.services.tile_version_service import current_tile_versions, served_tile_version

logger = logging.getLogger("ridecompass.region")

# タイル内容の世代は焼き込むSQLの隣（road_graph_repository.py）で導出する。ここは
# キャッシュパスの組み立てだけを持ち、export_openapi.pyはこのモジュール経由で受け取る
# （generated/region-tile-config.json、regionApi.test.tsの照合テストがドリフトを検知する）。


def _tile_cache_path(z: int, x: int, y: int) -> str:
    return f"region/road-surface/v{served_tile_version(ROAD_SURFACE_TILE_SHAPE)}/{z}/{x}/{y}.pbf"


def _poi_tile_cache_path(z: int, x: int, y: int) -> str:
    return f"region/poi/v{served_tile_version(POI_TILE_SHAPE)}/{z}/{x}/{y}.pbf"


class RegionService:
    """候補ルートに紐づかない「地域全体」のレイヤー（路面、停止要因POI）を、
    標準的なXYZベクタタイルとして提供する。

    標高は国土地理院の色別標高図（ラスタタイル）をフロントエンドから直接重ね描きするため、
    バックエンド側の地域取得はベクタタイルのみを扱う。
    生成したタイル（MVTバイナリ）はz/x/y単位で基礎地図タイルと同じファイルキャッシュ
    （infrastructure/tile_cache.py）に永続化する。基礎地図タイルと同じキャッシュのため、
    管理画面からの一括クリア（`api/routers/basemap.py: basemap_refresh`）で両方とも消える。

    データソース（docs/osm-pbf-import.md Phase 2）:
    `repository`（RoadGraphRepository）を渡すと、要求タイルのz12祖先タイルが取得済みマーク
    （road_graph_tiles、PBF取込バッチ or Road Graphのタイル取得が記録）されていれば、
    MVTエンコードまで含めてPostGIS側（ST_AsMVT）でタイルを丸ごと生成する（way行の転送と
    Python側のエンコードCPU処理を避ける。理由はroad_graph_repository.pyの
    _ROAD_SURFACE_TILE_MVT_SQLコメント参照）。カバレッジ外・DB障害時、および`repository`を
    渡さない場合（既定）は空タイルを返す（Overpassフォールバックを持たない設計の背景は
    docs/records/decisions/pre-static-attributes-gate.md 決定2参照）。

    カバレッジ内（生データ取込済み）でも、実際にタイル描画が読むroad_nodes/road_edges
    （道路グラフ）は、地図を眺めるだけ（ルート生成を経ない）の利用では構築されない
    ままになりうる。このタイル配信側でも、カバレッジ内と分かったz12祖先タイルについて
    未構築・古ければバックグラウンドで構築する（応答自体は
    待たせず即座に返し、次回以降のアクセスから反映される）。
    """

    def __init__(self, repository: RoadGraphRepository | None = None):
        self._repository = repository

    async def tile_versions(self) -> dict[str, str]:
        """系統名→配信する世代（`services/tile_version_service.py`）。

        DBの口（`repository`）を外へ出さずにここで閉じる。**外へ出すと、呼び出し側が
        どのセッション設定（タイムアウト）の上で動いているのかが見えないまま
        infrastructureを直接触ることになる**——このサービスを作る依存
        （`api/dependencies.py: get_region_service`）と、repositoryを直接配る依存とでは
        タイムアウトが違う。
        """
        return await current_tile_versions(self._repository)

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
            # カバレッジ判定（取込の宣言した範囲か）はMVT生成と同じ1クエリへ畳み込まれて
            # いる（遠隔DBの往復1回分を節約。repository側のdocstring参照）。
            tile_bytes = await getattr(self._repository, repository_method)(
                z, x, y, tile_bounds_lonlat(z, x, y)
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
    ) -> TileResponse:
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
            # 世代を読めていない間はディスクへ残さない（tile_servingのdocstring参照）。
            persist=derived_data_revision_service.current_revision() is not None,
        )

    async def get_road_surface_tile(self, z: int, x: int, y: int) -> TileResponse:
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

    async def get_poi_tile(self, z: int, x: int, y: int) -> TileResponse:
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

    async def get_axis_inspector(
        self,
        osm_way_id: int,
        edge_id: str | None = None,
        dynamic_materials: dict[str, float] | None = None,
    ) -> AxisInspectorResult | None:
        """区間インスペクタ。クリックされた道路（osm_way_id）について、一次属性→二次軸
        スコア→三次合成コスト（取得可能な軸だけの参考値）を返す（詳細はdocs/modules/backend/
        static-road-attributes.md参照）。

        フィーチャーのプロパティに含まれるosm_way_id（`_ROAD_SURFACE_TILE_MVT_SQL`が
        焼き込み済み）で該当行を曖昧さ無く引き直す（クリック地点の緯度経度からの空間マッチ
        [半径内最近傍]だと、交差点付近など複数の道路が近接する場所で、実際にクリックされた
        フィーチャーとは別の道路を拾いうるため採用しない）。

        `dynamic_materials`は進行方向に依存する材料（勾配・風）の値。**1本の道は往復2方向で
        値が違う**ため、方向が決まらないと算出できない。地図が指定している走行方位・時刻・
        想定速度から呼び出し側が引いて渡す（渡さなければその軸は「データなし」のまま）。

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
                accident_years_covered = await self._repository.get_accident_years_covered()
                materials = await self._repository.get_way_material_values(
                    osm_way_id, accident_years_covered
                )
                # 地図が塗っている値と同じ単位で読む（区間が特定できるときは区間単位）。
                way_landcover = await self._repository.get_feature_landcover(osm_way_id, edge_id)
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
            highway, tags, _surface = way_tags_result
            combined = {**(materials or {}), **(dynamic_materials or {})}
            return axis_inspector_breakdown(
                highway, tags, combined, way_landcover, RoutePreference(),
            )

    async def get_accident_years_covered(self) -> int:
        """`GET /api/axis-catalog`が地図表示の実行時スケール定数
        （`material_runtime_scales`）を組み立てるために使う。事故データの収録年数
        （accident_import_runsの成功run、年重複なし）——地図表示が導いた事故軸のタイル入力
        （年正規化前の生値）を、フロントのJS式が`1/accident_years_covered`倍して
        材料スケール（件/(km・年)）へ変換する。

        `repository`未注入・DB例外はいずれも0へ倒す（get_material_valuesと同じ
        グレースフルデグレード方針）。呼び出し元（axis_catalog.py）は0を「解決不能」
        として扱い、`material_runtime_scales`に該当エントリを含めない（0除算を避ける
        安全側の判断。この場合accident軸のtile_inputはneeds_runtime_scale=Trueのまま
        スケール定数を持たないため、フロント側は寄与0[常に緑]として描画する——事故データ
        自体が0件収録という実運用ではまず起こらない縮退ケースのため、軽微な誤表示として
        許容する）。
        """
        return len(await self.get_accident_years())

    async def get_accident_years(self) -> list[int]:
        """事故データの収録年。`GET /api/axis-catalog`が地図の説明文へ配る。

        表示側が年を文字列で持つと、取り込み直したときに黙って食い違う。年の正本は
        取込プロファイルの宣言（`source_runs.profile`）だけにする。

        `repository`未注入・DB例外はいずれも空へ倒す（`get_material_values`と同じ
        グレースフルデグレード方針）。
        """
        if self._repository is None:
            return []
        with log_external_call("region:accident-years-covered") as fields:
            try:
                years = await self._repository.get_accident_years()
            except Exception as exc:  # noqa: BLE001 DB障害は安全側(空)へ倒す（他メソッドと同じ方針）
                fields["result"] = "error"
                fields["warned"] = True
                fields["error_type"] = error_type_label(exc)
                log_throttled_warning("region:accident-years-covered", "事故データ収録年のPostGIS読み取りに失敗 error=%r", exc)
                return []
            fields["years_covered"] = len(years)
            return years

    async def get_material_values(self, material_id: str) -> list[str] | None:
        """軸スタジオ（AxisComposer.tsx）の値入力UX向け。指定した材料id
        （`MaterialSpec.value_sql`を持つcategorical材料）についてDBへ実際に取り込まれて
        いる値の一覧を返す。

        **取得できなかったとき（`repository`未注入・DB例外・タイムアウト）はNone**、
        取得できて値が無いときは空リストを返す。両方を空リストへ倒すと、画面は
        「候補が無い」と「候補を出せなかった」を区別できず、DBのタイムアウトが
        「この材料には値が無い」として静かに表示される
        （`get_axis_inspector`と同じグレースフルデグレード方針だが、**結果の区別は残す**）。
        """
        if self._repository is None:
            return None
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
                return None
            fields["value_count"] = len(values)
            return values
