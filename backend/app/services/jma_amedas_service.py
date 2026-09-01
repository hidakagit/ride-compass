"""JMAアメダス観測値サービス（改善計画T387）。

最寄りのアメダス観測所を解決し、直近の気温・風向風速・10分間降水量を返す。

**取得は定期バッチ（main.pyのAPScheduler、AMEDAS_REFRESH_INTERVAL_MINUTES間隔）が担い、
リクエスト経路（get_nearest_observation）はRedis読み取り専用にする**（ユーザー指摘、
2026-08-29）。理由: JMAの観測値エンドポイント（jma_amedas_client.fetch_observation_map）は
1地点だけを絞り込めず、常に全国約1,300観測所ぶんを1回のレスポンスで返す。「都度・
リクエストされた1地点だけ」フェッチ＆キャッシュする設計だと、この不可分な取得コストを
払っているのに他の近隣ユーザーのリクエストがキャッシュヒットせず同じ全国データを
再取得し続けてしまう。取得済みの全国データをまとめてRedisへ書き戻せば、以後は
どの観測所への最初のアクセスもキャッシュヒットになる。

観測値本体はRedis Hash（`jma:amedas:{station_id}`、TTL 900秒）でキャッシュする——
気象データは5〜10分で失効する短命データのためPostGISには書き込まず、Redis上で
完結させる設計（CLAUDE.md「JMA気象データ連携・キャッシュ基盤」節参照）。

バッチ間隔（AMEDAS_REFRESH_INTERVAL_MINUTES）は気象庁アメダスの公式仕様（毎正時から
10分おきに観測・配信）に合わせた10分にしている（ユーザー指示2026-08-29「気象庁側の
更新頻度に合わせて」、および「（暫定的だった）10分とかは適当な数字なので最適化して」を
受け、実際の公式更新周期で裏付けた値へ変更）。TTL（15分）はバッチ間隔より長く取ることで、
1回のバッチ実行が遅延・失敗しても次の成功まで古い値のまま動作を続けられる安全マージンに
なっている。失敗はWARNINGで可視化される（main.py: _refresh_amedas_job、外部API呼び出し
自体の詳細はjma_amedas_client.py内のlog_external_callが別途出す）。
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app.domain.geo import LatLonPoint, haversine_distance_km
from app.domain.jma_amedas import (
    AmedasObservation,
    apparent_temperature_from_amedas,
    wind_direction_degrees_from_jma_code,
    wind_direction_label_from_jma_code,
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

logger = logging.getLogger("app.services.jma_amedas_service")

_JST = ZoneInfo("Asia/Tokyo")
_REDIS_KEY_PREFIX = "jma:amedas"
_REDIS_TTL_SECONDS = 15 * 60
# バッチ実行間隔（main.py参照）。上のモジュールdocstring「バッチ間隔」節を参照。
AMEDAS_REFRESH_INTERVAL_MINUTES = 10


def _redis_key(station_id: str) -> str:
    return f"{_REDIS_KEY_PREFIX}:{station_id}"


def _nearest_station(stations: dict, point: Coordinates) -> str | None:
    """最寄り観測所のstation_idを返す。"""
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
        """最寄り観測所を解決し、Redisにキャッシュ済みの観測値を返す（Redis読み取りのみ、
        JMAへは問い合わせない）。バッチがまだ一度も成功していない・Redis自体が不通、
        または最寄り観測所が風向風速・気温センサーを持たない種別（雨量計のみ等）の場合は
        Noneを返す（router側で502として扱う）。"""
        stations = await jma_amedas_client.fetch_station_table(self._http_client)
        if not stations:
            return None
        station_id = _nearest_station(stations, point)
        if station_id is None:
            return None
        observation = await self._get_from_redis(station_id)
        if observation is None:
            return None
        # 日の出/日没はJMA/Open-Meteoに問い合わせず、クエリ地点そのものに対してその場で
        # ローカル計算する（改善計画T387フォローアップ）。最寄り観測所の位置ではなく
        # リクエストのpointを使う（観測所境界付近でのわずかなズレを避けるため、かつ
        # Redisキャッシュ済みの観測値と違い計算コストが無視できるほど軽いため都度計算で
        # 問題ない）。
        today = datetime.now(_JST).date()
        sunrise, sunset = sunrise_sunset_jst(point, today)
        return observation.model_copy(update={"sunrise": sunrise, "sunset": sunset})

    async def _get_from_redis(self, station_id: str) -> AmedasObservation | None:
        if not redis_available():
            return None
        client = get_redis_client_or_none()
        if client is None:
            return None
        try:
            fields = await client.hgetall(_redis_key(station_id))
        except Exception as exc:  # noqa: BLE001 Redis障害は「観測値なし」にfail-open
            record_redis_failure()
            log_throttled_warning("cache:jma-amedas-redis", "[cache:jma-amedas-redis] read failed error=%r", exc)
            return None
        record_redis_success()
        if not fields:
            return None
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
            # sunrise/sunsetはRedisに保存しない（クエリ地点依存のためget_nearest_observation
            # がこの後で都度埋める）。ここでは常にNoneのプレースホルダ。
            sunrise=None,
            sunset=None,
        )

    async def refresh_all_stations(self) -> int:
        """全国のアメダス観測値を1回取得し、観測所ごとにRedisへ書き戻す（main.pyの
        定期バッチから呼ばれる）。戻り値は書き込んだ観測所数（0は取得失敗またはデータ無し）。
        """
        stations = await jma_amedas_client.fetch_station_table(self._http_client)
        if not stations:
            # 改善計画T425（ゼロベース網羅レビュー指摘）: 以前はここから静かに0を返しており、
            # 呼び出し元main.py: _refresh_amedas_jobは例外の有無しか見ていないため
            # count=0の全滅バッチが完全に無警告のまま繰り返される可能性があった
            # （個別の外部API呼び出し詳細はjma_amedas_client.py内のlog_external_callが
            # 出すが、「今回のバッチが実質何もできなかった」というサービス層の要約は無い）。
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
                    wind_direction_deg=wind_direction_degrees_from_jma_code(wind_direction_code),
                    wind_direction_label=wind_direction_label_from_jma_code(wind_direction_code),
                    precipitation_10min_mm=_first_value(raw.get("precipitation10m")),
                    sunshine_10min_minutes=_first_value(raw.get("sun10m")),
                    # クエリ地点依存のためバッチ時点では決められない（get_nearest_observation参照）。
                    sunrise=None,
                    sunset=None,
                )
            )
        await self._save_all_to_redis(observations)
        return len(observations)

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
    """JMAの[値, 品質フラグ]配列から値を取り出す。フィールド自体が無い観測所（雨量計のみ等）
    はNoneのまま返す（品質フラグの詳細な意味は判定せず、値の有無だけを見る簡略化——
    他のJMA/Open-Meteo連携と同じ「取得できないのは正常」というfail-open方針に合わせる）。"""
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
