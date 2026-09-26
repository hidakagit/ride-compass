"""鍵→動的値配信層（雨）。

各フィーチャーは中ほどに最も近い雨量計の値を引く（`domain/rain.py`）。値は今の観測で、
走行方位・時刻・想定速度には依らない。1つの実装が雨の材料すべてを担当し、どの材料を返すかは
組み立てるときに受け取る——窓の長さの一覧（`RAIN_WINDOW_HOURS`）が増えても、ここは変わらない。

制御フローの詳細はdocs/modules/backend/dynamic-way-values.md「`RainWayService`」節参照。
"""

import logging
from datetime import datetime

import numpy as np

from app.domain.rain import RAIN_MATERIAL_IDS, nearest_point_indices
from app.domain.region import tile_bounds_lonlat
from app.domain.time_zone import JST
from app.infrastructure.database import DB_UNAVAILABLE_ERRORS
from app.infrastructure.debug_log import log_external_call, log_throttled_warning
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.jma_amedas_service import load_station_rain_materials
from app.services.weather_service import WeatherService

logger = logging.getLogger("ridecompass.rain_way")


class RainWayService:
    #: 担当する材料id。インスタンスはそのうち1つ（`material_id`）の値を返す。
    material_ids = RAIN_MATERIAL_IDS

    def __init__(self, repository: RoadGraphRepository, material_id: str):
        self._repository = repository
        self.material_id = material_id

    @classmethod
    def build(cls, repository: RoadGraphRepository, weather_service: WeatherService, material_id: str) -> "RainWayService":
        """登録テーブルから呼ぶための統一シグネチャ。依存の要否はサービスごとに違う。"""
        return cls(repository=repository, material_id=material_id)

    async def get_way_values(
        self, z: int, x: int, y: int, at: datetime | None, bearing_deg: float | None, speed_kmh: float | None = None
    ) -> dict[str, float]:
        """指定タイル内のフィーチャーごとの雨の材料値を返す。`at`・`bearing_deg`・`speed_kmh`は
        材料非依存な呼び出し口と形を揃えるためだけに受け取る。

        履歴が無い・古い、取込範囲外、観測所の値が欠測の道は結果から除く（地図上は「データなし」）。
        """
        bbox = tile_bounds_lonlat(z, x, y)
        with log_external_call("region:rain-way-values", z=z, x=x, y=y, material=self.material_id) as fields:
            stations = await load_station_rain_materials(datetime.now(JST))
            if stations is None:
                fields["rain_history"] = "unavailable"
                # 地図の1画面ぶんのタイルが同時に当たるため、抑制付きで出す。
                log_throttled_warning("region:rain-way-values", "雨の材料配信の観測履歴が無いか古い z=%d x=%d y=%d", z, x, y)
                return {}
            try:
                midpoints = await self._repository.get_feature_midpoints_in_tile(z, x, y, bbox)
            except DB_UNAVAILABLE_ERRORS as exc:
                fields["result"] = "error"
                fields["warned"] = True
                logger.warning("雨の材料配信の鍵取得に失敗 z=%d x=%d y=%d error=%r", z, x, y, exc)
                return {}
            if not midpoints:
                fields["postgis"] = "uncovered" if midpoints is None else "empty"
                return {}
            keys = list(midpoints)
            latitudes = np.array([midpoints[key][0] for key in keys], dtype=float)
            longitudes = np.array([midpoints[key][1] for key in keys], dtype=float)
            nearest = nearest_point_indices(latitudes, longitudes, stations.latitudes, stations.longitudes)
            values = stations.values[self.material_id][nearest]
            result = {key: round(float(value), 1) for key, value in zip(keys, values) if not np.isnan(value)}
            fields["feature_count"] = len(keys)
            fields["computed"] = len(result)
            return result
