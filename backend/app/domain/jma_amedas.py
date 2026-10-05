"""JMAアメダス観測値のドメインモデル。"""

import math

from app.domain.geo import SIXTEEN_POINT_LABELS
from app.domain.strict_model import StrictModel
from app.domain.twilight import Twilight


class WindDirection(StrictModel):
    """風の来る向き。角度は0=北・時計回り。"""

    deg: float
    label: str


def wind_direction_from_jma_code(code: int | None) -> WindDirection | None:
    """JMAアメダスのwindDirectionコード（0=静穏、1〜16=16方位）を角度と日本語ラベルへ
    変換する。角度は0=北・時計回り（`wind.py: DepartureWind.direction_deg`と揃える）で、
    code=16は360度ではなく0度（北）に正規化する。0（静穏、風速がほぼ0で方位不定）・None・
    1〜16の範囲外のコードはNoneを返す（範囲外を別の方位として出すと、向かい風と追い風を取り違えさせる）。

    角度とラベルを別々の関数で返さない——どちらも同じ1つのコードの読み替えで、分けると
    「方位がある/ない」の判定と16方位の割当が2箇所に分かれ、片方だけずれても落ちない。
    """
    # JMA特有なのは番号の割当だけ（1=北北東からcode*22.5度で時計回りに進み、16=北で一周する）。
    # 16で割った余りが北を0とした16方位の番号になり、呼び名は共通の並びから引く。
    if code is None or not 1 <= code <= 16:
        return None
    index = code % 16
    return WindDirection(deg=index * 22.5, label=SIXTEEN_POINT_LABELS[index])


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

    temperature_c: float | None
    apparent_temperature_c: float | None
    wind_speed_ms: float | None
    #: 静穏（方位不定）・欠測ならNone。
    wind_direction: WindDirection | None
    precipitation_10min_mm: float | None
    # 最寄り観測所ではなくリクエストのlatitude/longitudeそのものに対する、当日（JST）の値。
    # 外部には問い合わせず、domain/twilight.py: sunrise_sunset_jstのローカル天文計算で求める。
    twilight: Twilight | None
    # WMO天気コード（`weather.derive_observed_weather_code`）。晴れ・くもりはリクエストの地点の推計気象分布で
    # 決まるため、twilightと同じく応答のたびに入れ、Redisには持たない。
    weather_code: int | None
