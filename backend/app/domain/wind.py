import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from app.domain.geo import haversine_distance_km_array
from app.domain.route import Coordinates

# 仮定巡航速度（km/h）の既定値。区間ごとの推定到達時刻（探索時の風の時刻選択・区間表示・
# 所要時間表示）の算出にのみ使う。リクエストごとに`RouteGenerateRequest.assumed_speed_kmh`
# で上書きできる（範囲は下記MIN/MAX）。風・勾配に依存しない一律の定数として扱うことが
# 前提——速度を風で可変にすると「時刻の算出に速度が要り、速度が風（時刻依存）に影響される」
# という循環が生まれる。
ASSUMED_SPEED_KMH = 20.0
MIN_ASSUMED_SPEED_KMH = 5.0
MAX_ASSUMED_SPEED_KMH = 60.0

# 道なり距離／直線距離の比の想定値。探索前に各Edgeの通過予定時刻を「基準点からの直線距離
# ×この比÷仮定速度」で推定するときに使う。風の時間解像度（1時間＝仮定速度20km/hで20km）
# に対し、この比のばらつき（±20%程度）による推定誤差は片道15kmで約9分と十分小さい。
ROUTE_DETOUR_RATIO = 1.3


class WindCalculator:
    """走行方位と風向風速から、走行への風の影響（ペナルティ）を計算する。

    正の値=向かい風（走行が重くなる）、負の値=追い風（走行が楽になる）、0付近=横風（影響小）。
    進行方向に平行な風成分のみが走行に影響するというモデル。
    """

    @staticmethod
    def wind_penalty(wind_speed_ms: float, wind_direction_deg: float, travel_bearing_deg: float) -> float:
        # wind_direction_degは気象学の慣習で「風が吹いてくる方向」。
        # 走行方位と風向の差が0（風が正面から吹いてくる）＝向かい風＝cos(0)=1で最大。
        # 差が180度（風が背後から吹いてくる＝追い風）＝cos(180)=-1。
        diff = math.radians(wind_direction_deg - travel_bearing_deg)
        return wind_speed_ms * math.cos(diff)


@dataclass(frozen=True)
class WindForecastSeries:
    """1地点の時別風向・風速の予報系列（1時間刻み、`times`はタイムゾーン無しの
    ローカル時刻[JST]）。探索前に各Edgeの通過予定時刻へ対応する風を引くために使う。"""

    times: list[datetime]
    speed_ms: np.ndarray
    direction_deg: np.ndarray

    def __post_init__(self) -> None:
        if len(self.times) < 2 or len(self.times) != len(self.speed_ms) or len(self.times) != len(self.direction_deg):
            raise ValueError("WindForecastSeries: times/speed_ms/direction_deg must have the same length (>= 2)")
        step_hours = (self.times[1] - self.times[0]).total_seconds() / 3600
        if not math.isclose(step_hours, 1.0):
            raise ValueError(f"WindForecastSeries: expected hourly steps, got {step_hours}h")

    def sample(self, start: datetime, passage_hours: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """`start`（タイムゾーン無しのローカル時刻）から`passage_hours`時間後に最も近い
        時刻の（風速, 風向）配列を返す。系列の範囲外は端の値へクランプする（探索では欠損
        より端の値の方が妥当）。"""
        start_offset_hours = (start - self.times[0]).total_seconds() / 3600
        index = np.rint(start_offset_hours + np.asarray(passage_hours, dtype=float)).astype(np.int64)
        index = np.clip(index, 0, len(self.times) - 1)
        return self.speed_ms[index], self.direction_deg[index]


def estimate_passage_hours(
    mid_lat: np.ndarray,
    mid_lon: np.ndarray,
    anchor: Coordinates,
    offset_hours: float,
    direction: int,
    speed_kmh: float,
    detour_ratio: float = ROUTE_DETOUR_RATIO,
) -> np.ndarray:
    """各Edge（中点`mid_lat`/`mid_lon`）の通過予定時刻を、出発からの経過時間（h）として
    基準点`anchor`からの直線距離だけで推定する。`direction=+1`は基準点から離れていく
    レグ（`offset_hours + detour×距離/速度`）、`direction=-1`は基準点へ向かうレグ
    （`offset_hours − detour×距離/速度`、`offset_hours`は基準点への到着予定時刻）。
    経路の状態に依存しないため、探索前にbbox全体ぶんを1回のベクトル演算で求められる。"""
    if speed_kmh <= 0:
        raise ValueError("estimate_passage_hours: speed_kmh must be positive")
    distance_km = haversine_distance_km_array(mid_lat, mid_lon, anchor)
    return offset_hours + direction * detour_ratio * distance_km / speed_kmh
