"""JMAアメダス観測値サービス。

最寄りのアメダス観測所を解決し、直近の気温・風向風速・10分間降水量と天気コードを返す。

**観測値の取得は定期バッチが担い、リクエスト経路（`get_nearest_observation`）は観測値をRedisから読むだけに
する**。JMAの観測値エンドポイントは1地点だけを絞り込めず、常に全国ぶんを1回のレスポンスで
返すため——「リクエストされた1地点だけ」を都度取る形にすると、その不可分な取得コストを
払いながら近隣ユーザーのリクエストはキャッシュヒットせず、同じ全国データを取り直し続ける。
天気コードの晴れ・くもりだけは、リクエストの地点の推計気象分布（天気）のタイルから読む（地図の気象庁タイルと
同じキャッシュを通る。`infrastructure/jma_suikei_client.py`）。

観測値は短命でPostGISへは書かず、Redisで完結させる（置き場は`infrastructure/jma_amedas_store.py`）。
雨の材料（`domain/rain.py`）の元になる毎正時の1時間雨量の履歴も同じバッチが取り、Redisに持つ
——失うと気象庁の過去の地図JSONを全本取り直すことになる。
"""

import logging
from datetime import datetime, timedelta

import httpx
import numpy as np
from cachetools import TTLCache

from app.domain.rain import RAIN_HISTORY_HOURS, StationRainMaterials, is_rain_history_current, rain_material_values
from app.domain.time_zone import JST
from app.domain.geo import nearest_point_index
from app.domain.jma_amedas import (
    AmedasObservation,
    apparent_temperature_from_amedas,
    wind_direction_from_jma_code,
)
from app.domain.jma_suikei import sky_from_color
from app.domain.route import Coordinates
from app.domain.twilight import sunrise_sunset_jst
from app.domain.weather import derive_observed_weather_code
from app.infrastructure import jma_amedas_client, jma_amedas_store, jma_suikei_client
from app.infrastructure.jma_amedas_client import AmedasReading, AmedasStation
from app.infrastructure.jma_amedas_store import RainHistory
from app.infrastructure.jma_tile_client import JmaTileClient
from app.infrastructure.debug_log import log_throttled_warning

logger = logging.getLogger("ridecompass.jma_amedas_service")

_RAIN_MATERIALS_CACHE_TTL_SECONDS = 5 * 60
_rain_materials_cache: TTLCache = TTLCache(maxsize=1, ttl=_RAIN_MATERIALS_CACHE_TTL_SECONDS)
_RAIN_MATERIALS_CACHE_KEY = "rain_materials"


