import math
from datetime import datetime
from typing import Literal

import numpy as np

from app.domain.strict_model import StrictModel
from app.domain.twilight import Twilight

# 天気コードは観測（アメダスと推計気象分布）からだけ導く。数値予報モデル（MSM）の値から天気を計算して出すことは、
# 気象業務法の予報業務の許可の対象と気象庁の公式の説明が書いているため、しない（docs/architecture/data-sources.md
# 「気象業務法の予報業務許可」節）。コードの分類と表示名はdomain/weather_display.py（WEATHER_CATEGORIES）が持つ。
#: これ未満（mm/h）は「降っていない」。天気コードのほか、「今日」のパネルの降水量の「-」と地図の降水の塗りも同じ境で切る。
PRECIPITATION_MIN_MM = 0.1
_PRECIPITATION_MODERATE_MM = 1.0
_PRECIPITATION_HEAVY_MM = 4.0
_SNOW_MAX_TEMPERATURE_C = 0.0
#: 応答に出す桁。降水量（mm/h）は「今日」のパネル・コマ・地図の格子で揃える。
PRECIPITATION_MM_DECIMALS = 2
WIND_SPEED_MS_DECIMALS = 2
WIND_DIRECTION_DEG_DECIMALS = 1

#: 推計気象分布（天気）の区分。配信元の色からの読み替えは`infrastructure/jma_suikei_client.py`。
SuikeiWeather = Literal["clear", "cloudy", "rain", "rain_or_snow", "snow"]


def derive_observed_weather_code(
    precipitation_10min_mm: float | None, suikei: SuikeiWeather | None, temperature_c: float | None
) -> int | None:
    """アメダスの10分間の実測（降水量・気温）と推計気象分布の区分から WMO天気コードを求める。

    降水があれば10分間量を1時間あたりへ直し、気温で雨（61/63/65）と雪（71/73/75）を、1時間あたりの量で
    強さを分ける。降水が無ければ推計の区分で晴れ（0）/くもり（3）に分け、雨・雪の区分もくもりに数える
    ——降っているかは観測所の実測が決め、推計から読むのは降っていないときの空だけ。日照時間は夜は空によらず0になるため
    晴れ・くもりの材料にしない。霧・雷雨はどちらの項目からも判定できないため返さない。降っておらず空も
    分からなければNone。
    """
    hourly_mm = None if precipitation_10min_mm is None else precipitation_10min_mm * 6
    if hourly_mm is not None and hourly_mm >= PRECIPITATION_MIN_MM:
        snow = temperature_c is not None and temperature_c <= _SNOW_MAX_TEMPERATURE_C
        if hourly_mm < _PRECIPITATION_MODERATE_MM:
            return 71 if snow else 61
        if hourly_mm < _PRECIPITATION_HEAVY_MM:
            return 73 if snow else 63
        return 75 if snow else 65
    if suikei is None:
        return None
    return 0 if suikei == "clear" else 3


class WeatherPeriodOutlook(StrictModel):
    """「今日」のパネルの一定間隔のコマ1つぶん（数値予報モデルの計算値）。

    `period`は代表時刻の"HH:MM"文字列で、朝/午後/夜のような意味づけラベルは持たない
    ——時刻の解釈・表示ラベルへの整形はfrontend側が担う。
    """

    period: str
    temperature_c: float | None
    # 走るかどうかの判断には確率より予想量が直接的なため、mm/hの実量を持つ。
    precipitation_mm: float | None


class TemperatureRange(StrictModel):
    """今日（JST暦日）の残り時間の最低・最高気温（℃）。"""

    min_c: float
    max_c: float


class WeatherConditions(StrictModel):
    precipitation_mm: float | None
    # 「今日」のパネル向けの1日1個の値。早朝（夜明け前）は遠い日没時刻より近い夜明け時刻の方が
    # 有益なため両方持つ。どちらを表示するかの判定はfrontend側が現在時刻と比較して行う。
    twilight: Twilight | None
    precipitation_max_mm: float | None
    wind_speed_max_ms: float | None
    temperature_range: TemperatureRange | None
    # 「今日」のパネルへ並べる一定間隔のコマ。取得失敗時もNoneではなく空リストに
    # なる（フロント側はnullチェック無しで.filter/.mapできる）。
    today_periods: list[WeatherPeriodOutlook]
    # コマの間隔（時間）。画面はコマの並びの見出しにこの間隔を出す。
    today_period_interval_hours: int


_PERIOD_SLOT_COUNT = 8
PERIOD_INTERVAL_HOURS = 2


def today_indices(times: list[datetime]) -> list[int]:
    """時系列（JSTのローカル時刻、先頭が今の正時）のうち、先頭と同じ暦日の時刻の番号。

    MSMは過去の時刻を返さないため、今日の残りの時間になる（朝から見た「今日の最高気温」と
    夕方から見た値は一致しない——これから走る人向けの見通しとして扱う）。
    """
    if not times:
        return []
    today = times[0].date()
    return [index for index, t in enumerate(times) if t.date() == today]


def rounded_or_none(value: float, digits: int) -> float | None:
    """`value`を`digits`桁へ丸めた値。格子の欠損（NaN）はNone。"""
    return None if math.isnan(value) else round(float(value), digits)


def rounded_rows(values: np.ndarray, digits: int) -> list[list[float | None]]:
    """(地点, 時刻)の配列を地点ごとのリストへ丸める。格子の欠損（NaN）はNone。"""
    rounded = np.round(values, digits).astype(object)
    rounded[np.isnan(values)] = None
    return rounded.tolist()


def _complete_values(values: np.ndarray, indices: list[int]) -> np.ndarray | None:
    """`indices`の時刻の値。時刻が無いか、格子の欠損（NaN）を含めばNone。"""
    if not indices:
        return None
    picked = values[indices]
    return None if np.isnan(picked).any() else picked


def daily_max(values: np.ndarray, indices: list[int]) -> float | None:
    """`indices`の時刻の最大値（小数1桁）。時刻が無いか、格子の欠損（NaN）を含めばNone。"""
    picked = _complete_values(values, indices)
    return None if picked is None else round(float(np.max(picked)), 1)


def daily_range(temperature: np.ndarray, indices: list[int]) -> TemperatureRange | None:
    """`indices`の時刻の最低・最高気温。時刻が無いか、格子の欠損（NaN）を含めば両方を欠く。"""
    picked = _complete_values(temperature, indices)
    if picked is None:
        return None
    return TemperatureRange(min_c=round(float(np.min(picked)), 1), max_c=round(float(np.max(picked)), 1))


def period_outlooks(times: list[datetime], temperature: np.ndarray, precipitation: np.ndarray) -> list[WeatherPeriodOutlook]:
    """時系列の先頭（今の正時）を起点に、一定間隔のコマを返す。

    予報の終端に達したらそこで打ち切るため、コマ数はMSMのrunによって変動する。
    """
    return [
        WeatherPeriodOutlook(
            period=times[index].strftime("%H:%M"),
            temperature_c=rounded_or_none(temperature[index], 1),
            precipitation_mm=rounded_or_none(precipitation[index], PRECIPITATION_MM_DECIMALS),
        )
        for index in range(0, min(len(times), _PERIOD_SLOT_COUNT * PERIOD_INTERVAL_HOURS), PERIOD_INTERVAL_HOURS)
    ]
