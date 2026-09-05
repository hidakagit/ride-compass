"""way_id→動的値配信層（風、「評価軸」グループ）。

「評価軸」グループとしての風（ルート未確定時、視界内の全道路へユーザー指定の[時刻,向き]を
一律適用する線表示）の基盤。「環境」グループの風（時刻＋方位スライダー＋`gridFill`面表示、
windLayer.ts/dynamicWeather.ts）とは別経路だが、**同じ[時刻,向き]のユーザー入力を共有する**。

走行方位（travel_bearing_deg）は**ユーザーがコンパススライダーで指定した単一の値**
（全道路共通）を使う——道路自身のOSM格納方向は使わない。この結果、同じタイル内の全wayは
常に同じ`wind_drag_ratio`値を持つ（風グリッドもタイル中心1点で代表させる既存の近似の
ため）。対象タイルに存在するway_idの一覧（`get_way_ids_in_tile`）だけを取得すればよく、
計算結果のキャッシュもway_idごとではなくタイル単位のスカラー値1個で足りる（way_id一覧
全件へ同値をbroadcastしたdictとして`dynamic_way_value_cache.py`へ渡す）。

制御フローの詳細はdocs/modules/backend/dynamic-way-values.md「`WindWayService`」節参照。
"""

import logging
from datetime import datetime

from app.domain.region import ROAD_GRAPH_TILE_ZOOM, BoundingBox, tile_ancestor, tile_bounds_lonlat
from app.domain.route import Coordinates
from app.domain.wind import kmh_to_ms, wind_drag_ratio
from app.domain.wind_grid import nearest_grid_point
from app.infrastructure.debug_log import log_external_call
from app.infrastructure.dynamic_way_value_cache import get_tile_values, set_tile_values
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.infrastructure.weather_client import WIND_GRID_CACHE_TTL_SECONDS
from app.services.route_generator import JST
from app.services.weather_service import WeatherService

logger = logging.getLogger("ridecompass.wind_way")

# このサービスが担当する軸id（`api/dependencies.py: _DYNAMIC_WAY_VALUE_SERVICE_FACTORIES`の
# キーと同じ）。
AXIS_ID = "wind"

# 道路タイル単位の風評価に使う格子間隔（度）。Open-Meteoのキャッシュキー（weather_client.py:
# WeatherClient.cache_key、CACHE_PRECISION=2）は緯度経度を小数2桁（≒0.01度）に丸めるため、
# これより細かい間隔（domain/wind_grid.py: WIND_GRID_DETAIL_ALLOWED_SPACINGS_DEGの
# 0.005/0.0025）を選んでも同じキャッシュ値を返すだけで解像度は上がらない。
# WIND_GRID_SPACING_DEG（既定0.1度、道路タイル数枚〜十数枚が同じ格子点へ丸められる粗さ）より
# 10倍細かくする。
WIND_WAY_GRID_SPACING_DEG = 0.01


def _hour_bucket(at: datetime) -> str:
    """時刻を1時間バケットへ丸める（dynamic_way_value_cache.pyのキー参照）。"""
    return at.strftime("%Y-%m-%dT%H")


def _tile_center(bbox: BoundingBox) -> Coordinates:
    return Coordinates(
        latitude=(bbox.min_latitude + bbox.max_latitude) / 2,
        longitude=(bbox.min_longitude + bbox.max_longitude) / 2,
    )


def _nearest_time_index(times: list[str], target: datetime) -> int | None:
    """風グリッドのhourly時刻配列（Open-MeteoがJST基準の壁時計時刻をtzなし文字列で返す）から、
    targetに最も近いindexを求める（weather_service.py:
    WeatherService._nearest_hourly_index/_within_hourly_rangeと同じ「最近傍だが範囲外は不可」
    という考え方を踏襲した簡易版）。targetがtz-awareならJSTへ変換してから比較する
    （tzinfoを剥がすだけだとJSTとの時差ぶんズレる）。範囲外（風グリッドがまだ届いていない
    遠い未来・過去）はNoneを返し、呼び出し元は「不明」として扱う。"""
    if not times:
        return None
    if target.tzinfo is not None:
        target = target.astimezone(JST)
    target_naive = target.replace(tzinfo=None)
    parsed = [datetime.fromisoformat(t) for t in times]
    if target_naive < min(parsed) or target_naive > max(parsed):
        return None
    diffs = [abs((t - target_naive).total_seconds()) for t in parsed]
    return diffs.index(min(diffs))