class JmaAmedasService:
    def __init__(self, http_client: httpx.AsyncClient):
        self._http_client = http_client

    async def get_nearest_observation(self, point: Coordinates) -> AmedasObservation | None:
        """最寄り観測所を解決し、保存済みの観測値に地点の日の出・日没と天気コードを入れて返す。観測値はJMAへ
        問い合わせない。推計気象分布が取れなくても観測値は返し、降っていなければ天気コードだけがNoneになる。

        バッチがまだ一度も成功していない・Redisが不通・最寄り観測所が必要なセンサーを
        持たない種別（雨量計のみ等）のいずれもNone。
        """
        stations = await jma_amedas_client.fetch_station_table(self._http_client)
        if not stations:
            return None
        station_ids = list(stations)
        nearest_index = nearest_point_index(
            point.latitude, point.longitude,
            np.array([stations[station_id].latitude for station_id in station_ids]),
            np.array([stations[station_id].longitude for station_id in station_ids]),
        )
        if nearest_index is None:
            return None
        station_id = station_ids[nearest_index]
        observation = await jma_amedas_store.read_observation(station_id)
        if observation is None:
            return None
        # 日の出/日没は最寄り観測所ではなく**クエリ地点**に対して計算する（観測所境界
        # 付近でのズレを避ける）。外部への問い合わせを伴わないため都度計算でよい。
        today = datetime.now(JST).date()
        color = await jma_suikei_client.fetch_weather_color(
            JmaTileClient(self._http_client), point.latitude, point.longitude
        )
        sky = None if color is None else sky_from_color(*color)
        return observation.model_copy(
            update={
                "twilight": sunrise_sunset_jst(point, today),
                "weather_code": derive_observed_weather_code(
                    observation.precipitation_10min_mm, sky, observation.temperature_c
                ),
            }
        )

    async def refresh_all_stations(self) -> int:
        """全国のアメダス観測値を1回取得し、観測所ごとに書き戻す。

        戻り値は書き込んだ観測所数で、0は取得失敗またはデータ無し。0で終わった場合は
        例外を投げずWARNINGだけを出す——例外にしないため、ここで出さないと「1件も書けて
        いないバッチ」が無警告のまま繰り返される。
        """
        stations = await jma_amedas_client.fetch_station_table(self._http_client)
        if not stations:
            logger.warning("アメダス観測所マスタの取得に失敗しました（全滅バッチ）")
            return 0
        latest_time = await jma_amedas_client.fetch_latest_observation_time(self._http_client)
        if latest_time is None:
            logger.warning("アメダス最新観測時刻の取得に失敗しました（全滅バッチ）")
            return 0
        observation_map = await jma_amedas_client.fetch_observation_map(self._http_client, latest_time)
        if observation_map is None:
            logger.warning("アメダス観測値マップの取得に失敗しました（全滅バッチ）time=%s", latest_time.isoformat())
            return 0

        observations = [
            _observation(station_id, station, reading, latest_time.isoformat())
            for station_id, reading in observation_map.items()
            if (station := stations.get(station_id)) is not None
        ]
        await jma_amedas_store.write_observations(observations)
        await self._refresh_rain_history(stations, latest_time, observation_map)
        return len(observations)

    async def _refresh_rain_history(
        self, stations: dict[str, AmedasStation], latest_time: datetime, latest_map: dict[str, AmedasReading]
    ) -> None:
        """毎正時の1時間雨量の履歴（直近`RAIN_HISTORY_HOURS`本）に欠けている正時を、その正時の
        地図JSONから埋める。

        起動直後やRedisが空のときは全本を過去の地図JSONから取り直す（気象庁は過去の地図JSONも
        同じURLの形で置いている）。平常時に取りに行くのは、新しく来た正時の1本だけ。
        取れなかった正時は欠けたまま残し、次のバッチでまた取りに行く。
        """
        latest_hour = latest_time.astimezone(JST).replace(minute=0, second=0, microsecond=0)
        hours = [latest_hour - timedelta(hours=back) for back in range(RAIN_HISTORY_HOURS)]
        stored = await jma_amedas_store.read_rain_history()
        if stored is None and not jma_amedas_store.available():
            # 置き場が使えない間に全本を取り直すと、10分ごとに気象庁へ全本を問い合わせ続ける。
            return
        stored_hours = {} if stored is None else stored.hours
        history = {hour: stored_hours[hour] for hour in hours if hour in stored_hours}
        fetched = 0
        failed = 0
        for hour in hours:
            if hour in history:
                continue
            if hour == latest_time:
                hour_map: dict[str, AmedasReading] | None = latest_map
            else:
                hour_map = await jma_amedas_client.fetch_observation_map(self._http_client, hour)
            if hour_map is None:
                failed += 1
                continue
            history[hour] = _hourly_rain(hour_map)
            fetched += 1
        if failed:
            log_throttled_warning(
                "weather:jma-amedas-rain-history",
                "アメダスの1時間雨量の履歴を取れなかった正時があります missing=%d latest_hour=%s",
                failed, latest_hour.isoformat(),
            )
        if fetched == 0 and stored is not None and stored.latest_hour == latest_hour:
            return
        await jma_amedas_store.write_rain_history(
            RainHistory(
                latest_hour=latest_hour,
                stations={
                    station_id: (stations[station_id].latitude, stations[station_id].longitude)
                    for station_id in {station_id for rain in history.values() for station_id in rain}
                    if station_id in stations
                },
                hours=history,
            )
        )
        logger.info(
            "アメダスの1時間雨量の履歴を更新しました latest_hour=%s fetched=%d missing=%d",
            latest_hour.isoformat(), fetched, failed,
        )


