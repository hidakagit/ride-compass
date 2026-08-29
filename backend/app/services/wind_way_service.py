"""way_id→wind_penalty配信層（改善計画T405、docs/tasks/T400.md「2. 動的要素（時刻・向き等）を
含む材料は『環境』と『道路』の二重表現を持つ」節）。

「評価軸」グループとしての風（軸スタジオの軸と同じ扱いで道路そのものを線で塗る表示）の
基盤。「環境」グループの風（時刻＋方位スライダー＋`gridFill`面表示、windLayer.ts/
dynamicWeather.ts）とは別経路——本サービスは、道路のbearing_deg
（`RoadGraphRepository.get_way_bearings_in_tile`、osm_raw_ways.geomのstart→end基準）と、
既存の風グリッド（`WeatherService.get_wind_grid`、格子点ごとの時間別風向風速）を掛け合わせて
`WindCalculator.wind_penalty`（backend/app/domain/wind.py、既存の純粋関数をそのまま流用）を
計算するだけの薄いオーケストレーション層で、新しいドメインロジックは持たない。

対象範囲はリクエストされたタイル座標（z/x/y）に絞る（全国・全way分の常時計算は非現実的、
T405.mdの設計方針）。計算結果は`way_id`をキーにRedisへキャッシュする
（`wind_way_penalty_cache.py`）ため、同じ道路が複数タイル・複数ズームレベルにまたがって
現れても再計算しない。
"""

import logging
from datetime import datetime

from app.domain.region import ROAD_GRAPH_TILE_ZOOM, BoundingBox, tile_ancestor, tile_bounds_lonlat
from app.domain.route import Coordinates
from app.domain.wind import WindCalculator
from app.domain.wind_grid import nearest_grid_point
from app.infrastructure.debug_log import log_external_call
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.infrastructure.wind_way_penalty_cache import get_way_penalties_many, set_way_penalties_many
from app.services.route_generator import JST
from app.services.weather_service import WeatherService

logger = logging.getLogger("ridecompass.wind_way")


def _hour_bucket(at: datetime) -> str:
    """時刻を1時間バケットへ丸める（wind_way_penalty_cache.pyのキー、モジュールdocstring参照）。"""
    return at.strftime("%Y-%m-%dT%H")


def _tile_center(bbox: BoundingBox) -> Coordinates:
    return Coordinates(
        latitude=(bbox.min_latitude + bbox.max_latitude) / 2,
        longitude=(bbox.min_longitude + bbox.max_longitude) / 2,
    )


def _nearest_time_index(times: list[str], target: datetime) -> int | None:
    """風グリップのhourly時刻配列から、targetに最も近いindexを求める
    （weather_service.py: WeatherService._nearest_hourly_index/_within_hourly_rangeと同じ
    「最近傍だが範囲外は不可」という考え方を踏襲した簡易版。targetはtz-aware/naiveどちらでも
    受け付け、wall-clock成分[JST想定、route_generator.py: JSTのコメント参照]だけを比較する）。
    範囲外（風グリッドがまだ届いていない遠い未来・過去）はNoneを返し、呼び出し元は「不明」
    として扱う。"""
    if not times:
        return None
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

    async def get_way_wind_penalties(self, z: int, x: int, y: int, at: datetime | None) -> dict[int, float]:
        """指定タイル内のway_idごとのwind_penaltyを返す。repository未接続・取込範囲外・
        風データ取得不能等はいずれも空dictへ倒す（地図表示という既存機能全体を落とさず、
        「この道路には色が付かない」という安全側の劣化で済ませる、他タイル系メソッドと
        同じグレースフルデグレード方針）。
        """
        if self._repository is None:
            return {}
        target = at or datetime.now(JST)
        bbox = tile_bounds_lonlat(z, x, y)
        ancestor_x, ancestor_y = tile_ancestor(z, x, y, ROAD_GRAPH_TILE_ZOOM)

        with log_external_call("region:wind-way-penalty", z=z, x=x, y=y) as fields:
            try:
                bearings = await self._repository.get_way_bearings_in_tile(
                    z, x, y, bbox, (ROAD_GRAPH_TILE_ZOOM, ancestor_x, ancestor_y)
                )
            except Exception as exc:  # noqa: BLE001 DB障害は空dictへ倒す（他タイル系と同じ方針）
                fields["result"] = "error"
                fields["warned"] = True
                logger.warning("風の評価軸配信のbearing取得に失敗 z=%d x=%d y=%d error=%r", z, x, y, exc)
                return {}
            if not bearings:
                fields["postgis"] = "uncovered" if bearings is None else "empty"
                return {}
            fields["way_count"] = len(bearings)

            hour_bucket = _hour_bucket(target)
            way_ids = list(bearings.keys())
            cached = await get_way_penalties_many(way_ids, hour_bucket)
            fields["cache_hit"] = len(cached)
            missing_ids = [way_id for way_id in way_ids if way_id not in cached]
            if not missing_ids:
                fields["cache_status"] = "hit"
                return cached
            fields["cache_status"] = "partial" if cached else "miss"

            grid_point = nearest_grid_point(_tile_center(bbox))
            times, points = await self._weather_service.get_wind_grid([grid_point])
            wind_grid_point = points[0] if points else None
            if wind_grid_point is None:
                fields["wind_grid"] = "unavailable"
                logger.warning("風の評価軸配信の風グリッド取得に失敗 z=%d x=%d y=%d", z, x, y)
                return cached
            index = _nearest_time_index(times, target)
            if index is None:
                fields["wind_grid"] = "out_of_range"
                logger.warning("風の評価軸配信の時刻が風グリッド範囲外 z=%d x=%d y=%d", z, x, y)
                return cached

            wind_speed = wind_grid_point.wind_speed_ms[index]
            wind_direction = wind_grid_point.wind_direction_deg[index]
            computed = {
                way_id: round(WindCalculator.wind_penalty(wind_speed, wind_direction, bearings[way_id]), 2)
                for way_id in missing_ids
            }
            await set_way_penalties_many(computed, hour_bucket)
            fields["computed"] = len(computed)
            return {**cached, **computed}
