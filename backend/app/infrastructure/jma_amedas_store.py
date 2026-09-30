"""アメダスの観測値と1時間雨量の履歴をRedisに置く・読む。

鍵・項目名・TTL・保存した形の検査はここが持ち、呼び出し元（`services/jma_amedas_service.py`）とは
`AmedasObservation`・`RainHistory`の値でやり取りする。どちらもRedisの障害・保存した形の不一致は
「無い」へ倒す（fail-open）。

観測値は観測所ごとのHashに置き、全観測所をpipelineで一括して書く——単一キーのJSON読み書き
（`redis_json_cache`）では表せないため、骨格をここで持つ。履歴は1キーのJSONで`redis_json_cache`を通す。
"""

from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from app.domain.jma_amedas import AmedasObservation, WindDirection
from app.domain.rain import RAIN_HISTORY_HOURS
from app.domain.time_zone import JST
from app.infrastructure.debug_log import log_throttled_warning
from app.infrastructure.jma_amedas_client import AMEDAS_REFRESH_INTERVAL_MINUTES
from app.infrastructure.redis_client import (
    get_redis_client_or_none,
    record_redis_failure,
    record_redis_success,
    redis_available,
)
from app.infrastructure.redis_json_cache import get_json, set_json

_KEY_PREFIX = "jma:amedas"
#: 次のバッチが書き直すまで切らさない長さ。
_OBSERVATION_TTL_SECONDS = (AMEDAS_REFRESH_INTERVAL_MINUTES + 5) * 60
_OBSERVATION_CATEGORY = "cache:jma-amedas-redis"

_RAIN_HISTORY_KEY = f"{_KEY_PREFIX}:rain-history"
# 履歴は新しい正時が来るたびに書き直すので、TTLは書き直しが止まったときの消え方だけを決める。
# 最も古い1本が窓から外れるまでは残し、バッチが戻ったときに取り直す本数を減らす。
_RAIN_HISTORY_TTL_SECONDS = (RAIN_HISTORY_HOURS + 1) * 60 * 60
_RAIN_HISTORY_CATEGORY = "cache:jma-amedas-rain-history"
_HOUR_FORMAT = "%Y%m%d%H"


@dataclass(frozen=True)
class RainHistory:
    """毎正時の1時間雨量の履歴。"""

    #: 最新の正時（JST）。
    latest_hour: datetime
    #: 観測所id → (緯度, 経度)。
    stations: dict[str, tuple[float, float]]
    #: 正時 → 観測所id → その正時に終わる1時間の雨量（欠測はNone）。雨量計の無い観測所は載せない。
    hours: dict[datetime, dict[str, float | None]]


def available() -> bool:
    """置き場を今呼ぶ価値があるか（直近の障害からのクールダウンを過ぎたか）。"""
    return redis_available()


def _observation_key(station_id: str) -> str:
    return f"{_KEY_PREFIX}:{station_id}"


async def read_observation(station_id: str) -> AmedasObservation | None:
    """保存済みの観測値。日の出・日没（`twilight`）は持たずNoneで返す（クエリ地点で決まるため）。"""
    if not redis_available():
        return None
    client = get_redis_client_or_none()
    if client is None:
        return None
    try:
        # redis-pyは同期・非同期のクライアントで型を共有し、戻り値を`Awaitable[X] | X`と宣言している。
        fields = await cast(Awaitable[dict], client.hgetall(_observation_key(station_id)))
    except Exception as exc:  # noqa: BLE001 Redis障害は「観測値なし」にfail-open
        record_redis_failure()
        log_throttled_warning(_OBSERVATION_CATEGORY, "[cache:jma-amedas-redis] read failed error=%r", exc)
        return None
    record_redis_success()
    if not fields:
        return None
    try:
        return _observation_from_fields(station_id, fields)
    except (KeyError, ValueError) as exc:
        # Hashには版が無く、中身は**過去のコードが書いた形**である。必須フィールドが
        # 欠けた・型が変わった状態を無条件に展開すると、キャッシュの不整合が
        # 「観測値が無い」ではなく500になって外へ出る。fail-openの契約どおり倒す。
        log_throttled_warning(
            _OBSERVATION_CATEGORY,
            "[cache:jma-amedas-redis] 保存済みの観測値の形が現在のモデルと一致しません"
            " station_id=%s error=%r", station_id, exc,
        )
        return None


