"""`domain/rain.py`——1時間雨量の履歴から雨の材料の値を求め、道へ最寄りの雨量計の値を引く。

入口は`rain_material_values`（観測所ごとの値）・`rain_material_columns`（地点ごとの値）・
`is_rain_history_current`（配ってよい古さ）。

ここで見ないもの:
- 履歴をRedisから組み立てること → `test_jma_amedas_service.py`
- タイルの道へ配ること → `test_rain_way_service.py`
- 最寄りの点の選び方そのもの（`domain/geo.py: nearest_point_indices`） → `test_geo.py`
"""

from datetime import datetime, timedelta

import numpy as np
import pytest

from app.domain import rain
from app.domain.rain import (
    HOURS_SINCE_RAIN,
    RAIN_HISTORY_HOURS,
    RAIN_HISTORY_MAX_AGE,
    RAIN_WINDOW_HOURS,
    StationRainMaterials,
    is_rain_history_current,
    rain_material_columns,
    rain_material_values,
    rain_window_material_id,
)

NAN = float("nan")


def _history(**hours_ago: float) -> np.ndarray:
    """観測所1つの履歴（古い順、最後の列が直近の1時間）。`h<k>=値`でk時間前の1時間を置き、ほかは0。"""
    row = np.zeros(RAIN_HISTORY_HOURS)
    for key, value in hours_ago.items():
        row[-1 - int(key[1:])] = value
    return row[np.newaxis, :]


def _value(values: dict[str, np.ndarray], material_id: str) -> float:
    return float(values[material_id][0])


@pytest.mark.parametrize("window", RAIN_WINDOW_HOURS)
def test_a_window_sums_only_the_hours_inside_it(window):
    """窓のちょうど内側（最も古い1時間）は数え、ちょうど外側は数えない。"""
    inside = {"h0": 1.0, f"h{window - 1}": 2.0} if window > 1 else {"h0": 3.0}
    outside = {f"h{window}": 4.0} if window < RAIN_HISTORY_HOURS else {}

    values = rain_material_values(_history(**inside, **outside))

    assert _value(values, rain_window_material_id(window)) == 3.0


@pytest.mark.parametrize("window", RAIN_WINDOW_HOURS)
def test_a_missing_hour_inside_the_window_leaves_the_window_without_a_value(window):
    """欠測を0として足すと、雨を少なく見せる。窓の外の欠測は効かない。"""
    inside = rain_material_values(_history(**{f"h{window - 1}": NAN}))
    outside = rain_material_values(_history(**{f"h{window}": NAN})) if window < RAIN_HISTORY_HOURS else None

    assert np.isnan(_value(inside, rain_window_material_id(window)))
    if outside is not None:
        assert _value(outside, rain_window_material_id(window)) == 0.0


@pytest.mark.parametrize(
    ("history", "expected"),
    [
        (_history(h0=1.0), 0.0),
        (_history(h5=1.0, h9=4.0), 5.0),
        (_history(), float(RAIN_HISTORY_HOURS)),
        (_history(h2=NAN, h5=1.0), NAN),
        (_history(h5=1.0, h7=NAN), 5.0),
    ],
    ids=["直近に雨", "最後の雨が5時間前", "履歴に雨が無い", "雨を見つける前に欠測", "雨より古い欠測"],
)
def test_hours_since_rain_counts_back_to_the_last_rainy_hour(history, expected):
    value = _value(rain_material_values(history), HOURS_SINCE_RAIN)

    assert (np.isnan(value) and np.isnan(expected)) or value == expected


def test_rain_starts_at_the_smallest_amount_that_is_not_dry():
    """天気の「降っていない」の境と同じ量から雨と数える。"""
    at_the_border = rain_material_values(_history(h3=rain.PRECIPITATION_MIN_MM))
    below = rain_material_values(_history(h3=np.nextafter(rain.PRECIPITATION_MIN_MM, 0.0)))

    assert _value(at_the_border, HOURS_SINCE_RAIN) == 3.0
    assert _value(below, HOURS_SINCE_RAIN) == float(RAIN_HISTORY_HOURS)


def test_each_station_gets_its_own_values():
    values = rain_material_values(np.vstack([_history(h0=2.0), _history(h4=1.0)]))

    assert values[HOURS_SINCE_RAIN].tolist() == [0.0, 4.0]
    assert values[rain_window_material_id(1)].tolist() == [2.0, 0.0]


STATIONS = StationRainMaterials(
    latest_hour=datetime(2026, 7, 1, 12, 0),
    latitudes=np.array([35.0, 36.0]),
    longitudes=np.array([139.0, 139.0]),
    values={"rain_a": np.array([1.0, 2.0]), "rain_b": np.array([NAN, 5.0])},
)


def test_each_place_reads_its_nearest_rain_gauge():
    columns = rain_material_columns(STATIONS, np.array([35.1, 35.9, 35.4]), np.array([139.0, 139.0, 139.0]))

    assert columns["rain_a"].tolist() == [1.0, 2.0, 1.0]


def test_a_missing_value_at_the_nearest_gauge_is_not_filled_from_the_next():
    """近さの順に埋めると、同じ道が欠測の有無で別の雨量計の値へ静かに切り替わる。"""
    columns = rain_material_columns(STATIONS, np.array([35.1]), np.array([139.0]))

    assert np.isnan(columns["rain_b"][0])


@pytest.mark.parametrize(
    ("age", "expected"),
    [(RAIN_HISTORY_MAX_AGE, True), (RAIN_HISTORY_MAX_AGE + timedelta(seconds=1), False)],
    ids=["上限ちょうど", "上限を超えた"],
)
def test_a_history_older_than_the_limit_is_not_served(age, expected):
    """バッチが止まったまま、古い雨量を今の値として塗らない。"""
    latest = datetime(2026, 7, 1, 12, 0)

    assert is_rain_history_current(latest, latest + age) is expected
