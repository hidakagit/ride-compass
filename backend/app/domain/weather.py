from pydantic import BaseModel


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
    precipitation_probability_percent: float | None


class WeatherConditions(BaseModel):
    temperature_c: float
    # 気温より運動強度・服装判断に直結するため気温と併記する。
    apparent_temperature_c: float | None
    wind_speed_ms: float
    wind_direction_deg: float
    wind_direction_label: str
    # 橋上・河川敷等の横風リスクは平均風速より突風が効くため気温と別に持つ。
    wind_gusts_ms: float | None
    precipitation_probability_percent: float | None
    # 確率だけでは小雨か土砂降りか分からないためmm/hの実量も併記する。
    precipitation_mm: float | None
    uv_index: float | None
    observed_at: str
    # 天気アイコン化用（WMO天気コード・昼夜フラグ）。weather_codeの値の
    # 意味・アイコンへの変換はfrontend/src/components/WeatherPanel/weatherCode.tsに
    # 集約する（バックエンドは生のコードを素通しするだけで判定ロジックを持たない）。
    weather_code: int | None
    is_day: int | None
    # 「今日の見通し」パネル向けの日次見通し4項目。current/hourlyの瞬間値と
    # 違い1日1個の値（Open-Meteoのdailyパラメータ、weather_client.py参照）。
    sunset: str | None
    # 早朝（夜明け前）は遠い日没時刻より近い夜明け時刻の方が有益なため追加。どちらを
    # 表示するかの判定はfrontend側（TodayOutlook.tsx）が現在時刻とsunrise/sunsetを
    # 比較して行う（backendは両方の生値を渡すだけ）。
    sunrise: str | None
    precipitation_probability_max_percent: float | None
    wind_speed_max_ms: float | None
    temperature_max_c: float | None
    temperature_min_c: float | None
    # 現在値のuv_index（WeatherConditions.uv_index）はWeatherPanelの天気アイコンのtitle
    # 属性に格下げしてあるが、title属性はスマホのタップでは実質見えない。今日のUV最大値を
    # 今日の見通しパネル（タップで確実に開く）へ追加して可視性を確保する。
    uv_index_max: float | None
    # 現在時刻を2時間グリッドへ切り下げた時刻を起点に2時間おき8コマの天気アイコン・
    # 気温・降水確率の並びで「今日の見通し」パネルへ表示する。取得失敗時もNoneではなく
    # 空リストになる（フロント側はnullチェック無しで.filter/.mapできる）。
    today_periods: list[WeatherPeriodOutlook]
