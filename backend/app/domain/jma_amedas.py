"""JMAアメダス観測値のドメインモデル。"""

import math

from pydantic import computed_field

from app.domain.strict_model import StrictModel
from app.domain.weather import derive_observed_weather_code

# JMAアメダスのwindDirectionは0=静穏、1〜16が16方位（1=北北東からcode*22.5度で時計回りに
# 進み、16=北[360度=0度]で一周する）という特有の割当のため、domain/geo.pyの8方位
# compass_label（0=北起点）とは別に専用のテーブルを持つ。
_SIXTEEN_POINT_LABELS = [
    "北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
    "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西",
]


def wind_direction_from_jma_code(code: int | None) -> tuple[float, str] | None:
    """JMAアメダスのwindDirectionコード（0=静穏、1〜16=16方位）を(角度, 日本語ラベル)へ
    変換する。角度は0=北・時計回り（`WeatherConditions.wind_direction_deg`と揃える）で、
    code=16は360度ではなく0度（北）に正規化する。0（静穏、風速がほぼ0で方位不定）・None・
    1〜16の範囲外のコードはNoneを返す（範囲外を別の方位として出すと、向かい風と追い風を取り違えさせる）。

    角度とラベルを別々の関数で返さない——どちらも同じ1つのコードの読み替えで、分けると
    「方位がある/ない」の判定と16方位の割当が2箇所に分かれ、片方だけずれても落ちない。
    """
    if code is None or not 1 <= code <= 16:
        return None
    index = code % 16
    return index * 22.5, _SIXTEEN_POINT_LABELS[index]


def apparent_temperature_from_amedas(
    temperature_c: float | None, humidity_percent: float | None, wind_speed_ms: float | None
) -> float | None:
    """気温・湿度・風速から体感温度を算出する。
    JMAは体感温度そのものは提供しない（暑さ指数WBGTのみ）ため、
    オーストラリア気象局(BOM)のApparent Temperature式で自前計算する:

        AT = Ta + 0.33e - 0.70*ws - 4.00
        e  = (rh/100) * 6.105 * exp(17.27*Ta / (237.7+Ta))   # 水蒸気圧[hPa]

    Ta=気温[℃]、rh=相対湿度[%]、ws=風速[m/s]、e=水蒸気圧[hPa]。数値予報モデルが出力する
    体感温度は別の計算式による推定値のため、厳密には一致しない。気温・湿度・風速の
    いずれかがNone（センサー未搭載・欠測）ならNoneを返す。"""
    if temperature_c is None or humidity_percent is None or wind_speed_ms is None:
        return None
    vapor_pressure = (humidity_percent / 100) * 6.105 * math.exp(17.27 * temperature_c / (237.7 + temperature_c))
    return temperature_c + 0.33 * vapor_pressure - 0.70 * wind_speed_ms - 4.00


class AmedasObservation(StrictModel):
    """最寄りアメダス観測所の直近観測値。

    突風はJMAアメダスのリアルタイム観測値レスポンスがどの観測所についても持たないため、
    このモデルに項目が無い。
    """

    station_id: str
    station_name: str
    latitude: float
    longitude: float
    observed_at: str
    temperature_c: float | None
    apparent_temperature_c: float | None
    wind_speed_ms: float | None
    wind_direction_deg: float | None
    wind_direction_label: str | None
    precipitation_10min_mm: float | None
    # 直近10分間の日照時間（分、0〜10）。降水量と組み合わせて`weather_code`を決める。
    sunshine_10min_minutes: float | None
    # 最寄り観測所ではなくリクエストのlatitude/longitudeそのものに対する、当日（JST）の値。
    # 外部には問い合わせず、domain/twilight.py: sunrise_sunset_jstのローカル天文計算で求める。
    sunrise: str | None
    sunset: str | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def weather_code(self) -> int | None:
        """実測から導いたWMO天気コード（`weather.derive_observed_weather_code`）。保存した観測値からいつでも
        導けるため、Redisには持たない。"""
        return derive_observed_weather_code(
            self.precipitation_10min_mm, self.sunshine_10min_minutes, self.temperature_c
        )
