from pydantic import BaseModel


class WeatherPeriodOutlook(BaseModel):
    """「今日の見通し」パネルの時間帯別の天気の流れ1コマぶん（改善計画T385フォローアップ、
    ユーザー要望「今日の日中の大まかな天気の流れが分かるものも欲しい」→「朝/午後/夜3区分は
    荒い」→「天気・気温・降水確率をもう少し細かい粒度でスマホ横幅に収まる表現で」の3段階の
    やり取りを経て、2時間おき8コマ・"HH:MM"表記に決着。さらに次のフォローアップで
    「現在時刻を含む時間帯から2時間毎」（固定6時始まりではなく現在時刻基準）へ変更）。
    periodは代表時刻の"HH:MM"文字列（weather_service.py: _period_outlooks参照。現在時刻を
    2時間単位のグリッド（0/2/4...時）へ切り下げた時刻を起点に2時間おきで8コマ生成する。
    朝/午後/夜のような意味づけラベルは持たない——時刻の解釈・「6時」等の表示ラベルへの
    整形はfrontend側が担う）。weather_codeの意味・アイコンへの変換はWeatherConditions.
    weather_codeと同じくfrontend側（weatherCode.ts）に集約する。
    """

    period: str
    weather_code: int | None
    temperature_c: float | None
    precipitation_probability_percent: float | None


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
    # 改善計画T385フォローアップ2（ユーザー要望「夜明け前なら夜明け時間、日没前なら
    # 日没時間をそれぞれ出して」）: 早朝（夜明け前）は遠い日没時刻より近い夜明け時刻の
    # 方が有益なため追加。どちらを表示するかの判定はfrontend側（TodayOutlook.tsx）が
    # 現在時刻とsunrise/sunsetを比較して行う（backendは両方の生値を渡すだけ）。
    sunrise: str | None
    precipitation_probability_max_percent: float | None
    wind_speed_max_ms: float | None
    temperature_max_c: float | None
    temperature_min_c: float | None
    # 改善計画T385フォローアップ（ユーザー指摘「UV指数はスマホからだとどこから見えるのか」）:
    # 現在値のuv_index（WeatherConditions.uv_index）はWeatherPanelの天気アイコンのtitle
    # 属性に格下げしたが、title属性はスマホのタップでは実質見えない。今日のUV最大値を
    # 今日の見通しパネル（タップで確実に開く）へ追加して可視性を確保する。sunset等と同じく
    # get_conditionsのみ埋まる。
    uv_index_max: float | None
    # 改善計画T385フォローアップ（ユーザー要望「今日の日中の大まかな天気の流れが
    # 分かるものも欲しい」、さらに後続フォローアップで「現在時刻を含む時間帯から2時間毎」
    # へ変更）: 現在時刻を2時間グリッドへ切り下げた時刻を起点に2時間おき8コマの天気アイコン・
    # 気温・降水確率の並びで「今日の見通し」パネルへ表示する。dailyではなくhourlyの
    # weather_code/is_day/temperature_2m/precipitation_probabilityから作るため、
    # get_conditionsでのみ埋まり、get_conditions_manyでは常に空リスト（Noneではなく
    # リストなので、フロント側はnullチェック無しで.filter/.mapできる）。
    today_periods: list[WeatherPeriodOutlook]