def _observation(station_id: str, station: AmedasStation, reading: AmedasReading, observed_at: str) -> AmedasObservation:
    return AmedasObservation(
        station_id=station_id,
        station_name=station.name,
        latitude=station.latitude,
        longitude=station.longitude,
        observed_at=observed_at,
        temperature_c=reading.temperature_c,
        apparent_temperature_c=apparent_temperature_from_amedas(
            reading.temperature_c, reading.humidity_percent, reading.wind_speed_ms
        ),
        wind_speed_ms=reading.wind_speed_ms,
        wind_direction=wind_direction_from_jma_code(reading.wind_direction_code),
        precipitation_10min_mm=reading.precipitation_10min_mm,
        # クエリ地点依存のためバッチ時点では決められない。
        twilight=None,
        weather_code=None,
    )


def _hourly_rain(observation_map: dict[str, AmedasReading]) -> dict[str, float | None]:
    """正時の観測値から、雨量計を持つ観測所の直前1時間の雨量（欠測はNone）。雨量の項目を
    持たない観測所は載せない。"""
    return {
        station_id: reading.precipitation_1h_mm
        for station_id, reading in observation_map.items()
        if reading.reports_precipitation_1h
    }


async def load_station_rain_materials(now: datetime) -> StationRainMaterials | None:
    """観測所ごとの雨の材料（`domain/rain.py`）。保存済みの履歴だけを読み、気象庁へは問い合わせない。

    履歴がまだ無い（バッチが一度も成功していない・Redisが不通）・最新の正時が古い
    （`domain/rain.py: is_rain_history_current`）ときはNone。

    求めた値はプロセス内に`_RAIN_MATERIALS_CACHE_TTL_SECONDS`だけ持つ——地図のタイル1枚ごとに
    全観測所×`RAIN_HISTORY_HOURS`本の履歴を読み直さないため。履歴が新しい正時を得てから
    地図に出るまで、この時間だけ遅れうる。
    """
    materials = _rain_materials_cache.get(_RAIN_MATERIALS_CACHE_KEY)
    if materials is None:
        history = await jma_amedas_store.read_rain_history()
        if history is None or not history.stations:
            return None
        materials = _station_rain_materials(history)
        _rain_materials_cache[_RAIN_MATERIALS_CACHE_KEY] = materials
    if not is_rain_history_current(materials.latest_hour, now):
        log_throttled_warning(
            "weather:jma-amedas-rain-history",
            "アメダスの1時間雨量の履歴が古いため雨の材料を配りません latest_hour=%s",
            materials.latest_hour.isoformat(),
        )
        return None
    return materials


def _station_rain_materials(history: RainHistory) -> StationRainMaterials:
    station_ids = sorted(history.stations)
    hourly_mm = np.full((len(station_ids), RAIN_HISTORY_HOURS), np.nan)
    for column, back in enumerate(range(RAIN_HISTORY_HOURS - 1, -1, -1)):
        rain = history.hours.get(history.latest_hour - timedelta(hours=back))
        if rain is None:
            continue
        for row, station_id in enumerate(station_ids):
            value = rain.get(station_id)
            if value is not None:
                hourly_mm[row, column] = value
    coordinates = np.array([history.stations[station_id] for station_id in station_ids], dtype=float)
    return StationRainMaterials(
        latest_hour=history.latest_hour,
        latitudes=coordinates[:, 0],
        longitudes=coordinates[:, 1],
        values=rain_material_values(hourly_mm),
    )
