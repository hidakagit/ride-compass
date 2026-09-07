from pydantic import BaseModel

# 天気コードの導出しきい値。MSMは天気そのものを配信しないため、降水量・雲量・気温から
# WMO天気コード相当へ落とす（値の意味・アイコンへの変換はfrontend側weatherCode.tsに集約
# する方針は変えず、backendは数値コードだけを返す）。
_PRECIPITATION_MIN_MM = 0.1
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

    frontendのアイコンは6カテゴリ（快晴/くもり/霧/雨/雪/雷雨）へ丸めて表示するため、
    降水の強度3段階と雲量4段階が区別できれば足りる。霧・雷雨はMSMの配信変数からは
    判定できないため返さない。
    """
    if precipitation_mm is not None and precipitation_mm >= _PRECIPITATION_MIN_MM:
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


class WeatherPeriodOutlook(BaseModel):
    """「今日の見通し」パネルの時間帯別の天気の流れ1コマぶん。periodは代表時刻の
    "HH:MM"文字列（weather_service.py: _period_outlooks参照。現在時刻を2時間単位の
    グリッド（0/2/4...時）へ切り下げた時刻を起点に2時間おきで8コマ生成する。朝/午後/夜
    のような意味づけラベルは持たない——時刻の解釈・「6時」等の表示ラベルへの整形は
    frontend側が担う）。weather_codeの意味・アイコンへの変換はWeatherConditions.
    weather_codeと同じくfrontend側（weatherCode.ts）に集約する。
    """

    period: str
    weather_code: int | None
    temperature_c: float | None
    # 走るかどうかの判断には確率より予想量が直接的なため、mm/hの実量を持つ。
    precipitation_mm: float | None


class WeatherConditions(BaseModel):
    temperature_c: float | None
    wind_speed_ms: float
    wind_direction_deg: float
    wind_direction_label: str
    precipitation_mm: float | None
    observed_at: str
    # 天気アイコン化用（WMO天気コード・昼夜フラグ）。weather_codeの値の
    # 意味・アイコンへの変換はfrontend/src/components/WeatherPanel/weatherCode.tsに
    # 集約する（バックエンドは数値コードを返すだけで表示上の判定を持たない）。
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
    # 現在時刻を2時間グリッドへ切り下げた時刻を起点に2時間おき8コマの天気アイコン・
    # 気温・降水量の並びで「今日の見通し」パネルへ表示する。取得失敗時もNoneではなく
    # 空リストになる（フロント側はnullチェック無しで.filter/.mapできる）。
    today_periods: list[WeatherPeriodOutlook]
