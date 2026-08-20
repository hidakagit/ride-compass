from pydantic import BaseModel


class WeatherConditions(BaseModel):
    temperature_c: float
    # 体感温度（改善計画T172）。気温より運動強度・服装判断に直結するため気温と併記する。
    apparent_temperature_c: float | None
    wind_speed_ms: float
    wind_direction_deg: float
    wind_direction_label: str
    # 突風（改善計画T172）。橋上・河川敷等の横風リスクは平均風速より突風が効く。
    wind_gusts_ms: float | None
    precipitation_probability_percent: float | None
    # 降水量mm/h（改善計画T172）。確率だけでは小雨か土砂降りか分からないため併記する。
    precipitation_mm: float | None
    uv_index: float | None
    observed_at: str
