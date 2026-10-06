"""`domain/weather.py`——アメダスの実測と推計気象分布の区分から天気コードを導く。

入口は`derive_observed_weather_code`。「今日」のパネルの読み方（今日の範囲・日次の値・コマ）は
`test_weather_service.py`が入口から見る。

ここで見ないもの:
- 観測値と推計気象分布の区分がこの規則へ渡り、応答に出ること → `test_jma_amedas_service.py`
"""

from typing import get_args

import pytest

from app.domain.weather import SuikeiWeather, derive_observed_weather_code
from app.domain.weather_display import WEATHER_CATEGORIES


@pytest.mark.parametrize(
    ("precipitation_10min", "suikei", "temperature", "expected"),
    [
        (0.0, "clear", 20.0, 0),
        (0.0, "cloudy", 20.0, 3),
        (None, "cloudy", 20.0, 3),
        (0.1, "clear", 20.0, 61),  # 10分0.1mm＝1時間0.6mm相当は弱い雨。空より降水を先に見る
        (1.0, None, 20.0, 65),  # 1時間6mm相当は強い雨
        (0.5, None, 0.0, 73),  # 1時間3mm相当。0℃以下は雪
        (0.5, None, 0.1, 63),
        (0.5, None, None, 63),  # 気温が欠測なら雨
        (0.0, None, 20.0, None),  # 降水なしで空が分からなければ判定材料が無い
    ],
)
def test_derive_observed_weather_code(precipitation_10min, suikei, temperature, expected):
    assert derive_observed_weather_code(precipitation_10min, suikei, temperature) == expected


def test_weather_categories_hold_exactly_the_derived_codes():
    """画面は分類に無いコードを出さないので、導くコードはどれも分類に入る。導かないコードと、導くコードを1つも
    持たない分類は、画面に通らないアイコンを残すので置かない。入力は降水量の全ての強さの帯・空の
    区分・気温の雨と雪の両側を掃く。"""
    precipitations = [None, *(step / 100 for step in range(201))]
    derived = {
        derive_observed_weather_code(precipitation, suikei, temperature)
        for precipitation in precipitations
        for suikei in (None, *get_args(SuikeiWeather))
        for temperature in (None, -5.0, 0.0, 0.1, 20.0)
    } - {None}
    categorized = {code for category in WEATHER_CATEGORIES for code in category.codes}
    assert derived
    assert derived <= categorized, sorted(derived - categorized)
    assert categorized <= derived, sorted(categorized - derived)
    assert all(category.codes for category in WEATHER_CATEGORIES)
