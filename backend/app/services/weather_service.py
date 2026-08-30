from datetime import datetime, timedelta

import httpx

from app.domain.geo import compass_label
from app.domain.route import Coordinates
from app.domain.weather import WeatherConditions, WeatherPeriodOutlook
from app.domain.wind_grid import WindGridPoint
from app.infrastructure.weather_client import WeatherClient


class WeatherService:
    """地点の天候を取得する。

    `get_conditions`は常に現在の気象を返す（呼び出し元は天気APIエンドポイント・
    RoadGraphEngineの起点判定のみで、いずれも過去/未来時刻を渡さない）。
    複数地点・複数時刻をまとめて解決する`get_conditions_many`/`prefetch`は
    openrouteserviceエンジン専用のWindServiceが唯一の呼び出し元だったため、
    改善計画T462でWindServiceを削除した結果、現在は呼び出し元が無い
    （削除は別タスクへ切り出し済み）。
    """

    def __init__(self, client: WeatherClient, http_client: httpx.AsyncClient):
        self._client = client
        self._http_client = http_client

    async def get_conditions(self, point: Coordinates) -> WeatherConditions | None:
        data = await self._client.get_forecast(self._http_client, point)
        if data is None:
            return None
        return self._conditions_from_data(data, None)

    async def prefetch(self, points: list[Coordinates]) -> None:
        """複数地点の予報をまとめて1回のOpen-Meteo呼び出しでキャッシュへ先読みする（結果は使わない）。

        候補（方位）ごとに`get_conditions_many`を並列呼び出しすると、候補数ぶん
        （最大8本）のOpen-Meteoリクエストがほぼ同時に発火してしまう（本番のOpen-Meteo
        429常態化の一因）。呼び出し元が候補間で点を合流させてこれを先に呼んでおけば、
        `get_forecast_many`のTTLキャッシュが温まり、後続の候補ごとの呼び出しはキャッシュ
        ヒットしてHTTPを発生させない（現在は呼び出し元が無い、クラスdocstring参照）。
        """
        await self._client.get_forecast_many(self._http_client, points)

    async def get_conditions_many(
        self, points: list[Coordinates], times: list[datetime | None]
    ) -> list[WeatherConditions | None]:
        """複数地点の天候を、可能な限り1回のOpen-Meteo呼び出しでまとめて取得する
        （現在は呼び出し元が無い、クラスdocstring参照）。

        地点ごとの時刻（times[i]）が異なっていても、予報自体は地点ごとにforecast_days分の
        hourly系列をまとめて取得しているため、取得後にそれぞれ最も近い時刻を選ぶだけでよい
        （get_conditionsと同じ選択ロジックを_conditions_from_dataへ切り出して共有する）。
        """
        forecasts = await self._client.get_forecast_many(self._http_client, points)
        results = []
        for point, at in zip(points, times):
            data = forecasts.get(self._client.cache_key(point))
            results.append(None if data is None else self._conditions_from_data(data, at))
        return results

    async def get_wind_grid(self, points: list[Coordinates]) -> tuple[list[str], list[WindGridPoint | None]]:
        """複数地点の時間別風向・風速・降水量をまとめて取得する（改善計画T178フォローアップ、
        T183で降水（+60分以降の延長予報）を追加）。get_conditions_manyと違い特定時刻1点へ
        収束させず、hourly配列全体（forecast_days=2分）をそのまま返す（domain/wind_grid.py:
        WindGridPointのdocstring参照）。

        時刻配列は全地点で共通のため（同じforecast_days・timezoneで一括取得、
        WindGridResponseのdocstring参照）、戻り値の先頭要素として1本だけ返す
        （改善計画T203、応答サイズ削減）。最初に見つかった有効な地点のtimesを採用する
        （全地点失敗時は空リストになる）。"""
        forecasts = await self._client.get_forecast_many(self._http_client, points)
        times: list[str] = []
        results: list[WindGridPoint | None] = []
        for point in points:
            data = forecasts.get(self._client.cache_key(point))
            parsed = None if data is None else self._wind_grid_point_from_data(point, data)
            if parsed is None:
                results.append(None)
                continue
            point_times, wind_grid_point = parsed
            if not times:
                times = point_times
            results.append(wind_grid_point)
        return times, results

    @staticmethod
    def _wind_grid_point_from_data(point: Coordinates, data: dict) -> tuple[list[str], WindGridPoint] | None:
        hourly = data.get("hourly")
        if not hourly or not hourly.get("time"):
            return None
        times = hourly.get("time")
        speeds = hourly.get("wind_speed_10m")
        directions = hourly.get("wind_direction_10m")
        precipitation = hourly.get("precipitation")
        if (
            not speeds
            or not directions
            or not precipitation
            or len(speeds) != len(times)
            or len(directions) != len(times)
            or len(precipitation) != len(times)
        ):
            return None
        return times, WindGridPoint(
            latitude=point.latitude,
            longitude=point.longitude,
            wind_speed_ms=speeds,
            wind_direction_deg=directions,
            precipitation_mm=precipitation,
        )

    def _conditions_from_data(self, data: dict, at: datetime | None) -> WeatherConditions | None:
        hourly = data.get("hourly")
        if not hourly or not hourly.get("time"):
            return None

        # Open-Meteoが200を返してもJSON形状が期待と食い違う（一時的なAPI障害・スキーマ変更等）
        # 場合、直下の添字アクセスがKeyError/IndexErrorを送出しうる。ここで捕捉せず伝播させると
        # 「取得失敗は握りつぶしてnull」という他の外部API（標高・路面）と同じ方針から外れ、
        # 8方位分の候補が確定済みでも1件の異常レスポンスでルート生成全体が500になってしまう
        # （route_generator.pyのgatherはtrace_loopのみreturn_exceptions=True保護対象）。
        try:
            if at is None:
                current = data.get("current")
                if not current:
                    return None
                observed_at = current["time"]
                temperature = current["temperature_2m"]
                wind_speed = current["wind_speed_10m"]
                wind_direction = current["wind_direction_10m"]
                # 突風・体感温度・UV指数・降水量は「current」自体に含めて取得済み（改善計画T172、
                # weather_client.py参照）のため、precipitation_probabilityと違いhourlyへの
                # 近傍探索は不要。current側に無い場合（プロパティ欠落）はNoneへ倒す。
                apparent_temperature = current.get("apparent_temperature")
                wind_gusts = current.get("wind_gusts_10m")
                precipitation = current.get("precipitation")
                uv_index = current.get("uv_index")
                weather_code = current.get("weather_code")
                is_day = current.get("is_day")
                precipitation_probability = self._hourly_value_near(hourly, observed_at, "precipitation_probability")
                # 改善計画T385: 「今日の見通し」（daily、forecast_days=2のindex0=今日）。
                # get_conditions（この分岐）でのみ取得する（下のelse分岐＝
                # get_conditions_manyはdailyを取得していないため常にNone）。
                daily = data.get("daily") or {}
                sunrise = self._daily_index_value(daily, "sunrise", 0)
                sunset = self._daily_index_value(daily, "sunset", 0)
                precipitation_probability_max = self._daily_index_value(daily, "precipitation_probability_max", 0)
                wind_speed_max = self._daily_index_value(daily, "wind_speed_10m_max", 0)
                temperature_max = self._daily_index_value(daily, "temperature_2m_max", 0)
                temperature_min = self._daily_index_value(daily, "temperature_2m_min", 0)
                uv_index_max = self._daily_index_value(daily, "uv_index_max", 0)
                # 改善計画T385フォローアップ（ユーザー要望「今日の日中の大まかな天気の
                # 流れが分かるものも欲しい」）: dailyの日次集約値だけでは「日中いつ頃
                # 崩れるか」が分からないため、hourlyから2時間おき8コマの代表時刻を抜き出す
                # （_period_outlooks参照）。
                today_periods = self._period_outlooks(hourly, observed_at)
            else:
                target = at.strftime("%Y-%m-%dT%H:%M")
                if not self._within_hourly_range(hourly["time"], target):
                    # 取得済みhourly（forecast_days=2分）の範囲外。範囲内の最も近い時刻を
                    # 代用すると「遠い未来/過去の天候」として誤って提示することになるため、
                    # 範囲外は素直にNoneを返す（他の欠損時と同じ方針）。
                    return None
                index = self._nearest_hourly_index(hourly["time"], target)
                if index is None:
                    return None
                observed_at = hourly["time"][index]
                temperature = hourly["temperature_2m"][index]
                wind_speed = hourly["wind_speed_10m"][index]
                wind_direction = hourly["wind_direction_10m"][index]
                precipitation_probability = hourly["precipitation_probability"][index]
                apparent_temperature = self._hourly_index_value(hourly, "apparent_temperature", index)
                wind_gusts = self._hourly_index_value(hourly, "wind_gusts_10m", index)
                precipitation = self._hourly_index_value(hourly, "precipitation", index)
                uv_index = self._hourly_index_value(hourly, "uv_index", index)
                # 改善計画T385: この分岐（get_conditions_many、ルート上の各点・未来時刻）は
                # weather_code/is_day・dailyのいずれも取得していないため常にNoneにする
                # （天気アイコン・今日の見通しはルート評価には使わない表示専用の情報）。
                weather_code = None
                is_day = None
                sunrise = None
                sunset = None
                precipitation_probability_max = None
                wind_speed_max = None
                temperature_max = None
                temperature_min = None
                uv_index_max = None
                today_periods = []
        except (KeyError, IndexError, TypeError):
            return None

        return WeatherConditions(
            temperature_c=temperature,
            apparent_temperature_c=apparent_temperature,
            wind_speed_ms=wind_speed,
            wind_direction_deg=wind_direction,
            wind_direction_label=compass_label(wind_direction),
            wind_gusts_ms=wind_gusts,
            precipitation_probability_percent=precipitation_probability,
            precipitation_mm=precipitation,
            uv_index=uv_index,
            observed_at=observed_at,
            weather_code=weather_code,
            is_day=is_day,
            sunrise=sunrise,
            sunset=sunset,
            precipitation_probability_max_percent=precipitation_probability_max,
            wind_speed_max_ms=wind_speed_max,
            temperature_max_c=temperature_max,
            temperature_min_c=temperature_min,
            uv_index_max=uv_index_max,
            today_periods=today_periods,
        )

    @staticmethod
    def _within_hourly_range(times: list[str], target: str) -> bool:
        if not times:
            return False
        target_dt = datetime.fromisoformat(target)
        parsed = [datetime.fromisoformat(t) for t in times]
        return min(parsed) <= target_dt <= max(parsed)

    @staticmethod
    def _nearest_hourly_index(times: list[str], target: str) -> int | None:
        if not times:
            return None
        target_dt = datetime.fromisoformat(target)
        diffs = [abs((datetime.fromisoformat(t) - target_dt).total_seconds()) for t in times]
        return diffs.index(min(diffs))

    @classmethod
    def _hourly_value_near(cls, hourly: dict, target_time: str, field: str):
        index = cls._nearest_hourly_index(hourly.get("time", []), target_time)
        values = hourly.get(field)
        if index is None or not values or index >= len(values):
            return None
        return values[index]

    @staticmethod
    def _hourly_index_value(hourly: dict, field: str, index: int):
        """hourly配列から既知のindexで値を引く（改善計画T172）。突風・体感温度・UV指数・
        降水量はatが指す時刻のindexが既にprecipitation_probabilityの取得で確定しているため、
        _hourly_value_nearのように改めて最近傍時刻を探し直す必要がない。フィールド自体が
        存在しない/配列が短い場合はNoneへ倒す（新規追加パラメータのため既存キャッシュ済み
        レスポンスに含まれないケースを想定）。"""
        values = hourly.get(field)
        if not values or index >= len(values):
            return None
        return values[index]

    @staticmethod
    def _daily_index_value(daily: dict, field: str, index: int):
        """daily配列から既知のindexで値を引く（改善計画T385、_hourly_index_valueのdaily版）。
        forecast_days=2・timezone=Asia/Tokyoのindex 0が「今日」に対応する。"""
        values = daily.get(field)
        if not values or index >= len(values):
            return None
        return values[index]

    # 改善計画T385フォローアップ: 「今日の見通し」パネルの時間帯別コマ。
    # 当初「朝/午後/夜」3コマ→ユーザー指摘「少し荒い」→「天気・気温・降水確率をもう少し
    # 細かい粒度でスマホ横幅に収まる表現で」→固定6時始まり8コマ→後続フォローアップ
    # 「現在時刻を含む時間帯（例：今7時なら6時の天気）から2時間毎」を経て、現在時刻を
    # 2時間グリッド（0/2/4...時）へ切り下げた時刻を起点に2時間おき8コマ・代表時刻
    # そのままの単純採用に決着。severity（重大度）で「その区間で最も荒れた時刻」を選ぶ
    # 方式ではなく代表1時刻をそのまま使うのは、重大度ランキングがweather_code→
    # アイコン判定と同種の「意味づけ」であり、frontend/weatherCode.tsへ集約する既存方針
    # （backendは生の値を素通しするだけ）に合わせたため。既存の_nearest_hourly_index/
    # _hourly_index_valueをそのまま再利用できる利点もある。
    _PERIOD_SLOT_COUNT = 8
    _PERIOD_INTERVAL_HOURS = 2

    @classmethod
    def _period_outlooks(cls, hourly: dict, observed_at: str) -> list[WeatherPeriodOutlook]:
        now = datetime.fromisoformat(observed_at)
        start_hour = now.hour - (now.hour % cls._PERIOD_INTERVAL_HOURS)
        start = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        times = hourly.get("time") or []
        results = []
        for i in range(cls._PERIOD_SLOT_COUNT):
            slot_time = start + timedelta(hours=cls._PERIOD_INTERVAL_HOURS * i)
            target = slot_time.strftime("%Y-%m-%dT%H:%M")
            index = cls._nearest_hourly_index(times, target) if cls._within_hourly_range(times, target) else None
            weather_code = None if index is None else cls._hourly_index_value(hourly, "weather_code", index)
            temperature = None if index is None else cls._hourly_index_value(hourly, "temperature_2m", index)
            precipitation_probability = (
                None if index is None else cls._hourly_index_value(hourly, "precipitation_probability", index)
            )
            results.append(
                WeatherPeriodOutlook(
                    period=slot_time.strftime("%H:%M"),
                    weather_code=weather_code,
                    temperature_c=temperature,
                    precipitation_probability_percent=precipitation_probability,
                )
            )
        return results
