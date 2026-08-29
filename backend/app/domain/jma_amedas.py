"""JMAアメダス観測値のドメインモデル（改善計画T387）。"""

import math

from pydantic import BaseModel

# JMAアメダスのwindDirectionは0=静穏、1〜16が16方位（1=北北東からcode*22.5度で時計回りに
# 進み、16=北[360度=0度]で一周する）という特有の割当のため、domain/geo.pyの8方位
# compass_label（0=北起点）とは別に専用のテーブルを持つ。
_SIXTEEN_POINT_LABELS = [
    "北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
    "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西",
]


def wind_direction_label_from_jma_code(code: int | None) -> str | None:
    """JMAアメダスのwindDirectionコード（0=静穏、1〜16=16方位）を日本語ラベルへ変換する。
    0（静穏、風速がほぼ0で方位不定）およびNoneはNoneを返す。"""
    if not code:
        return None
    index = code % 16
    return _SIXTEEN_POINT_LABELS[index]


def wind_direction_degrees_from_jma_code(code: int | None) -> float | None:
    """JMAアメダスのwindDirectionコードを角度（0=北、時計回り）へ変換する（改善計画T387
    フォローアップ、/api/weatherの現在値をアメダス優先にする際にWeatherConditions.
    wind_direction_deg[度]と揃えるために追加）。code=16は360度ではなく0度（北）に正規化する。
    """
    if not code:
        return None
    return (code % 16) * 22.5


def apparent_temperature_from_amedas(
    temperature_c: float | None, humidity_percent: float | None, wind_speed_ms: float | None
) -> float | None:
    """気温・湿度・風速から体感温度を算出する（改善計画T387フォローアップ、ユーザー指示
    2026-08-29）。JMAは体感温度そのものは提供しない（暑さ指数WBGTのみ）ため、
    オーストラリア気象局(BOM)のApparent Temperature式で自前計算する:

        AT = Ta + 0.33e - 0.70*ws - 4.00
        e  = (rh/100) * 6.105 * exp(17.27*Ta / (237.7+Ta))   # 水蒸気圧[hPa]

    Ta=気温[℃]、rh=相対湿度[%]、ws=風速[m/s]、e=水蒸気圧[hPa]。新規外部依存を要しない
    公知の標準式で、Open-Meteoのapparent_temperature（別の計算式によるモデル推定値）とは
    厳密には一致しない近似値になる。3項目のいずれかがNone（センサー未搭載・欠測）なら
    Noneを返す。"""
    if temperature_c is None or humidity_percent is None or wind_speed_ms is None:
        return None
    vapor_pressure = (humidity_percent / 100) * 6.105 * math.exp(17.27 * temperature_c / (237.7 + temperature_c))
    return temperature_c + 0.33 * vapor_pressure - 0.70 * wind_speed_ms - 4.00


class AmedasObservation(BaseModel):
    """最寄りアメダス観測所の直近観測値。"""

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
