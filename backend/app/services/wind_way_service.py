"""鍵→動的値配信層（風）。

走行方位は**ユーザーが指定した単一の値**（全道路共通）で、道路自身のOSM格納方向は使わない
（ルートを出す前は道を走る向きが決まっていない）。予報の地点と時刻の選び方はルートの区間と
同じ（`domain/wind.py`の`WindLattice`・`WindForecastSeries`）で、値は同じ評価器
（`domain/dynamic_materials.py`）を通す。

制御フローの詳細はdocs/modules/backend/dynamic-way-values.md「`WindWayService`」節参照。
"""

import logging
from datetime import datetime

import numpy as np

from app.domain.dynamic_materials import DynamicAxisRequestContext, evaluate_dynamic_material_arrays
from app.domain.time_zone import JST
from app.domain.material_catalog import WIND_DRAG_RATIO
from app.domain.region import BoundingBox, tile_bounds_lonlat
from app.domain.wind import kmh_to_ms
from app.infrastructure.database import DB_UNAVAILABLE_ERRORS
from app.infrastructure.debug_log import log_external_call
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.weather_service import WeatherService

logger = logging.getLogger("ridecompass.wind_way")


class WindWayService:
    def __init__(self, repository: RoadGraphRepository, weather_service: WeatherService):
        self._repository = repository
        self._weather_service = weather_service

    #: 返す生値の材料id。この材料を参照する軸の配信を担当する。
    material_id = WIND_DRAG_RATIO
    material_ids = (WIND_DRAG_RATIO,)

    @classmethod
    def build(cls, repository: RoadGraphRepository, weather_service: WeatherService, material_id: str) -> "WindWayService":
        """登録テーブルから呼ぶための統一シグネチャ。依存の要否はサービスごとに違い、風の材料は1つだけ。"""
        return cls(repository=repository, weather_service=weather_service)

    async def get_way_values(
        self, z: int, x: int, y: int, at: datetime | None, bearing_deg: float | None, speed_kmh: float | None = None
    ) -> dict[str, float]:
        """指定タイル内のフィーチャーごとの風の材料値を返す。

        取込範囲外・風データ取得不能・予報の範囲の外の時刻はいずれも空dictへ倒し、「この道路に
        色が付かない」という劣化で済ませる。

        `bearing_deg`・`speed_kmh`は材料非依存な呼び出し口と形を揃えるため省略可能な形に
        なっているが、風はどちらも無いと計算できない。Noneのまま到達したら即座に失敗させる
        （router側の検証をすり抜けた場合の防御。無音でNoneを計算へ渡さない）。
        """
        if bearing_deg is None:
            raise ValueError("WindWayService.get_way_valuesにはbearing_degが必須です")
        if speed_kmh is None:
            raise ValueError("WindWayService.get_way_valuesにはspeed_kmhが必須です")
        # 予報の時刻はJSTのローカル時刻。tz付きの時刻はtzinfoを剥がすだけだと時差ぶんずれる。
        target = at or datetime.now(JST)
        if target.tzinfo is not None:
            target = target.astimezone(JST).replace(tzinfo=None)
        bbox = tile_bounds_lonlat(z, x, y)

        with log_external_call("region:wind-way-penalty", z=z, x=x, y=y) as fields:
            try:
                midpoints = await self._repository.get_feature_midpoints_in_tile(z, x, y, bbox)
            except DB_UNAVAILABLE_ERRORS as exc:
                fields["result"] = "error"
                fields["warned"] = True
                logger.warning("風の評価軸配信の鍵取得に失敗 z=%d x=%d y=%d error=%r", z, x, y, exc)
                return {}
            if not midpoints:
                fields["postgis"] = "uncovered" if midpoints is None else "empty"
                return {}
            fields["feature_count"] = len(midpoints)

            keys = list(midpoints)
            latitudes = np.array([midpoints[key][0] for key in keys], dtype=float)
            longitudes = np.array([midpoints[key][1] for key in keys], dtype=float)
            # タイルをまたぐ道の中ほどはタイルの外にありうるため、格子はタイルと中ほどの両方を覆う。
            series = await self._weather_service.get_wind_forecast_lattice(BoundingBox(
                min_latitude=min(bbox.min_latitude, float(latitudes.min())),
                min_longitude=min(bbox.min_longitude, float(longitudes.min())),
                max_latitude=max(bbox.max_latitude, float(latitudes.max())),
                max_longitude=max(bbox.max_longitude, float(longitudes.max())),
            ))
            if series is None:
                fields["wind_grid"] = "unavailable"
                logger.warning("風の評価軸配信の風グリッド取得に失敗 z=%d x=%d y=%d", z, x, y)
                return {}
            passage_hours = np.zeros(len(keys))
            # ルートの区間は予報の先を端の値で延ばすが、地図では延ばした値を当てにならない色として
            # 見せないよう塗らない。
            _, clamped = series.sampled_times(target, passage_hours[:1])
            if clamped[0]:
                fields["wind_grid"] = "out_of_range"
                logger.warning("風の評価軸配信の時刻が風グリッド範囲外 z=%d x=%d y=%d", z, x, y)
                return {}

            context = DynamicAxisRequestContext(
                bearing_deg=np.full(len(keys), bearing_deg, dtype=float),
                weather=None,
                travel_speed_ms=kmh_to_ms(speed_kmh),
                wind_series=series,
                start=target,
                passage_hours=passage_hours,
                wind_points=None if series.lattice is None else series.lattice.points_of(latitudes, longitudes),
            )
            values = evaluate_dynamic_material_arrays(context)[self.material_id]
            fields["computed"] = len(keys)
            # 値はキャッシュしない（docs/modules/backend/dynamic-way-values.md「キャッシュ」節）。
            return {key: round(float(value), 3) for key, value in zip(keys, values)}
