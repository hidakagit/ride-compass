"""JMAアメダス観測値サービス。

最寄りのアメダス観測所を解決し、直近の気温・風向風速・10分間降水量を返す。

**取得は定期バッチが担い、リクエスト経路（`get_nearest_observation`）はRedis読み取り専用に
する**。JMAの観測値エンドポイントは1地点だけを絞り込めず、常に全国ぶんを1回のレスポンスで
返すため——「リクエストされた1地点だけ」を都度取る形にすると、その不可分な取得コストを
払いながら近隣ユーザーのリクエストはキャッシュヒットせず、同じ全国データを取り直し続ける。

観測値は短命でPostGISへは書かず、Redis Hash（`jma:amedas:{station_id}`）で完結させる。
雨の材料（`domain/rain.py`）の元になる毎正時の1時間雨量の履歴も同じバッチが取り、Redisの1キー
（`jma:amedas:rain-history`）に持つ——失うと気象庁の過去の地図JSONを全本取り直すことになる。
"""

import logging
from collections.abc import Awaitable
from datetime import datetime, timedelta
from typing import cast

import httpx
import numpy as np
from cachetools import TTLCache

from app.domain.rain import RAIN_HISTORY_HOURS, StationRainMaterials, rain_material_values
from app.domain.time_zone import JST
from app.domain.geo import LatLonPoint, haversine_distance_km
from app.domain.jma_amedas import (
    AmedasObservation,
    apparent_temperature_from_amedas,
    wind_direction_from_jma_code,
)
from app.domain.route import Coordinates
from app.domain.twilight import sunrise_sunset_jst
from app.infrastructure import jma_amedas_client
from app.infrastructure.debug_log import log_throttled_warning
from app.infrastructure.redis_client import (
    get_redis_client_or_none,
    record_redis_failure,
    record_redis_success,
    redis_available,
)
from app.infrastructure.redis_json_cache import get_json, set_json

logger = logging.getLogger("ridecompass.jma_amedas_service")

_REDIS_KEY_PREFIX = "jma:amedas"
_REDIS_TTL_SECONDS = 15 * 60
#: 気象庁アメダスの配信間隔（毎正時から10分おき）に合わせる。`_REDIS_TTL_SECONDS`は
#: これより長く取ること。
AMEDAS_REFRESH_INTERVAL_MINUTES = 10

_RAIN_HISTORY_KEY = f"{_REDIS_KEY_PREFIX}:rain-history"
# 履歴は新しい正時が来るたびに書き直すので、TTLは書き直しが止まったときの消え方だけを決める。
# 最も古い1本が窓から外れるまでは残し、バッチが戻ったときに取り直す本数を減らす。
_RAIN_HISTORY_TTL_SECONDS = (RAIN_HISTORY_HOURS + 1) * 60 * 60
#: 最新の正時がこれより古い履歴は配らない（地図は「データなし」）。正時の地図JSONは次の正時まで
#: 最新なので平常時でも1時間余りは古く、1本取り損ねても塗り続けられる幅にしてある。
RAIN_HISTORY_MAX_AGE = timedelta(hours=2, minutes=30)
_RAIN_MATERIALS_CACHE_TTL_SECONDS = 5 * 60
_rain_materials_cache: TTLCache = TTLCache(maxsize=1, ttl=_RAIN_MATERIALS_CACHE_TTL_SECONDS)


def _redis_key(station_id: str) -> str:
    return f"{_REDIS_KEY_PREFIX}:{station_id}"


def _nearest_station(stations: dict, point: Coordinates) -> str | None:
    best_station_id: str | None = None
    best_distance = float("inf")
    for station_id, entry in stations.items():
        lat = entry.get("lat")
        lon = entry.get("lon")
        name = entry.get("kjName")
        if not lat or not lon or not name:
            continue
        # JMAのlat/lonは[度, 分]配列（jma_amedas_client.pyのdocstring参照）。
        latitude = lat[0] + lat[1] / 60
        longitude = lon[0] + lon[1] / 60
        distance = haversine_distance_km(point, LatLonPoint(latitude=latitude, longitude=longitude))
        if distance < best_distance:
            best_distance = distance
            best_station_id = station_id
    return best_station_id


