"""雨の材料（`domain/rain.py`）。観測所ごとの1時間雨量の履歴から、窓の雨量と雨が止んでからの時間を求める。"""

import numpy as np

from app.domain.rain import (
    HOURS_SINCE_RAIN,
    RAIN_HISTORY_HOURS,
    RAIN_MATERIAL_IDS,
    RAIN_WINDOW_HOURS,
    nearest_point_indices,
    rain_material_values,
    rain_window_material_id,
)


def _history(*newest_first: float) -> np.ndarray:
    """直近の1時間から古い順に並べた値で1観測所ぶんの履歴を作る。残りは0mm。"""
    row = np.zeros(RAIN_HISTORY_HOURS)
    row[RAIN_HISTORY_HOURS - len(newest_first):] = newest_first[::-1]
    return row[None, :]


def test_every_window_sums_exactly_its_own_hours():
    """各窓は直近の窓の長さぶんの1時間雨量だけを足す（1本ずれると、雨が上がった直後の値が変わる）。"""
    # k時間前の1時間にk+1 mmを置く。窓が1本ずれると和が変わる。
    hourly = _history(*(float(back + 1) for back in range(RAIN_HISTORY_HOURS)))
    values = rain_material_values(hourly)
    for hours in RAIN_WINDOW_HOURS:
        assert values[rain_window_material_id(hours)][0] == hours * (hours + 1) / 2


def test_a_missing_hour_inside_a_window_leaves_that_window_without_a_value():
    """欠測を0として足すと雨量を少なく見せる。窓の外の欠測は、その窓に影響しない。"""
    hourly = _history(1.0, 2.0, np.nan)
    values = rain_material_values(hourly)
    assert values[rain_window_material_id(1)][0] == 1.0
    for hours in RAIN_WINDOW_HOURS:
        if hours >= 3:
            assert np.isnan(values[rain_window_material_id(hours)][0])


def test_hours_since_rain_counts_back_to_the_last_rainy_hour():
    values = rain_material_values(np.vstack([_history(0.5), _history(0.0, 0.0, 0.0, 1.5), _history(0.0)]))
    assert values[HOURS_SINCE_RAIN].tolist() == [0.0, 3.0, RAIN_HISTORY_HOURS]


def test_hours_since_rain_is_unknown_when_a_missing_hour_comes_before_any_rain():
    """欠測の1時間に降っていたかもしれない。雨より古い欠測は、止んでからの時間を変えない。"""
    values = rain_material_values(np.vstack([_history(0.0, np.nan, 1.0), _history(0.0, 1.0, np.nan)]))
    assert np.isnan(values[HOURS_SINCE_RAIN][0])
    assert values[HOURS_SINCE_RAIN][1] == 1.0


def test_every_rain_material_gets_a_value_per_station():
    values = rain_material_values(np.vstack([_history(1.0), _history(0.0)]))
    assert set(values) == set(RAIN_MATERIAL_IDS)
    assert all(len(array) == 2 for array in values.values())


def test_nearest_point_matches_the_great_circle_nearest():
    """観測所の間隔（十数km）では、平面で比べても球面の最寄りと同じ観測所になる。区切りの刻みを
    またぐ件数で確かめる。"""
    rng = np.random.default_rng(0)
    station_lat = rng.uniform(34.0, 37.0, 300)
    station_lon = rng.uniform(138.0, 141.0, 300)
    lat = rng.uniform(34.5, 36.5, 1500)
    lon = rng.uniform(138.5, 140.5, 1500)

    phi1, phi2 = np.radians(lat)[:, None], np.radians(station_lat)[None, :]
    dphi = phi2 - phi1
    dlmb = np.radians(station_lon)[None, :] - np.radians(lon)[:, None]
    haversine = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlmb / 2) ** 2
    expected = np.argmin(haversine, axis=1)

    assert (nearest_point_indices(lat, lon, station_lat, station_lon) == expected).all()
