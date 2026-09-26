"""鍵→動的値配信層（風）。

走行方位は**ユーザーが指定した単一の値**（全道路共通）で、道路自身のOSM格納方向は使わない。
風グリッドもタイル中心1点で代表させる。この2つの結果、**同じタイル内の全wayが同じ値を持つ**
——鍵の一覧さえ取れればよく、計算はタイルにつき1回で足りる。

制御フローの詳細はdocs/modules/backend/dynamic-way-values.md「`WindWayService`」節参照。
"""

import logging
from datetime import datetime

from app.domain.time_zone import JST
from app.domain.material_catalog import WIND_DRAG_RATIO
from app.domain.region import BoundingBox, tile_bounds_lonlat
from app.domain.route import Coordinates
from app.domain.wind import kmh_to_ms, wind_drag_ratio
from app.domain.wind_grid import WIND_GRID_DETAIL_SPACING_DEG, nearest_grid_point
from app.infrastructure.database import DB_UNAVAILABLE_ERRORS
from app.infrastructure.debug_log import log_external_call
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.weather_service import WeatherService

logger = logging.getLogger("ridecompass.wind_way")

def _tile_center(bbox: BoundingBox) -> Coordinates:
    return Coordinates(
        latitude=(bbox.min_latitude + bbox.max_latitude) / 2,
        longitude=(bbox.min_longitude + bbox.max_longitude) / 2,
    )


def _nearest_time_index(times: list[str], target: datetime) -> int | None:
    """風グリッドの時刻配列からtargetに最も近いindexを求める。範囲外はNone。

    時刻配列はJST基準の壁時計時刻をtzなし文字列で持つ。targetがtz-awareならJSTへ変換して
    から比較すること——tzinfoを剥がすだけだと時差ぶんズレる。
    """
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
    def __init__(self, repository: RoadGraphRepository, weather_service: WeatherService):
        self._repository = repository
        self._weather_service = weather_service

    #: 返す生値の材料id。この材料を参照する軸の配信を担当する。
    material_id = WIND_DRAG_RATIO

    @classmethod
    def build(cls, repository: RoadGraphRepository, weather_service: WeatherService) -> "WindWayService":
        """登録テーブルから呼ぶための統一シグネチャ。依存の要否はサービスごとに違う。"""
        return cls(repository=repository, weather_service=weather_service)

    async def get_way_values(
        self, z: int, x: int, y: int, at: datetime | None, bearing_deg: float | None, speed_kmh: float | None = None
    ) -> dict[str, float]:
        """指定タイル内のフィーチャーごとの風の材料値を返す。

        取込範囲外・風データ取得不能はいずれも空dictへ倒し、「この道路に
        色が付かない」という劣化で済ませる。

        `bearing_deg`・`speed_kmh`は材料非依存な呼び出し口と形を揃えるため省略可能な形に
        なっているが、風はどちらも無いと計算できない。Noneのまま到達したら即座に失敗させる
        （router側の検証をすり抜けた場合の防御。無音でNoneを計算へ渡さない）。
        """
        if bearing_deg is None:
            raise ValueError("WindWayService.get_way_valuesにはbearing_degが必須です")
        if speed_kmh is None:
            raise ValueError("WindWayService.get_way_valuesにはspeed_kmhが必須です")
        target = at or datetime.now(JST)
        bbox = tile_bounds_lonlat(z, x, y)

        with log_external_call("region:wind-way-penalty", z=z, x=x, y=y) as fields:
            try:
                feature_keys = await self._repository.get_feature_keys_in_tile(z, x, y, bbox)
            except DB_UNAVAILABLE_ERRORS as exc:
                fields["result"] = "error"
                fields["warned"] = True
                logger.warning("風の評価軸配信の鍵取得に失敗 z=%d x=%d y=%d error=%r", z, x, y, exc)
                return {}
            if not feature_keys:
                fields["postgis"] = "uncovered" if feature_keys is None else "empty"
                return {}
            fields["feature_count"] = len(feature_keys)

            # タイル中心1点の風を全wayへ配るだけで計算が軽いため、値はキャッシュしない
            # （保持する容量に見合う節約にならない）。格子間隔は環境グループの風表示と
            # 揃える。MSMの格子はこれより粗く、細かくしても補間値を刻むだけで精度は上がらない。
            grid_point = nearest_grid_point(_tile_center(bbox), spacing_deg=WIND_GRID_DETAIL_SPACING_DEG)
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
            fields["computed"] = len(feature_keys)

            # 同じタイル内の全wayが同じ値を持つため、ここで1回だけbroadcastする。
            return dict.fromkeys(feature_keys, penalty)
