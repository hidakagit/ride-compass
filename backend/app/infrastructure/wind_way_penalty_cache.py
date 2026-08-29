"""way_id→wind_penalty配信層（改善計画T405）専用のRedis cache-asideキャッシュ。

`wind_forecast_cache.py`（風グリッド地点そのもののキャッシュ）とは別レイヤー。こちらは
`WindWayService`が風グリッド値とway自身のbearing_degから計算した**wayごとの評価値
（wind_penalty、m/s単位のスカラー）**をキャッシュする。T400.md「2. 動的要素…の二重表現」節の
指示どおり`way_id`をキーにする——同じwayが複数タイル・複数ズームレベルにまたがって現れても
（隣接タイル・親子タイルで重複するway、パン・ズームのたびの再訪等）、bearing_degの再取得
（DB問い合わせ）はタイル単位で毎回行うが、wind_penaltyの再計算自体はway単位でキャッシュ
共有できる。

キーには時刻の1時間バケット（`YYYY-MM-DDTHH`）を含める。風グリッド自体は複数時刻ぶんの
hourly配列を持ち、`WindWayService`は要求時刻に最も近い時刻のindexを都度選ぶため、同じ
way_idでも時刻が1時間跨げば別の値になりうる（バケットを持たないと、風が変わってもTTLが
切れるまで古い時刻の値を返し続けてしまう）。TTLは`weather_client.WIND_GRID_CACHE_TTL_SECONDS`
（風グリッドの新鮮判定TTL、3時間）に合わせる——バケット自体がキーに含まれるため、TTLは
正しさの担保ではなく単なるRedis側の自動ガベージコレクション（無限に古いバケットのキーが
溜まり続けるのを防ぐ）としての役割になる。

**正本を持たないキャッシュ**（wind_forecast_cache.pyと同じ性質）: 失っても風グリッド・
bearing_degから再計算すればよいだけで、失敗時はfail-open（未キャッシュとして扱い実計算へ
進む）。Redis障害時も機能は止まらない（再計算コストが少し増えるだけ）。
"""

from app.infrastructure.debug_log import log_throttled_warning
from app.infrastructure.redis_client import (
    get_redis_client,
    record_redis_failure,
    record_redis_success,
    redis_available,
)
from app.infrastructure.weather_client import WIND_GRID_CACHE_TTL_SECONDS

_KEY_PREFIX = "wind:way-penalty"
_TTL_SECONDS = WIND_GRID_CACHE_TTL_SECONDS


def _key(osm_way_id: int, hour_bucket: str) -> str:
    return f"{_KEY_PREFIX}:{osm_way_id}:{hour_bucket}"


async def get_way_penalties_many(way_ids: list[int], hour_bucket: str) -> dict[int, float]:
    """指定した`way_id`のうちRedisに見つかった分だけを{way_id: wind_penalty}で返す。
    Redis自体が疎通不能な場合は空辞書を返す（fail-open、呼び出し元は未キャッシュ分の
    実計算へ進む）。"""
    if not way_ids or not redis_available():
        return {}
    client = get_redis_client()
    keys = [_key(way_id, hour_bucket) for way_id in way_ids]
    try:
        values = await client.mget(keys)
    except Exception as exc:  # noqa: BLE001 Redis障害は「未キャッシュ」へのfail-open対象
        record_redis_failure()
        log_throttled_warning("cache:wind-way-penalty-redis", "[cache:wind-way-penalty-redis] read failed error=%r", exc)
        return {}
    record_redis_success()

    result: dict[int, float] = {}
    for way_id, raw in zip(way_ids, values):
        if raw is None:
            continue
        try:
            result[way_id] = float(raw)
        except (ValueError, TypeError):
            # 壊れたエントリ（手動編集等）は未キャッシュ扱いにする。
            continue
    return result


async def set_way_penalties_many(entries: dict[int, float], hour_bucket: str) -> None:
    """新規に計算できたway_idごとのwind_penaltyをRedisへ書き戻す（キャッシュの最適化であり、
    書き込み失敗はレスポンス自体の成否には関与しない。失敗時は抑制付きWARNINGで記録する
    だけに留める）。"""
    if not entries or not redis_available():
        return
    client = get_redis_client()
    try:
        pipe = client.pipeline(transaction=False)
        for way_id, value in entries.items():
            pipe.set(_key(way_id, hour_bucket), str(value), ex=_TTL_SECONDS)
        await pipe.execute()
    except Exception as exc:  # noqa: BLE001 書き込み失敗は次回の実計算で自己修復する
        record_redis_failure()
        log_throttled_warning("cache:wind-way-penalty-redis", "[cache:wind-way-penalty-redis] write failed error=%r", exc)
    else:
        record_redis_success()
