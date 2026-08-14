import asyncio
from datetime import datetime, timedelta

from app.domain.geo import bearing_between, haversine_distance_km
from app.domain.route import Coordinates
from app.domain.wind import WindCalculator
from app.services.weather_service import WeatherService

MAX_CONCURRENT_REQUESTS = 5

# 仮定巡航速度。MVPでは固定値。将来はユーザー入力/プロファイルに応じて可変にする拡張ポイント。
ASSUMED_SPEED_KMH = 20.0


class WindService:
    """指定された点列から、走行中に受ける風の影響（区間ごとのwind_penaltyとルート全体のwind_score）を算出する。

    サンプル点は呼び出し元（`RouteGenerator`）が渡す（標高・路面と同じ点集合・同じ並びで評価するため）。
    各区間について「起点からの累積距離÷仮定巡航速度」で推定到達時刻を計算、その時刻・地点の風を
    `WeatherService`（Step6で「地点＋時刻」対応済み）から取得して`WindCalculator`で区間ごとのペナルティを求める。
    `semaphore`はコンストラクタで1つだけ生成し共有する（`ElevationService`と同じ理由）。
    """

    def __init__(self, weather_service: WeatherService):
        self._weather_service = weather_service
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

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

        async def fetch(meta):
            async with self._semaphore:
                return await self._weather_service.get_conditions(meta["point"], at=meta["arrival_time"])

        conditions = await asyncio.gather(*(fetch(meta) for meta in segment_meta))

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
