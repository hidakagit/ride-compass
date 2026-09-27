from app.domain.strict_model import StrictModel

# 天気コードは観測（アメダス）からだけ導く。数値予報モデル（MSM）の値から天気を計算して出すことは、気象業務法の
# 予報業務の許可の対象と気象庁の公式の説明が書いているため、しない（docs/architecture/data-sources.md「気象業務法の
# 予報業務許可」節）。コードの分類と表示名はdomain/weather_display.py（WEATHER_CATEGORIES）が持つ。
#: これ未満（mm/h）は「降っていない」。天気コードのほか、「今日」のパネルの降水量の「-」と地図の降水の塗りも同じ境で切る。
PRECIPITATION_MIN_MM = 0.1
_PRECIPITATION_MODERATE_MM = 1.0
_PRECIPITATION_HEAVY_MM = 4.0
_SNOW_MAX_TEMPERATURE_C = 0.0


def derive_observed_weather_code(
    precipitation_10min_mm: float | None, sunshine_10min_minutes: float | None, temperature_c: float | None
) -> int | None:
    """アメダスの10分間の実測（降水量・日照時間・気温）からWMO天気コードを求める。

    降水があれば10分間量を1時間あたりへ直し、気温で雨（61/63/65）と雪（71/73/75）を、1時間あたりの量で
    強さを分ける。降水が無ければ日照の有無だけで晴れ（0）/くもり（3）に分け、霧・雷雨は実測の項目からは
    判定できないため返さない。降水量も日照時間も無ければNone。
    """
    hourly_mm = None if precipitation_10min_mm is None else precipitation_10min_mm * 6
    if hourly_mm is not None and hourly_mm >= PRECIPITATION_MIN_MM:
        snow = temperature_c is not None and temperature_c <= _SNOW_MAX_TEMPERATURE_C
        if hourly_mm < _PRECIPITATION_MODERATE_MM:
            return 71 if snow else 61
        if hourly_mm < _PRECIPITATION_HEAVY_MM:
            return 73 if snow else 63
        return 75 if snow else 65
    if sunshine_10min_minutes is None:
        return None
    return 0 if sunshine_10min_minutes > 0 else 3


class WeatherPeriodOutlook(StrictModel):
    """「今日」のパネルの2時間おきのコマ1つぶん（数値予報モデルの計算値）。

    `period`は代表時刻の"HH:MM"文字列で、朝/午後/夜のような意味づけラベルは持たない
    ——時刻の解釈・表示ラベルへの整形はfrontend側が担う。
    """

    period: str
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
    # 「今日」のパネル向けの1日1個の値。時刻別の値と違い1日1個。
    sunset: str | None
    # 早朝（夜明け前）は遠い日没時刻より近い夜明け時刻の方が有益なため両方持つ。どちらを
    # 表示するかの判定はfrontend側が現在時刻とsunrise/sunsetを比較して行う。
    sunrise: str | None
    precipitation_max_mm: float | None
    wind_speed_max_ms: float | None
    temperature_max_c: float | None
    temperature_min_c: float | None
    # 「今日」のパネルへ並べる2時間おきのコマ。取得失敗時もNoneではなく空リストに
    # なる（フロント側はnullチェック無しで.filter/.mapできる）。
    today_periods: list[WeatherPeriodOutlook]
