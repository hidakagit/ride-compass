"""雨の材料。アメダスの毎正時の1時間雨量を観測所ごとに履歴で持ち、そこから区間ごとに引く。

窓の長さの一覧（`RAIN_WINDOW_HOURS`）がこの材料群の唯一の宣言で、材料id・材料カタログの行・
持つ履歴の長さはここから導く。値は観測どおりの量（mm・時間）で、どこからを「濡れている」と
みなすかのしきい値は軸の側が決める。

何mm以上を雨と数えるかは、天気の「降っていない」の境（`weather.PRECIPITATION_MIN_MM`）と同じ事実として
そちらを読む。雨量計は0.5mm刻みなので、観測された雨はすべて当たる。
"""

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from app.domain.weather import PRECIPITATION_MIN_MM

RAIN_WINDOW_HOURS: tuple[int, ...] = (1, 3, 4, 6, 12, 24, 48, 72)
#: 観測所ごとに持つ1時間雨量の本数。最も長い窓と、止んでからの時間の上限を兼ねる。
RAIN_HISTORY_HOURS = max(RAIN_WINDOW_HOURS)

HOURS_SINCE_RAIN = "hours_since_rain"


def rain_window_material_id(hours: int) -> str:
    return f"rain_{hours}h_mm"


RAIN_MATERIAL_IDS: tuple[str, ...] = (
    *(rain_window_material_id(hours) for hours in RAIN_WINDOW_HOURS),
    HOURS_SINCE_RAIN,
)

# 1回に距離を並べる区間の数。区間数×観測所数の配列を一度に作らないための刻み。
_NEAREST_CHUNK = 512


@dataclass(frozen=True)
class StationRainMaterials:
    """観測所ごとの雨の材料の値（`RAIN_MATERIAL_IDS`→観測所の並びの配列、値が無ければNaN）。"""

    #: 最も新しい1時間の終わり（JSTの正時）。
    latest_hour: datetime
    latitudes: np.ndarray
    longitudes: np.ndarray
    values: dict[str, np.ndarray]


def rain_material_values(hourly_mm: np.ndarray) -> dict[str, np.ndarray]:
    """(観測所, 時刻)の1時間雨量から材料の値を求める。時刻は古い順に`RAIN_HISTORY_HOURS`本で、
    最後の列が直近の1時間。欠測はNaN。

    窓の雨量は、窓の中に欠測の1時間が1つでもあれば値を持たない（0として足すと少なく見せる）。
    止んでからの時間は、直近の1時間に雨があれば0、k時間前の1時間が最後の雨ならk。
    さかのぼって雨を見つける前に欠測に当たれば値を持たず、全部さかのぼって雨が無ければ
    `RAIN_HISTORY_HOURS`（それ以上）になる。
    """
    values ={rain_window_material_id(hours): hourly_mm[:, -hours:].sum(axis=1) for hours in RAIN_WINDOW_HOURS}
    newest_first = hourly_mm[:, ::-1]
    rained = newest_first >= PRECIPITATION_MIN_MM
    missing = np.isnan(newest_first)
    first_rain = np.where(rained.any(axis=1), rained.argmax(axis=1), RAIN_HISTORY_HOURS)
    first_missing = np.where(missing.any(axis=1), missing.argmax(axis=1), RAIN_HISTORY_HOURS)
    hours_since = first_rain.astype(float)
    hours_since[first_missing < first_rain] = np.nan
    values[HOURS_SINCE_RAIN] = hours_since
    return values


def nearest_point_indices(
    latitudes: np.ndarray, longitudes: np.ndarray, point_latitudes: np.ndarray, point_longitudes: np.ndarray
) -> np.ndarray:
    """各地点（`latitudes`/`longitudes`）に最も近い点（`point_*`）の番号。

    距離は地点ごとの緯度で経度を縮めた平面の距離で比べる。観測所の間隔（十数km）では球面の
    距離と順位が入れ替わらない。
    """
    result = np.empty(len(latitudes), dtype=np.intp)
    for start in range(0, len(latitudes), _NEAREST_CHUNK):
        stop = start + _NEAREST_CHUNK
        latitude = latitudes[start:stop, None]
        dx = (point_longitudes[None, :] - longitudes[start:stop, None]) * np.cos(np.radians(latitude))
        dy = point_latitudes[None, :] - latitude
        result[start:stop] = np.argmin(dx * dx + dy * dy, axis=1)
    return result
