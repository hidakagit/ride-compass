"""アメダスの観測値と1時間雨量の履歴をRedisに置く・読む。

鍵・項目名・TTL・保存した形の検査はここが持ち、呼び出し元（`services/jma_amedas_service.py`）とは
`AmedasObservation`・`RainHistory`の値でやり取りする。保存した形の不一致は「無い」へ倒す（fail-open）。

観測値は観測所ごとのHashに置き、全観測所を1往復で書く。履歴は1キーのJSONに置く。どちらも`redis_json_cache`を通す。
"""

from dataclasses import dataclass
from datetime import datetime

from app.domain.jma_amedas import AmedasObservation, WindDirection
from app.domain.rain import RAIN_HISTORY_HOURS
from app.domain.time_zone import JST
from app.infrastructure.debug_log import log_throttled_warning
from app.infrastructure.jma_amedas_client import AMEDAS_REFRESH_INTERVAL_MINUTES
from app.infrastructure.redis_json_cache import UNAVAILABLE, Unavailable, get_hash, get_json, set_hashes, set_json

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


def _observation_key(station_id: str) -> str:
    return f"{_KEY_PREFIX}:{station_id}"


async def read_observation(station_id: str) -> AmedasObservation | None:
    """保存済みの観測値。日の出・日没（`twilight`）と天気コード（`weather_code`）は持たずNoneで返す（クエリ地点で決まるため）。

    未保存とRedisを読めないときは、どちらも観測値なしとしてNone（読み手はどちらでも観測値を出さない）。
    """
    observation = await get_hash(
        _observation_key(station_id),
        decode=lambda fields: _observation_or_none(station_id, fields),
        category=_OBSERVATION_CATEGORY,
        station_id=station_id,
    )
    return None if observation is UNAVAILABLE else observation


def _observation_or_none(station_id: str, raw: dict[bytes, bytes]) -> AmedasObservation | None:
    fields = {name.decode(): value.decode() for name, value in raw.items()}
    try:
        return _observation_from_fields(fields)
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


async def write_observations(observations: dict[str, AmedasObservation]) -> None:
    """観測所ごと（観測所id → 観測値）に書き戻す。失敗は次のバッチで自己修復するため、記録だけして諦める。"""
    await set_hashes(
        {
            _observation_key(station_id): _fields_from_observation(observation)
            for station_id, observation in observations.items()
        },
        ttl_seconds=_OBSERVATION_TTL_SECONDS,
        category=_OBSERVATION_CATEGORY,
    )


def _fields_from_observation(observation: AmedasObservation) -> dict[str, str]:
    return {
        "temperature_c": _field_value(observation.temperature_c),
        "apparent_temperature_c": _field_value(observation.apparent_temperature_c),
        "wind_speed_ms": _field_value(observation.wind_speed_ms),
        "wind_direction_deg": _field_value(None if observation.wind_direction is None else observation.wind_direction.deg),
        "wind_direction_label": "" if observation.wind_direction is None else observation.wind_direction.label,
        "precipitation_10min_mm": _field_value(observation.precipitation_10min_mm),
    }


def _observation_from_fields(fields: dict[str, str]) -> AmedasObservation:
    return AmedasObservation(
        temperature_c=_optional_float(fields.get("temperature_c")),
        apparent_temperature_c=_optional_float(fields.get("apparent_temperature_c")),
        wind_speed_ms=_optional_float(fields.get("wind_speed_ms")),
        wind_direction=_wind_direction_from_fields(fields),
        precipitation_10min_mm=_optional_float(fields.get("precipitation_10min_mm")),
        twilight=None,
        weather_code=None,
    )


def _field_value(value: float | None) -> str:
    return "" if value is None else str(value)


def _optional_float(value: str | None) -> float | None:
    return None if not value else float(value)


def _wind_direction_from_fields(fields: dict[str, str]) -> WindDirection | None:
    """角度とラベルは同じ観測から一緒に書かれるため、角度があればラベルもある。"""
    deg = _optional_float(fields.get("wind_direction_deg"))
    return None if deg is None else WindDirection(deg=deg, label=fields["wind_direction_label"])


async def read_rain_history() -> RainHistory | None | Unavailable:
    """保存済みの履歴。未保存・保存した形が読めないときはNone、Redisを読めないときは`UNAVAILABLE`。"""
    stored = await get_json(_RAIN_HISTORY_KEY, category=_RAIN_HISTORY_CATEGORY)
    if stored is None or stored is UNAVAILABLE:
        return stored
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
