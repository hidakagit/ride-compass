from pydantic import BaseModel


class WeatherConditions(BaseModel):
    temperature_c: float
    wind_speed_ms: float
    wind_direction_deg: float
    wind_direction_label: str
    precipitation_probability_percent: float | None
    observed_at: str