async def write_observations(observations: list[AmedasObservation]) -> None:
    """観測所ごとに書き戻す。失敗は次のバッチで自己修復するため、記録だけして諦める。"""
    if not observations or not redis_available():
        return
    client = get_redis_client_or_none()
    if client is None:
        return
    try:
        pipe = client.pipeline(transaction=False)
        for observation in observations:
            key = _observation_key(observation.station_id)
            pipe.hset(key, mapping=_fields_from_observation(observation))
            pipe.expire(key, _OBSERVATION_TTL_SECONDS)
        await pipe.execute()
    except Exception as exc:  # noqa: BLE001 書き込み失敗は次回バッチで自己修復する
        record_redis_failure()
        log_throttled_warning(_OBSERVATION_CATEGORY, "[cache:jma-amedas-redis] write failed error=%r", exc)
    else:
        record_redis_success()


def _fields_from_observation(observation: AmedasObservation) -> dict[str, str | float]:
    return {
        "station_name": observation.station_name,
        "latitude": observation.latitude,
        "longitude": observation.longitude,
        "observed_at": observation.observed_at,
        "temperature_c": _field_value(observation.temperature_c),
        "apparent_temperature_c": _field_value(observation.apparent_temperature_c),
        "wind_speed_ms": _field_value(observation.wind_speed_ms),
        "wind_direction_deg": _field_value(None if observation.wind_direction is None else observation.wind_direction.deg),
        "wind_direction_label": "" if observation.wind_direction is None else observation.wind_direction.label,
        "precipitation_10min_mm": _field_value(observation.precipitation_10min_mm),
        "sunshine_10min_minutes": _field_value(observation.sunshine_10min_minutes),
    }


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
        wind_direction=_wind_direction_from_fields(fields),
        precipitation_10min_mm=_optional_float(fields.get("precipitation_10min_mm")),
        sunshine_10min_minutes=_optional_float(fields.get("sunshine_10min_minutes")),
        twilight=None,
    )


def _field_value(value: float | None) -> str:
    return "" if value is None else str(value)


def _optional_float(value: str | None) -> float | None:
    return None if not value else float(value)


def _wind_direction_from_fields(fields: dict) -> WindDirection | None:
    """角度とラベルは同じ観測から一緒に書かれるため、角度があればラベルもある。"""
    deg = _optional_float(fields.get("wind_direction_deg"))
    return None if deg is None else WindDirection(deg=deg, label=fields["wind_direction_label"])


async def read_rain_history() -> RainHistory | None:
    """保存済みの履歴。未保存・Redisの障害・保存した形が読めないときはNone。"""
    stored = await get_json(_RAIN_HISTORY_KEY, category=_RAIN_HISTORY_CATEGORY)
    if stored is None:
        return None
    try:
        return RainHistory(
            latest_hour=_hour_from_key(stored["latest_hour"]),
            stations={
                station_id: (float(latitude), float(longitude))
                for station_id, (latitude, longitude) in stored["stations"].items()
            },
            hours={_hour_from_key(hour): dict(rain) for hour, rain in stored["hours"].items()},
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        log_throttled_warning(
            _RAIN_HISTORY_CATEGORY,
            "[cache:jma-amedas-rain-history] 保存済みの履歴の形が現在の形と一致しません error=%r", exc,
        )
        return None


async def write_rain_history(history: RainHistory) -> None:
    await set_json(
        _RAIN_HISTORY_KEY,
        {
            "latest_hour": _hour_key(history.latest_hour),
            "stations": {station_id: list(coordinates) for station_id, coordinates in history.stations.items()},
            "hours": {_hour_key(hour): rain for hour, rain in history.hours.items()},
        },
        ttl_seconds=_RAIN_HISTORY_TTL_SECONDS,
        category=_RAIN_HISTORY_CATEGORY,
    )


def _hour_key(hour: datetime) -> str:
    return hour.astimezone(JST).strftime(_HOUR_FORMAT)


def _hour_from_key(key: str) -> datetime:
    return datetime.strptime(key, _HOUR_FORMAT).replace(tzinfo=JST)
