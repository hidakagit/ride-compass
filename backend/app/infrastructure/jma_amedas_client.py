"""JMAアメダス観測値APIのクライアント。

`jma_warning_client.py`と同じ「JMA公式の非公開だが広く使われているエンドポイント」を使う。
応答の形（キー名・[度, 分]の座標・[値, 品質フラグ]の観測値）はここで解き、呼び出し元
（`jma_amedas_service.py`）へは`AmedasStation`・`AmedasReading`の値で渡す。
取得失敗時はNoneを返し、呼び出し元が「観測値なし」として扱う。
"""

from dataclasses import dataclass
from datetime import datetime

import httpx
from cachetools import TTLCache

from app.domain.time_zone import JST
from app.infrastructure.simple_api_client import UnexpectedShapeError, cached_fetch

# 観測所マスタは`amedastable.json`（`amedas.json`ではない）。最新時刻は`latest_time.txt`
# （ISO時刻文字列1個のプレーンテキスト、JSON配列ではない。fetch_latest_observation_time
# 参照）。
AMEDAS_STATION_TABLE_URL = "https://www.jma.go.jp/bosai/amedas/const/amedastable.json"
AMEDAS_LATEST_TIME_URL = "https://www.jma.go.jp/bosai/amedas/data/latest_time.txt"
AMEDAS_OBSERVATION_URL_TEMPLATE = "https://www.jma.go.jp/bosai/amedas/data/map/{timestamp}.json"

REQUEST_TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)

#: 気象庁アメダスの配信間隔（毎正時から10分おき）。
AMEDAS_REFRESH_INTERVAL_MINUTES = 10

# 観測所マスタ（緯度経度）は行政区画変更等でしか変わらない静的に近いデータのため、
# jma_warning_client.pyのarea.jsonと同じ長寿命TTL。
_STATION_TABLE_CACHE_TTL_SECONDS = 24 * 60 * 60
# 最新観測時刻の一覧は10分更新のアメダスの鮮度に合わせた短いTTL。
_LATEST_TIME_CACHE_TTL_SECONDS = 5 * 60

_STATION_TABLE_CACHE_KEY = "stations"
_LATEST_TIME_CACHE_KEY = "latest_time"


def new_station_table_cache() -> TTLCache:
    """`fetch_station_table`へ渡すキャッシュ。リクエストをまたいで持つのは組み立てる側（`api/dependencies.py`）。"""
    return TTLCache(maxsize=1, ttl=_STATION_TABLE_CACHE_TTL_SECONDS)


def new_latest_time_cache() -> TTLCache:
    """`fetch_latest_observation_time`へ渡すキャッシュ。リクエストをまたいで持つのは組み立てる側（`api/dependencies.py`）。"""
    return TTLCache(maxsize=1, ttl=_LATEST_TIME_CACHE_TTL_SECONDS)


@dataclass(frozen=True)
class AmedasStation:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class AmedasReading:
    """1観測所の1時刻ぶんの観測値。センサーを持たない・欠測の項目はNone。"""

    temperature_c: float | None
    humidity_percent: float | None
    wind_speed_ms: float | None
    #: 気象庁の16方位コード（0=静穏）。角度への読み替えは`domain/jma_amedas.py: wind_direction_from_jma_code`。
    wind_direction_code: int | None
    precipitation_10min_mm: float | None
    #: その時刻に終わる1時間の雨量。正時の観測値だけが持つ。
    precipitation_1h_mm: float | None
    #: 1時間雨量の項目を持つか。雨量計の無い観測所は持たず、雨量計はあるが欠測なら
    #: 項目はあって値がNone——雨の履歴は前者を載せず、後者を欠測として載せる。
    reports_precipitation_1h: bool


def _degree_minute(value: list) -> float:
    """気象庁の[度, 分]を10進度にする。"""
    return value[0] + value[1] / 60


def _parse_station_table(payload: dict) -> dict[str, AmedasStation]:
    """座標の無い観測所は載せない（最寄りにも、雨の履歴の座標にも使えない）。"""
    stations = {}
    for station_id, entry in payload.items():
        lat = entry.get("lat")
        lon = entry.get("lon")
        if not lat or not lon:
            continue
        stations[station_id] = AmedasStation(latitude=_degree_minute(lat), longitude=_degree_minute(lon))
    return stations


def _first_value(pair: list | None) -> float | None:
    """[値, 品質フラグ]から値を取り出す。品質フラグの意味は判定せず、値の有無だけを見る。"""
    if not pair:
        return None
    return pair[0]


def _parse_reading(raw: dict) -> AmedasReading:
    wind_direction = _first_value(raw.get("windDirection"))
    return AmedasReading(
        temperature_c=_first_value(raw.get("temp")),
        humidity_percent=_first_value(raw.get("humidity")),
        wind_speed_ms=_first_value(raw.get("wind")),
        wind_direction_code=None if wind_direction is None else int(wind_direction),
        precipitation_10min_mm=_first_value(raw.get("precipitation10m")),
        precipitation_1h_mm=_first_value(raw.get("precipitation1h")),
        reports_precipitation_1h="precipitation1h" in raw,
    )


async def fetch_station_table(client: httpx.AsyncClient, cache: TTLCache) -> dict[str, AmedasStation] | None:
    """観測所マスタ（観測所id → 観測所）を取得する。"""

    async def fetch() -> dict[str, AmedasStation]:
        response = await client.get(AMEDAS_STATION_TABLE_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise UnexpectedShapeError(f"station table is {type(payload).__name__}")
        return _parse_station_table(payload)

    return await cached_fetch("weather:jma-amedas-stations", fetch, cache=cache, key=_STATION_TABLE_CACHE_KEY)


async def fetch_latest_observation_time(client: httpx.AsyncClient, cache: TTLCache) -> datetime | None:
    """最新の観測時刻を返す。

    レスポンスはJSON配列ではなく、ISO時刻文字列1個だけのプレーンテキスト
    （例: "2026-08-29T17:00:00+09:00"）。
    """

    async def fetch() -> datetime:
        response = await client.get(AMEDAS_LATEST_TIME_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        latest = response.text.strip()
        try:
            observed_at = datetime.fromisoformat(latest)
        except ValueError as exc:
            raise UnexpectedShapeError(f"latest observation time is not ISO: {latest!r}") from exc
        if observed_at.tzinfo is None:
            raise UnexpectedShapeError(f"latest observation time has no offset: {latest!r}")
        return observed_at

    # 応答はプレーンテキストで`.json()`を呼ばず、読めない時刻は`UnexpectedShapeError`へ直すため、
    # ほかにValueErrorの発生源が無い。
    return await cached_fetch(
        "weather:jma-amedas-latest-time",
        fetch,
        cache=cache,
        key=_LATEST_TIME_CACHE_KEY,
        catch=(httpx.HTTPError,),
    )


async def fetch_observation_map(
    client: httpx.AsyncClient, observed_at: datetime
) -> dict[str, AmedasReading] | None:
    """指定時刻の全観測所ぶんの観測値（観測所id → 観測値）を取得する。"""
    timestamp = observed_at.astimezone(JST).strftime("%Y%m%d%H%M%S")

    async def fetch() -> dict[str, AmedasReading]:
        response = await client.get(
            AMEDAS_OBSERVATION_URL_TEMPLATE.format(timestamp=timestamp), timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise UnexpectedShapeError(f"observation map is {type(payload).__name__}")
        return {station_id: _parse_reading(raw) for station_id, raw in payload.items()}

    return await cached_fetch("weather:jma-amedas-observation", fetch, timestamp=timestamp)