class WindWayService:
    def __init__(self, repository: RoadGraphRepository | None, weather_service: WeatherService):
        self._repository = repository
        self._weather_service = weather_service

    material_id = "wind_drag_ratio"

    async def get_way_values(
        self, z: int, x: int, y: int, at: datetime | None, bearing_deg: float | None, speed_kmh: float | None = None
    ) -> dict[int, float]:
        """指定タイル内のway_idごとの風の材料値（`material_id`）を返す（同じタイル内の
        全wayは同じ値を持つ——モジュールdocstring参照）。`speed_kmh`（想定速度）は
        必須。repository未接続・取込範囲外・風データ取得不能等はいずれも空dictへ倒す
        （地図表示という既存機能全体を落とさず、
        「この道路には色が付かない」という安全側の劣化で済ませる、他タイル系メソッドと
        同じグレースフルデグレード方針）。

        bearing_degはユーザーがコンパススライダーで指定した走行方位（0〜360度、北=0・
        時計回り）。全道路共通の値として使う。型は`at`と揃え`float | None`にしている
        （router側`api/routers/region.py`の材料非依存な呼び出しインターフェースと
        一致させるため）が、風は常にbearing_degを必須とする材料
        （`domain/dynamic_way_values.py: dynamic_way_value_materials()["wind"].needs_bearing`
        =True）のため、Noneのまま到達したら即座に失敗させる（router側の422検証を
        すり抜けて呼ばれた場合の防御、無音でNoneを計算に渡さない）。
        """
        if bearing_deg is None:
            raise ValueError("WindWayService.get_way_valuesにはbearing_degが必須です")
        if speed_kmh is None:
            raise ValueError("WindWayService.get_way_valuesにはspeed_kmhが必須です")
        material_id = self.material_id
        if self._repository is None:
            return {}
        target = at or datetime.now(JST)
        bbox = tile_bounds_lonlat(z, x, y)
        ancestor_x, ancestor_y = tile_ancestor(z, x, y, ROAD_GRAPH_TILE_ZOOM)

        with log_external_call("region:wind-way-penalty", z=z, x=x, y=y) as fields:
            try:
                way_ids = await self._repository.get_way_ids_in_tile(
                    z, x, y, bbox, (ROAD_GRAPH_TILE_ZOOM, ancestor_x, ancestor_y)
                )
            except Exception as exc:  # noqa: BLE001 DB障害は空dictへ倒す（他タイル系と同じ方針）
                fields["result"] = "error"
                fields["warned"] = True
                logger.warning("風の評価軸配信のway_id取得に失敗 z=%d x=%d y=%d error=%r", z, x, y, exc)
                return {}
            if not way_ids:
                fields["postgis"] = "uncovered" if way_ids is None else "empty"
                return {}
            fields["way_count"] = len(way_ids)

            hour_bucket = _hour_bucket(target)
            cached = await get_tile_values(material_id, z, x, y, hour_bucket, bearing_deg, speed_kmh)
            if cached is not None:
                fields["cache_hit"] = len(way_ids)
                fields["cache_status"] = "hit"
                penalty = next(iter(cached.values()), 0.0)
            else:
                fields["cache_status"] = "miss"

                grid_point = nearest_grid_point(_tile_center(bbox), spacing_deg=WIND_WAY_GRID_SPACING_DEG)
                times, points = await self._weather_service.get_wind_grid([grid_point])
                wind_grid_point = points[0] if points else None
                if wind_grid_point is None:
                    fields["wind_grid"] = "unavailable"
                    logger.warning("風の評価軸配信の風グリッド取得に失敗 z=%d x=%d y=%d", z, x, y)
                    return {}
                index = _nearest_time_index(times, target)
                if index is None:
                    fields["wind_grid"] = "out_of_range"
                    logger.warning("風の評価軸配信の時刻が風グリッド範囲外 z=%d x=%d y=%d", z, x, y)
                    return {}

                wind_speed = wind_grid_point.wind_speed_ms[index]
                wind_direction = wind_grid_point.wind_direction_deg[index]
                penalty = round(wind_drag_ratio(wind_speed, wind_direction, bearing_deg, kmh_to_ms(speed_kmh)), 3)
                values = dict.fromkeys(way_ids, penalty)
                await set_tile_values(
                    material_id, z, x, y, hour_bucket, bearing_deg, values, WIND_GRID_CACHE_TTL_SECONDS, speed_kmh
                )
                fields["computed"] = len(way_ids)

            # 同じタイル内の全wayが同じ値を持つため、キャッシュhit/missいずれの経路も
            # ここで1回だけbroadcastする。
            return dict.fromkeys(way_ids, penalty)
