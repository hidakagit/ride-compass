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
    # 改善計画T385: 天気アイコン化用（WMO天気コード・昼夜フラグ）。get_conditionsのみ
    # 埋まる（get_conditions_manyはルート評価用でアイコン表示に使わないためNone、
    # weather_service.py参照）。weather_codeの値の意味・アイコンへの変換は
    # frontend/src/components/WeatherPanel/weatherCode.tsに集約する
    # （バックエンドは生のコードを素通しするだけで判定ロジックを持たない）。
    weather_code: int | None
    is_day: int | None
    # 改善計画T385: 「今日の見通し」パネル向けの日次見通し4項目。current/hourlyの瞬間値と
    # 違い1日1個の値（Open-Meteoのdailyパラメータ、weather_client.py参照）のため、
    # get_conditions（現在地点の実況、`at is None`）のときだけ埋まる。
    # get_conditions_many（ルート上の各点・未来時刻向け、WindService用）はdailyを
    # 取得していないため常にNoneになる（今日の見通しはルート評価には使わない情報のため）。
    sunset: str | None
    precipitation_probability_max_percent: float | None
    wind_speed_max_ms: float | None
    temperature_max_c: float | None
    temperature_min_c: float | None
