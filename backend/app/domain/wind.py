import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from app.domain.geo import haversine_distance_km_array
from app.domain.route import Coordinates

# 仮定巡航速度（km/h）の既定値。区間ごとの推定到達時刻（探索時の風の時刻選択・区間表示・
# 所要時間表示）と、風の追加負荷（`wind_drag_ratio_array`の走行速度）の算出に使う。
# リクエストごとに`RouteGenerateRequest.assumed_speed_kmh`で上書きできる（範囲は下記MIN/MAX）。
# 風・勾配に依存しない一律の定数として扱うことが前提——速度を風で可変にすると「時刻の
# 算出に速度が要り、速度が風（時刻依存）に影響される」という循環が生まれる。
ASSUMED_SPEED_KMH = 20.0
MIN_ASSUMED_SPEED_KMH = 5.0
MAX_ASSUMED_SPEED_KMH = 60.0

# 道なり距離／直線距離の比の想定値。探索前に各Edgeの通過予定時刻を「基準点からの直線距離
# ×この比÷仮定速度」で推定するときに使う。風の時間解像度（1時間＝仮定速度20km/hで20km）
# に対し、この比のばらつき（±20%程度）による推定誤差は片道15kmで約9分と十分小さい。
ROUTE_DETOUR_RATIO = 1.3

# 風の追加負荷（`wind_drag_ratio_array`）を無次元化する基準速度（m/s、時速20km）。
# `ASSUMED_SPEED_KMH`とは独立の専用定数にする——既定の想定速度を変えても材料のスケール
# （軸スタジオのbreakpointsが前提にする値域）がずれないようにするため。
WIND_DRAG_REFERENCE_SPEED_MS = 20.0 / 3.6


def kmh_to_ms(speed_kmh: float) -> float:
    return speed_kmh / 3.6


def _wind_relative_angle_rad(wind_direction_deg, travel_bearing_deg) -> np.ndarray:
    # wind_direction_degは気象学の慣習で「風が吹いてくる方向」。走行方位との差が0で
    # 正面からの向かい風、180で背後からの追い風。
    return np.radians(np.asarray(wind_direction_deg, dtype=float) - np.asarray(travel_bearing_deg, dtype=float))


def headwind_component_ms(wind_speed_ms, wind_direction_deg, travel_bearing_deg) -> np.ndarray:
    """進行方向に平行な風成分（m/s）。正=向かい風、負=追い風、横風は0。
    引数はいずれもスカラーまたは同じ長さの配列（numpyのブロードキャスト規則に従う）。

    `wind_drag_ratio_array`の部品であると同時に、非推奨材料`wind_penalty`の値そのもの
    （本番DBの公開軸がまだこの材料を参照しているため、切替が完了するまで残す）。
    """
    return np.asarray(wind_speed_ms, dtype=float) * np.cos(_wind_relative_angle_rad(wind_direction_deg, travel_bearing_deg))


def wind_drag_ratio_array(wind_speed_ms, wind_direction_deg, travel_bearing_deg, travel_speed_ms: float) -> np.ndarray:
    """風の追加負荷（材料`wind_drag_ratio`、無次元）。相対風速ベクトルの二乗則で、無風時に
    対する進行方向の空気抵抗の増分を`WIND_DRAG_REFERENCE_SPEED_MS`での無風時の抵抗を1と
    する倍率にしたもの。走行速度v・風速w・風向と走行方位の差dとして:

        x  = v + w·cos(d)              # 進行方向の相対風速（正=向かい風的）
        Vr = sqrt(x² + (w·sin(d))²)    # 相対風速の大きさ
        (Vr·x − v²) / v_ref²

    横風0のとき`sign(x)·x² − v²`の1次元式と一致し、追い風が走行速度を超える領域も連続。
    符号はxの符号で自然に決まる（正=向かい風で重くなる、負=追い風で楽になる、純横風は
    相対風速が増えるぶんだけ小さな正の値）。走行速度が大きいほど同じ風でも値が大きくなる。
    `wind_speed_ms`/`wind_direction_deg`/`travel_bearing_deg`はスカラーまたは同じ長さの配列、
    `travel_speed_ms`はリクエスト単位のスカラー（m/s、正）。
    """
    if travel_speed_ms <= 0:
        raise ValueError("wind_drag_ratio_array: travel_speed_ms must be positive")
    wind_speed = np.asarray(wind_speed_ms, dtype=float)
    angle = _wind_relative_angle_rad(wind_direction_deg, travel_bearing_deg)
    along = travel_speed_ms + wind_speed * np.cos(angle)
    cross = wind_speed * np.sin(angle)
    relative_speed = np.sqrt(along * along + cross * cross)
    return (relative_speed * along - travel_speed_ms * travel_speed_ms) / (WIND_DRAG_REFERENCE_SPEED_MS**2)


def wind_drag_ratio(wind_speed_ms: float, wind_direction_deg: float, travel_bearing_deg: float, travel_speed_ms: float) -> float:
    """`wind_drag_ratio_array`のスカラー版（1地点・1方位向け）。"""
    return float(wind_drag_ratio_array(wind_speed_ms, wind_direction_deg, travel_bearing_deg, travel_speed_ms))


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
