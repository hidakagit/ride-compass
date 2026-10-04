from collections.abc import Awaitable, Callable
from functools import partial

from app.domain.axis_inspector import AxisInspectorResult, axis_inspector_breakdown
from app.domain.route_preference import RoutePreference
from app.domain.region import BoundingBox, tile_bounds_lonlat
from app.infrastructure.cache_identity import is_known_tile_version
from app.infrastructure.database import DB_UNAVAILABLE_ERRORS
from app.infrastructure.debug_log import log_external_call, log_throttled_warning, mark_failed
from app.infrastructure.point_tile_layers import PointTileLayer
from app.infrastructure.road_graph_repository import ROAD_SURFACE_TILE_SHAPE, RoadGraphRepository
from app.infrastructure.vector_tile import ROAD_SURFACE_LAYER_NAME, encode_empty_tile
from app.infrastructure.media_types import MVT_CONTENT_TYPE
from app.services.tile_serving import TileResponse, serve_cached_tile
from app.services.tile_version_service import current_tile_versions, served_tile_version

# z・x・yとその範囲（経度・緯度）から、PostGISが生成したタイル1枚を返す読み出し。
_TileReader = Callable[[int, int, int, BoundingBox], Awaitable[bytes | None]]


class RegionService:
    """候補ルートに紐づかない「地域全体」のレイヤーを、XYZベクタタイルとして配る。

    生成したタイルは基礎地図タイルと同じファイルキャッシュへ置く。そのため管理画面からの
    一括クリア（`api/routers/basemap.py: basemap_refresh`）で両方とも消える。

    カバレッジ外・DB障害はいずれも空タイルを返す。取れなかったときに
    別の経路から取り直すフォールバックは持たない（背景は
    docs/records/decisions/pre-static-attributes-gate.md 決定2）。
    """

    def __init__(self, repository: RoadGraphRepository):
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
        self, read_tile: _TileReader, z: int, x: int, y: int, fields: dict
    ) -> bytes | None:
        """PostGIS側（ST_AsMVT）でタイル1枚分のMVTを丸ごと生成する。

        `read_tile`は「カバレッジ外はNone・カバレッジ内0件は空バイト列」という契約を
        満たすこと。DB障害もNoneへ倒し、PostGIS停止時も地図表示全体を落とさない。
        """
        try:
            # カバレッジ判定（取込の宣言した範囲か）はMVT生成と同じ1クエリへ畳み込まれて
            # いる（DBの往復1回分を節約。repository側のdocstring参照）。
            tile_bytes = await read_tile(z, x, y, tile_bounds_lonlat(z, x, y))
        except DB_UNAVAILABLE_ERRORS as exc:
            mark_failed(fields, exc)
            return None
        if tile_bytes is None:
            fields["postgis"] = "uncovered"
            return None
        fields["postgis"] = "hit"
        return tile_bytes

    async def _get_tile(
        self,
        *,
        read_tile: _TileReader,
        layer: str,
        shape: str,
        empty_tile: bytes,
        external_call_name: str,
        label: str,
        z: int,
        x: int,
        y: int,
    ) -> TileResponse:
        async def fetch_tile(fields: dict) -> bytes | None:
            postgis_tile = await self._tile_from_repository(read_tile, z, x, y, fields)
            if postgis_tile is None and fields.get("result") != "error":
                # 失敗のときに出さないのは、「取込範囲外」という表記がDB障害には当てはまらず、
                # かつその失敗は記録の口が抜けるときにWARNINGで出すため。
                log_throttled_warning(
                    f"{external_call_name}-uncovered", "[%s] %sタイルがPostGIS取込範囲外 z=%d x=%d y=%d",
                    external_call_name, label, z, x, y,
                )
            return postgis_tile

        version = await served_tile_version(self._repository, shape)
        return await serve_cached_tile(
            z=z,
            x=x,
            y=y,
            cache_path=f"region/{layer}/v{version}/{z}/{x}/{y}.pbf",
            empty_tile=empty_tile,
            content_type=MVT_CONTENT_TYPE,
            external_call_name=external_call_name,
            fetch_tile=fetch_tile,
            # 世代を読めていない間はディスクへ残さない（tile_servingのdocstring参照）。
            persist=is_known_tile_version(version),
        )

    async def get_road_surface_tile(self, z: int, x: int, y: int) -> TileResponse:
        return await self._get_tile(
            read_tile=self._repository.get_road_surface_tile_mvt,
            layer="road-surface",
            shape=ROAD_SURFACE_TILE_SHAPE,
            empty_tile=encode_empty_tile(ROAD_SURFACE_LAYER_NAME),
            external_call_name="region:road-surface-tile",
            label="路面",
            z=z,
            x=x,
            y=y,
        )

    async def get_point_tile(self, layer: PointTileLayer, z: int, x: int, y: int) -> TileResponse:
        """点のレイヤー（`infrastructure/point_tile_layers.py`）のタイル。どのレイヤーも同じ道で配る。"""
        return await self._get_tile(
            read_tile=partial(self._repository.get_tile_mvt, layer.sql, layer.source_layer),
            layer=layer.name,
            shape=layer.shape,
            empty_tile=encode_empty_tile(layer.source_layer),
            external_call_name=f"region:{layer.name}-tile",
            label=layer.name,
            z=z,
            x=x,
            y=y,
        )

    async def get_axis_inspector(
        self,
        osm_way_id: int,
        edge_id: str | None,
        dynamic_materials: dict[str, float] | None,
        preference: RoutePreference | None,
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

        該当way不在・DB例外はいずれもNoneへ倒す（タイル配信と同じ
        グレースフルデグレード方針）。
        """
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
                mark_failed(fields, exc)
                return None
            fields["lookup"] = "ok"
            highway, tags, _surface = way_tags_result
            combined = {**(materials or {}), **(dynamic_materials or {})}
            return axis_inspector_breakdown(
                highway, tags, combined, landcover, preference or RoutePreference(),
            )

    async def get_accident_years(self) -> list[int]:
        """事故データの収録年。地図の説明文へ配る。

        表示側が年を文字列で持つと、取り込み直したときに黙って食い違う。年の正本は
        今の事故の数を数えた取込の宣言（`source_runs.profile`）だけにする。

        DB例外は空へ倒す。
        """
        with log_external_call("region:accident-years-covered") as fields:
            try:
                years = await self._repository.get_accident_years()
            except DB_UNAVAILABLE_ERRORS as exc:
                mark_failed(fields, exc)
                return []
            fields["years_covered"] = len(years)
            return years

    async def get_ingested_area(self) -> BoundingBox | None:
        """サービスの対象範囲（取り込んだ道路の範囲）。風の格子と気象庁タイルのプリウォームが、ここから
        範囲を引く——範囲を持つのは取込の宣言だけで、取込範囲を広げれば風とタイルも同じ範囲へ広がる。

        道路をまだ取り込んでいない・DB例外のときはNone（どちらもWARNING）。
        """
        with log_external_call("region:ingested-area") as fields:
            try:
                area = await self._repository.get_ingested_area()
            except DB_UNAVAILABLE_ERRORS as exc:
                mark_failed(fields, exc)
                return None
            fields["ingested"] = area is not None
            if area is None:
                log_throttled_warning("region:ingested-area", "道路の取込が成功した記録が無く、対象範囲が決まらない")
            return area
