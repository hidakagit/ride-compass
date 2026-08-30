"""気象グリッド（風・降水延長予報、`weather_client.py: get_forecast_many`）のRedis
cache-asideキャッシュ（改善計画T398）。

`weather_client.py`側のプロセス内メモリ辞書（L1）がヒットしなかったキーだけをここ（L2）が
引く2段構成のL2を担う。以前は`cache_db.py`（SQLite、`backend/data/ridecompass_cache.db`）が
この役割を持っていたが、JMAアメダス連携（改善計画T387）で導入済みのRedisへ基盤を1本化した
（同居するVM上に既にRedisが稼働しているため、新たにSQLiteファイルの永続化を維持する理由が
無くなったため）。

**正本を持たないキャッシュ**: road_graph_tile_cache.pyのタイル取得済みマーカーと異なり、
このキャッシュを失っても「データ未整備で機能が壊れる」ことはない（Open-Meteoへ再取得すれば
よいだけ）。そのためPostGISのようなフォールバック正本は無く、Redis自体が唯一の永続化層に
なる。ただし失敗時はweather_client.py側が単に「未キャッシュ」として扱い実フェッチへ進む
fail-openのため、Redis障害時も機能は止まらない（Open-Meteo 429リトライの頻度が上がるだけ）。

TTLは`weather_client.WIND_GRID_STALE_FALLBACK_MAX_AGE_SECONDS`（24時間、フェッチ失敗時に
このキャッシュを代用してよい上限）に合わせている。それを超えたエントリはどのみち
weather_client.py側のstale fallback判定でも使われなくなるため、Redis側で先に消えても
挙動は変わらない（`fetched_at`ベースの新鮮/陳腐判定は引き続きweather_client.py側が担う。
このモジュールは「保存されているか・いつのものか」を返すだけの薄い層のまま）。
"""

import json

from app.infrastructure.debug_log import error_type_label, log_external_call
from app.infrastructure.redis_client import (
    get_redis_client_or_none,
    record_redis_failure,
    record_redis_success,
    redis_available,
)

_KEY_PREFIX = "wind:forecast"
_TTL_SECONDS = 24 * 60 * 60


def _key(lat: float, lon: float) -> str:
    return f"{_KEY_PREFIX}:{lat}:{lon}"


async def get_wind_forecast_many(
    keys: list[tuple[float, float]],
) -> dict[tuple[float, float], tuple[float, dict]]:
    """Redisキャッシュから、渡したキーのうち見つかった分だけを{(lat,lon): (fetched_at, data)}
    で返す（TTL/新鮮度判定は呼び出し側が行う）。Redis自体が疎通不能な場合は空辞書を返す
    （fail-open、呼び出し元は実フェッチへ進む）。"""
    if not keys or not redis_available():
        return {}
    client = get_redis_client_or_none()
    if client is None:
        return {}
    redis_keys = [_key(lat, lon) for lat, lon in keys]
    with log_external_call("cache:wind-forecast-redis", key_count=len(keys)) as fields:
        try:
            values = await client.mget(redis_keys)
        except Exception as exc:  # noqa: BLE001 Redis障害は「未キャッシュ」へのfail-open対象
            record_redis_failure()
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            return {}
        record_redis_success()

        result: dict[tuple[float, float], tuple[float, dict]] = {}
        for key, raw in zip(keys, values):
            if raw is None:
                continue
            try:
                fetched_at, data = json.loads(raw)
            except (ValueError, TypeError):
                # 壊れたエントリ（手動編集・フォーマット変更等）は未キャッシュ扱いにする。
                continue
            result[key] = (fetched_at, data)
        fields["result"] = "ok"
        fields["cache"] = "hit" if result else "miss"
        return result


async def set_wind_forecast_many(entries: dict[tuple[float, float], tuple[float, dict]]) -> None:
    """新規に取得できた気象グリッドの応答をRedisへ書き戻す（キャッシュの最適化であり、
    書き込み失敗はレスポンス自体の成否には関与しない。失敗時は抑制付きWARNINGで記録する
    だけに留める）。"""
    if not entries or not redis_available():
        return
    client = get_redis_client_or_none()
    if client is None:
        return
    with log_external_call("cache:wind-forecast-redis", entry_count=len(entries)) as fields:
        try:
            pipe = client.pipeline(transaction=False)
            for (lat, lon), (fetched_at, data) in entries.items():
                pipe.set(_key(lat, lon), json.dumps([fetched_at, data]), ex=_TTL_SECONDS)
            await pipe.execute()
        except Exception as exc:  # noqa: BLE001 書き込み失敗は次回フェッチで自己修復する
            record_redis_failure()
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
        else:
            record_redis_success()
            fields["result"] = "ok"
