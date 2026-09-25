import logging

from app.domain.axis_inspector import AxisInspectorResult, axis_inspector_breakdown
from app.domain.route_preference import RoutePreference
from app.domain.region import tile_bounds_lonlat
from app.infrastructure.database import DB_UNAVAILABLE_ERRORS
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

def _tile_cache_path(z: int, x: int, y: int) -> str:
    return f"region/road-surface/v{served_tile_version(ROAD_SURFACE_TILE_SHAPE)}/{z}/{x}/{y}.pbf"


def _poi_tile_cache_path(z: int, x: int, y: int) -> str:
    return f"region/poi/v{served_tile_version(POI_TILE_SHAPE)}/{z}/{x}/{y}.pbf"


class RegionService:
    """候補ルートに紐づかない「地域全体」のレイヤーを、XYZベクタタイルとして配る。

    生成したタイルは基礎地図タイルと同じファイルキャッシュへ置く。そのため管理画面からの
    一括クリア（`api/routers/basemap.py: basemap_refresh`）で両方とも消える。

    カバレッジ外・DB障害・`repository`未注入はいずれも空タイルを返す。取れなかったときに
    別の経路から取り直すフォールバックは持たない（背景は
    docs/records/decisions/pre-static-attributes-gate.md 決定2）。
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
        """PostGIS側（ST_AsMVT）でタイル1枚分のMVTを丸ごと生成する。

        `repository_method`が名指すメソッドは「カバレッジ外はNone・カバレッジ内0件は
        空バイト列」という契約を満たすこと。DB障害もNoneへ倒し、PostGIS停止時も地図表示
        全体を落とさない。
        """
        try:
            # カバレッジ判定（取込の宣言した範囲か）はMVT生成と同じ1クエリへ畳み込まれて
            # いる（遠隔DBの往復1回分を節約。repository側のdocstring参照）。
            tile_bytes = await getattr(self._repository, repository_method)(
                z, x, y, tile_bounds_lonlat(z, x, y)
            )
        except DB_UNAVAILABLE_ERRORS as exc:
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
                log_throttled_warning(
                    f"{external_call_name}-uncovered", "[%s] %sタイルがPostGIS取込範囲外 z=%d x=%d y=%d",
                    external_call_name, label, z, x, y,
                )
                return None
            postgis_tile = await self._tile_from_repository(repository_method, z, x, y, fields, label)
            if postgis_tile is None and fields.get("postgis") != "error":
                # error時に出さないのは、「取込範囲外」という表記がDB障害には当てはまらず、
                # かつその失敗は_tile_from_repository側が既にWARNINGで出しているため。
                log_throttled_warning(
                    f"{external_call_name}-uncovered", "[%s] %sタイルがPostGIS取込範囲外 z=%d x=%d y=%d",
                    external_call_name, label, z, x, y,
                )
            return postgis_tile

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
        preference: RoutePreference | None = None,
    ) -> AxisInspectorResult | None:
        """区間インスペクタ。クリックされた道路について、一次属性→二次軸スコア→三次合成
        コスト（取得可能な軸だけの参考値）を返す。

        引き直しの鍵はタイルへ焼き込み済みのosm_way_idで、クリック地点の緯度経度からの
        空間マッチは使わない——交差点付近など複数の道路が近接する場所で、実際にクリック
        されたフィーチャーとは別の道路を拾う。

        `dynamic_materials`は進行方向に依存する材料（勾配・風）の値。**1本の道は往復2方向で
        値が違う**ため、方向が決まらないと算出できない。地図が指定している走行方位・時刻・
        想定速度から呼び出し側が引いて渡す（渡さなければその軸は「データなし」のまま）。

        `preference`は合成に使う重み。利用者がいま設定している重みを渡す——ルート生成と同じ重みで見せないと、
        重みを0にした軸まで効いて見える。省略すると既定の重み。

        `repository`未注入・該当way不在・DB例外はいずれもNoneへ倒す（タイル配信と同じ
        グレースフルデグレード方針）。
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
                landcover = await self._repository.get_feature_landcover(osm_way_id, edge_id)
            except DB_UNAVAILABLE_ERRORS as exc:
                fields["result"] = "error"
                fields["warned"] = True
                fields["error_type"] = error_type_label(exc)
                log_throttled_warning(
                    "region:axis-inspector", "区間インスペクタのPostGIS読み取りに失敗 osm_way_id=%d error=%r",
                    osm_way_id, exc,
                )
                return None
            fields["lookup"] = "ok"
            highway, tags, _surface = way_tags_result
            combined = {**(materials or {}), **(dynamic_materials or {})}
            return axis_inspector_breakdown(
                highway, tags, combined, landcover, preference or RoutePreference(),
            )

    async def get_accident_years_covered(self) -> int:
        """事故データの収録年数。タイルへ焼き込んだ年正規化前の生値を、フロントが
        `1/この値`倍して件/(km・年)へ直す。

        取得できなければ0へ倒す。呼び出し元は0を「解決不能」として扱い、スケール定数を
        配らない（0除算を避ける）。
        """
        return len(await self.get_accident_years())

    async def get_accident_years(self) -> list[int]:
        """事故データの収録年。地図の説明文へ配る。

        表示側が年を文字列で持つと、取り込み直したときに黙って食い違う。年の正本は
        取込プロファイルの宣言（`source_runs.profile`）だけにする。

        `repository`未注入・DB例外はいずれも空へ倒す。
        """
        if self._repository is None:
            return []
        with log_external_call("region:accident-years-covered") as fields:
            try:
                years = await self._repository.get_accident_years()
            except DB_UNAVAILABLE_ERRORS as exc:
                fields["result"] = "error"
                fields["warned"] = True
                fields["error_type"] = error_type_label(exc)
                log_throttled_warning("region:accident-years-covered", "事故データ収録年のPostGIS読み取りに失敗 error=%r", exc)
                return []
            fields["years_covered"] = len(years)
            return years

    async def get_material_values(self, material_id: str) -> list[str] | None:
        """指定した材料についてDBへ実際に取り込まれている値の一覧。軸スタジオの値入力が使う。

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
            except DB_UNAVAILABLE_ERRORS as exc:
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
