from datetime import datetime, timedelta

from app.domain.geo import bearing_between, haversine_distance_km
from app.domain.route import Coordinates
from app.domain.wind import ASSUMED_SPEED_KMH, WindCalculator
from app.services.weather_service import WeatherService


class WindService:
    """指定された点列から、走行中に受ける風の影響（区間ごとのwind_penaltyとルート全体のwind_score）を算出する。

    サンプル点は呼び出し元（`RouteGenerator`）が渡す（標高・路面と同じ点集合・同じ並びで評価するため）。
    各区間について「起点からの累積距離÷仮定巡航速度」で推定到達時刻を計算、その時刻・地点の風を
    `WeatherService.get_conditions_many`でまとめて取得し`WindCalculator`で区間ごとのペナルティを求める。
    以前は区間ごとに個別リクエスト（同時実行数5で並列）していたが、本番（Render、共有の送信元IP）では
    ルート1本の生成だけでOpen-Meteo側の429が常態化していたため、Open-Meteoのマルチロケーション機能で
    1リクエストへ集約した（原因調査ログ参照）。
    """

    def __init__(self, weather_service: WeatherService):
        self._weather_service = weather_service

    async def prefetch(self, points_per_candidate: list[list[Coordinates]]) -> None:
        """複数候補（方位）ぶんのサンプル点をまとめ、Open-Meteoへの呼び出しを1回に集約して
        先読みする。呼び出し元（エンジン）が候補ごとに`get_wind_profile`を`asyncio.gather`で
        並列実行する前にこれを呼んでおくことで、候補数ぶん（最大8本）同時発火していた
        リクエストを実質1本にまとめられる（本番のOpen-Meteo 429常態化への対策）。
        """
        all_points = [point for points in points_per_candidate for point in points]
        if all_points:
            await self._weather_service.prefetch(all_points)

    async def get_wind_profile(self, points: list[Coordinates], start_time: datetime) -> dict:
        if len(points) < 2:
            return {"wind_score": None, "segments": []}

        segment_meta = []
        cumulative_km = 0.0
        for p1, p2 in zip(points, points[1:]):
            segment_distance_km = haversine_distance_km(p1, p2)
            bearing_deg = bearing_between(p1, p2)
            elapsed_hours = cumulative_km / ASSUMED_SPEED_KMH
            arrival_time = start_time + timedelta(hours=elapsed_hours)
            segment_meta.append(
                {
                    "point": p1,
                    "arrival_time": arrival_time,
                    "bearing_deg": bearing_deg,
                    "distance_km": segment_distance_km,
                }
            )
            cumulative_km += segment_distance_km

        conditions = await self._weather_service.get_conditions_many(
            [meta["point"] for meta in segment_meta],
            [meta["arrival_time"] for meta in segment_meta],
        )

        segments = []
        weighted_penalties = []
        total_weight = 0.0
        for meta, condition in zip(segment_meta, conditions):
            wind_penalty = None
            if condition is not None:
                wind_penalty = WindCalculator.wind_penalty(
                    condition.wind_speed_ms, condition.wind_direction_deg, meta["bearing_deg"]
                )
                if meta["distance_km"] > 0:
                    weighted_penalties.append(wind_penalty * meta["distance_km"])
                    total_weight += meta["distance_km"]

            segments.append(
                {
                    "distance_km": meta["distance_km"],
                    "bearing_deg": meta["bearing_deg"],
                    "arrival_time": meta["arrival_time"],
                    "wind_penalty": wind_penalty,
                }
            )

        wind_score = round(sum(weighted_penalties) / total_weight, 2) if total_weight > 0 else None

        return {"wind_score": wind_score, "segments": segments}