class JmaAmedasService:
    def __init__(self, http_client: httpx.AsyncClient):
        self._http_client = http_client

    async def get_nearest_observation(self, point: Coordinates) -> AmedasObservation | None:
        """最寄り観測所を解決し、Redisにキャッシュ済みの観測値を返す。JMAへは問い合わせない。

        バッチがまだ一度も成功していない・Redisが不通・最寄り観測所が必要なセンサーを
        持たない種別（雨量計のみ等）のいずれもNone。
        """
        stations = await jma_amedas_client.fetch_station_table(self._http_client)
        if not stations:
            return None
        station_id = _nearest_station(stations, point)
        if station_id is None:
            return None
        observation = await self._get_from_redis(station_id)
        if observation is None:
            return None
        # 日の出/日没は最寄り観測所ではなく**クエリ地点**に対して計算する（観測所境界
        # 付近でのズレを避ける）。外部への問い合わせを伴わないため都度計算でよい。
        today = datetime.now(JST).date()
        sunrise, sunset = sunrise_sunset_jst(point, today)
        return observation.model_copy(update={"sunrise": sunrise, "sunset": sunset})

    async def _get_from_redis(self, station_id: str) -> AmedasObservation | None:
        if not redis_available():
            return None
        client = get_redis_client_or_none()
        if client is None:
            return None
        try:
            # redis-pyは同期・非同期のクライアントで型を共有し、戻り値を`Awaitable[X] | X`と宣言している。
            fields = await cast(Awaitable[dict], client.hgetall(_redis_key(station_id)))
        except Exception as exc:  # noqa: BLE001 Redis障害は「観測値なし」にfail-open
            record_redis_failure()
            log_throttled_warning("cache:jma-amedas-redis", "[cache:jma-amedas-redis] read failed error=%r", exc)
            return None
        record_redis_success()
        if not fields:
            return None
        try:
            return self._observation_from_fields(station_id, fields)
        except (KeyError, ValueError) as exc:
            # Hashには版が無く、中身は**過去のコードが書いた形**である。必須フィールドが
            # 欠けた・型が変わった状態を無条件に展開すると、キャッシュの不整合が
            # 「観測値が無い」ではなく500になって外へ出る。fail-openの契約どおり倒す。
            log_throttled_warning(
                "cache:jma-amedas-redis",
                "[cache:jma-amedas-redis] 保存済みの観測値の形が現在のモデルと一致しません"
                " station_id=%s error=%r", station_id, exc,
            )
            return None

    @staticmethod
    def _observation_from_fields(station_id: str, fields: dict) -> AmedasObservation:
        return AmedasObservation(
            station_id=station_id,
            station_name=fields["station_name"],
            latitude=float(fields["latitude"]),
            longitude=float(fields["longitude"]),
            observed_at=fields["observed_at"],
            temperature_c=_optional_float(fields.get("temperature_c")),
            apparent_temperature_c=_optional_float(fields.get("apparent_temperature_c")),
            wind_speed_ms=_optional_float(fields.get("wind_speed_ms")),
            wind_direction_deg=_optional_float(fields.get("wind_direction_deg")),
            wind_direction_label=fields.get("wind_direction_label") or None,
            precipitation_10min_mm=_optional_float(fields.get("precipitation_10min_mm")),
            sunshine_10min_minutes=_optional_float(fields.get("sunshine_10min_minutes")),
            # sunrise/sunsetはクエリ地点依存のためRedisに無く、呼び出し側が後から埋める。
            sunrise=None,
            sunset=None,
        )

    async def refresh_all_stations(self) -> int:
        """全国のアメダス観測値を1回取得し、観測所ごとにRedisへ書き戻す。

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
        compact_timestamp = datetime.fromisoformat(latest_time).strftime("%Y%m%d%H%M%S")
        observation_map = await jma_amedas_client.fetch_observation_map(self._http_client, compact_timestamp)
        if observation_map is None:
            logger.warning("アメダス観測値マップの取得に失敗しました（全滅バッチ）time=%s", compact_timestamp)
            return 0

        observations = []
        for station_id, raw in observation_map.items():
            station_meta = stations.get(station_id)
            if station_meta is None:
                continue
            lat = station_meta.get("lat")
            lon = station_meta.get("lon")
            name = station_meta.get("kjName")
            if not lat or not lon or not name:
                continue
            wind_direction_code = _first_int(raw.get("windDirection"))
            temperature_c = _first_value(raw.get("temp"))
            wind_speed_ms = _first_value(raw.get("wind"))
            humidity_percent = _first_value(raw.get("humidity"))
            wind_direction_deg, wind_direction_label = wind_direction_from_jma_code(wind_direction_code) or (None, None)
            observations.append(
                AmedasObservation(
                    station_id=station_id,
                    station_name=name,
                    latitude=lat[0] + lat[1] / 60,
                    longitude=lon[0] + lon[1] / 60,
                    observed_at=latest_time,
                    temperature_c=temperature_c,
                    apparent_temperature_c=apparent_temperature_from_amedas(
                        temperature_c, humidity_percent, wind_speed_ms
                    ),
                    wind_speed_ms=wind_speed_ms,
                    wind_direction_deg=wind_direction_deg,
                    wind_direction_label=wind_direction_label,
                    precipitation_10min_mm=_first_value(raw.get("precipitation10m")),
                    sunshine_10min_minutes=_first_value(raw.get("sun10m")),
                    # クエリ地点依存のためバッチ時点では決められない。
                    sunrise=None,
                    sunset=None,
                )
            )
        await self._save_all_to_redis(observations)
        await self._refresh_rain_history(stations, datetime.fromisoformat(latest_time), observation_map)
        return len(observations)

    async def _refresh_rain_history(self, stations: dict, latest_time: datetime, latest_map: dict) -> None:
        """毎正時の1時間雨量の履歴（直近`RAIN_HISTORY_HOURS`本）に欠けている正時を、その正時の
        地図JSONから埋める。

        起動直後やRedisが空のときは全本を過去の地図JSONから取り直す（気象庁は過去の地図JSONも
        同じURLの形で置いている）。平常時に取りに行くのは、新しく来た正時の1本だけ。
        取れなかった正時は欠けたまま残し、次のバッチでまた取りに行く。
        """
        latest_hour = latest_time.astimezone(JST).replace(minute=0, second=0, microsecond=0)
        hours = [latest_hour - timedelta(hours=back) for back in range(RAIN_HISTORY_HOURS)]
        stored = await get_json(_RAIN_HISTORY_KEY, category="cache:jma-amedas-rain-history")
        if stored is None and not redis_available():
            # 置き場が使えない間に全本を取り直すと、10分ごとに気象庁へ全本を問い合わせ続ける。
            return
        stored = stored or {}
        stored_hours = stored.get("hours", {})
        history: dict[str, dict[str, float | None]] = {
            _hour_key(hour): stored_hours[_hour_key(hour)] for hour in hours if _hour_key(hour) in stored_hours
        }
        fetched = 0
        failed = 0
        for hour in hours:
            if _hour_key(hour) in history:
                continue
            if hour == latest_time:
                hour_map: dict | None = latest_map
            else:
                hour_map = await jma_amedas_client.fetch_observation_map(
                    self._http_client, hour.strftime("%Y%m%d%H%M%S")
                )
            if hour_map is None:
                failed += 1
                continue
            history[_hour_key(hour)] = _hourly_rain(hour_map)
            fetched += 1
        if failed:
            log_throttled_warning(
                "weather:jma-amedas-rain-history",
                "アメダスの1時間雨量の履歴を取れなかった正時があります missing=%d latest_hour=%s",
                failed, _hour_key(latest_hour),
            )
        if fetched == 0 and stored.get("latest_hour") == _hour_key(latest_hour):
            return
        await set_json(
            _RAIN_HISTORY_KEY,
            {
                "latest_hour": _hour_key(latest_hour),
                "stations": {
                    station_id: _decimal_coordinates(stations[station_id])
                    for station_id in {station_id for rain in history.values() for station_id in rain}
                    if station_id in stations and stations[station_id].get("lat") and stations[station_id].get("lon")
                },
                "hours": history,
            },
            ttl_seconds=_RAIN_HISTORY_TTL_SECONDS,
            category="cache:jma-amedas-rain-history",
        )
        logger.info(
            "アメダスの1時間雨量の履歴を更新しました latest_hour=%s fetched=%d missing=%d",
            _hour_key(latest_hour), fetched, failed,
        )

    async def _save_all_to_redis(self, observations: list[AmedasObservation]) -> None:
        if not observations or not redis_available():
            return
        client = get_redis_client_or_none()
        if client is None:
            return
        try:
            pipe = client.pipeline(transaction=False)
            for observation in observations:
                key = _redis_key(observation.station_id)
                pipe.hset(
                    key,
                    mapping={
                        "station_name": observation.station_name,
                        "latitude": observation.latitude,
                        "longitude": observation.longitude,
                        "observed_at": observation.observed_at,
                        "temperature_c": _redis_value(observation.temperature_c),
                        "apparent_temperature_c": _redis_value(observation.apparent_temperature_c),
                        "wind_speed_ms": _redis_value(observation.wind_speed_ms),
                        "wind_direction_deg": _redis_value(observation.wind_direction_deg),
                        "wind_direction_label": observation.wind_direction_label or "",
                        "precipitation_10min_mm": _redis_value(observation.precipitation_10min_mm),
                        "sunshine_10min_minutes": _redis_value(observation.sunshine_10min_minutes),
                    },
                )
                pipe.expire(key, _REDIS_TTL_SECONDS)
            await pipe.execute()
        except Exception as exc:  # noqa: BLE001 書き込み失敗は次回バッチで自己修復する
            record_redis_failure()
            log_throttled_warning("cache:jma-amedas-redis", "[cache:jma-amedas-redis] write failed error=%r", exc)
        else:
            record_redis_success()


def _first_value(pair: list | None) -> float | None:
    """JMAの[値, 品質フラグ]配列から値を取り出す。

    品質フラグの意味は判定せず、値の有無だけを見る。フィールド自体を持たない観測所
    （雨量計のみ等）があるのは正常な状態で、その場合はNoneのまま返す。
    """
    if not pair:
        return None
    return pair[0]


def _first_int(pair: list | None) -> int | None:
    value = _first_value(pair)
    return None if value is None else int(value)


def _redis_value(value: float | None) -> str:
    return "" if value is None else str(value)


def _optional_float(value: str | None) -> float | None:
    return None if not value else float(value)


def _hour_key(hour: datetime) -> str:
    return hour.strftime("%Y%m%d%H")


def _decimal_coordinates(station_meta: dict) -> list[float]:
    lat = station_meta["lat"]
    lon = station_meta["lon"]
    return [lat[0] + lat[1] / 60, lon[0] + lon[1] / 60]


def _hourly_rain(observation_map: dict) -> dict[str, float | None]:
    """正時の地図JSONから、雨量計を持つ観測所の直前1時間の雨量（欠測はNone）。雨量の項目を
    持たない観測所は載せない。"""
    return {
        station_id: _first_value(raw["precipitation1h"])
        for station_id, raw in observation_map.items()
        if "precipitation1h" in raw
    }


async def load_station_rain_materials(now: datetime) -> StationRainMaterials | None:
    """観測所ごとの雨の材料（`domain/rain.py`）。Redisの履歴だけを読み、気象庁へは問い合わせない。

    履歴がまだ無い（バッチが一度も成功していない・Redisが不通）・最新の正時が
    `RAIN_HISTORY_MAX_AGE`より古いときはNone。

    求めた値はプロセス内に`_RAIN_MATERIALS_CACHE_TTL_SECONDS`だけ持つ——地図のタイル1枚ごとに
    全観測所×`RAIN_HISTORY_HOURS`本の履歴を読み直さないため。履歴が新しい正時を得てから
    地図に出るまで、この時間だけ遅れうる。
    """
    materials = _rain_materials_cache.get(_RAIN_HISTORY_KEY)
    if materials is None:
        stored = await get_json(_RAIN_HISTORY_KEY, category="cache:jma-amedas-rain-history")
        if stored is None or not stored["stations"]:
            return None
        materials = _station_rain_materials(stored)
        _rain_materials_cache[_RAIN_HISTORY_KEY] = materials
    if now - materials.latest_hour > RAIN_HISTORY_MAX_AGE:
        log_throttled_warning(
            "weather:jma-amedas-rain-history",
            "アメダスの1時間雨量の履歴が古いため雨の材料を配りません latest_hour=%s",
            _hour_key(materials.latest_hour),
        )
        return None
    return materials


def _station_rain_materials(stored: dict) -> StationRainMaterials:
    latest_hour = datetime.strptime(stored["latest_hour"], "%Y%m%d%H").replace(tzinfo=JST)
    station_ids = sorted(stored["stations"])
    hourly_mm = np.full((len(station_ids), RAIN_HISTORY_HOURS), np.nan)
    for column, back in enumerate(range(RAIN_HISTORY_HOURS - 1, -1, -1)):
        rain = stored["hours"].get(_hour_key(latest_hour - timedelta(hours=back)))
        if rain is None:
            continue
        for row, station_id in enumerate(station_ids):
            value = rain.get(station_id)
            if value is not None:
                hourly_mm[row, column] = value
    coordinates = np.array([stored["stations"][station_id] for station_id in station_ids], dtype=float)
    return StationRainMaterials(
        latest_hour=latest_hour,
        latitudes=coordinates[:, 0],
        longitudes=coordinates[:, 1],
        values=rain_material_values(hourly_mm),
    )
