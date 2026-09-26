from app.domain.strict_model import StrictModel

# 天気コードの導出しきい値。MSMは天気そのものを配信しないため、降水量・雲量・気温から
# WMO天気コード相当へ落とす。コードの分類と表示名はdomain/weather_display.py（WEATHER_CATEGORIES）が持つ。
#: これ未満（mm/h）は「降っていない」。天気コードのほか、画面の予想降水量の「-」と地図の降水の塗りも同じ境で切る。
PRECIPITATION_MIN_MM = 0.1
_PRECIPITATION_MODERATE_MM = 1.0
_PRECIPITATION_HEAVY_MM = 4.0
_SNOW_MAX_TEMPERATURE_C = 0.0
_CLOUD_CLEAR_PERCENT = 20.0
_CLOUD_MOSTLY_CLEAR_PERCENT = 50.0
_CLOUD_OVERCAST_PERCENT = 85.0


def derive_weather_code(
    precipitation_mm: float | None, cloud_cover_percent: float | None, temperature_c: float | None
) -> int | None:
    """降水量・雲量・気温からWMO天気コード（0/1/2/3・61/63/65・71/73/75）を求める。

    画面はコードを天気の分類（`weather_display.WEATHER_CATEGORIES`）へ丸めて出すので、降水の強度と
    雲量の段が区別できれば足りる。霧・雷雨はMSMの配信変数からは判定できないため返さない。
    """
    if precipitation_mm is not None and precipitation_mm >= PRECIPITATION_MIN_MM:
        snow = temperature_c is not None and temperature_c <= _SNOW_MAX_TEMPERATURE_C
        if precipitation_mm < _PRECIPITATION_MODERATE_MM:
            return 71 if snow else 61
        if precipitation_mm < _PRECIPITATION_HEAVY_MM:
            return 73 if snow else 63
        return 75 if snow else 65
    if cloud_cover_percent is None:
        return None
    if cloud_cover_percent < _CLOUD_CLEAR_PERCENT:
        return 0
    if cloud_cover_percent < _CLOUD_MOSTLY_CLEAR_PERCENT:
        return 1
    if cloud_cover_percent < _CLOUD_OVERCAST_PERCENT:
        return 2
    return 3


def derive_observed_weather_code(
    precipitation_10min_mm: float | None, sunshine_10min_minutes: float | None, temperature_c: float | None
) -> int | None:
    """アメダスの10分間の実測（降水量・日照時間・気温）からWMO天気コードを求める。

    降水があれば10分間量を1時間あたりへ直して`derive_weather_code`と同じ段で雨/雪と強さを決める
    ——雨と雪の境を予報と観測で1つにするため。降水が無ければ日照の有無だけで晴れ（0）/くもり（3）に
    分け、霧・雷雨は実測の項目からは判定できないため返さない。降水量も日照時間も無ければNone。
    """
    if precipitation_10min_mm is not None and precipitation_10min_mm > 0:
        return derive_weather_code(precipitation_10min_mm * 6, None, temperature_c)
    if sunshine_10min_minutes is None:
        return None
    return 0 if sunshine_10min_minutes > 0 else 3


class WeatherPeriodOutlook(StrictModel):
    """「今日の見通し」パネルの時間帯別の天気の流れ1コマぶん。

    `period`は代表時刻の"HH:MM"文字列で、朝/午後/夜のような意味づけラベルは持たない
    ——時刻の解釈・表示ラベルへの整形はfrontend側が担う。
    """

    period: str
    weather_code: int | None
    temperature_c: float | None
    # 走るかどうかの判断には確率より予想量が直接的なため、mm/hの実量を持つ。
    precipitation_mm: float | None


class WeatherConditions(StrictModel):
    temperature_c: float | None
    wind_speed_ms: float
    wind_direction_deg: float
    wind_direction_label: str
    precipitation_mm: float | None
    observed_at: str
    # 天気アイコン化用（WMO天気コード・昼夜フラグ）。
    weather_code: int | None
    is_day: int | None
    # 「今日の見通し」パネル向けの日次見通し。時刻別の値と違い1日1個の値。
    sunset: str | None
    # 早朝（夜明け前）は遠い日没時刻より近い夜明け時刻の方が有益なため両方持つ。どちらを
    # 表示するかの判定はfrontend側が現在時刻とsunrise/sunsetを比較して行う。
    sunrise: str | None
    precipitation_max_mm: float | None
    wind_speed_max_ms: float | None
    temperature_max_c: float | None
    temperature_min_c: float | None
    # 「今日の見通し」パネルへ並べる時間帯別の予報。取得失敗時もNoneではなく空リストに
    # なる（フロント側はnullチェック無しで.filter/.mapできる）。
    today_periods: list[WeatherPeriodOutlook]
