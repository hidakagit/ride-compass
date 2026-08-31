"""Redis共有クライアント（改善計画T387）。

JMA気象データ（アメダス・降水ナウキャスト・MSM）の短命キャッシュ、および
road_graph_tilesタイル取得済みマーカーのcache-aside層（road_graph_tile_cache.py）が使う
共有接続。httpx.AsyncClient（http_client.py）と同じ「プロセス全体で1つを使い回す」方針。

すべての用途がTTL付きキャッシュ、またはPostGIS（正本）へ即座にフォールバック可能な
cache-asideのため、Redis接続自体の障害はfail-fastさせない（呼び出し元がtry/exceptで
握りつぶし、キャッシュ無し相当として本処理へ進む。road_graph_tile_cache.py参照）。
main.pyのlifespanでも疎通確認は行わない（axis_definitionsと違い、Redisが一時的に
使えないこと自体はアプリの起動を妨げるべき障害ではないため）。

**接続タイムアウトを明示的に短く設定する**: redis-pyの既定タイムアウトのままだと、
Redisが疎通不能な環境で1回の接続試行に数秒（実測、Windows開発機でConnectionError発生まで
約4秒）かかることが判明した。これはroad_graph_tile_cache.pyがルート生成の
リクエストごとに参照するホットパスのため、Redis障害時にこの遅延がそのまま乗ると
「PostGIS往復を減らして高速化する」という本来の目的に反して大幅な悪化になる。

**サーキットブレーカー**: 上記の短縮タイムアウト（0.2秒）を適用してもなお、Redis障害中は
毎リクエストその0.2秒を払い続けることになる。`redis_available()`は直近の失敗から
_CIRCUIT_COOLDOWN_SECONDS以内なら`False`を返し、呼び出し元はRedis自体への接続試行を
スキップして即座にPostGISへフォールバックできる（`record_redis_failure`/
`record_redis_success`で状態を更新する）。テストでは`reset_circuit_breaker`でリセットする
（tests/conftest.py参照）。
"""

import time

import redis.asyncio as redis

from app.config import settings

_client: redis.Redis | None = None

# 接続確立・コマンド応答の待ち上限。デフォルト値のままだと疎通不能時の1回の失敗検知が
# 数秒かかる（モジュールdocstring参照）。ローカルネットワーク内（本番はOCI VM上で
# --network=host、開発はdocker-compose同一ネットワーク）を前提に、正常時は決して
# 到達しない短い値へ絞る。
_CONNECT_TIMEOUT_SECONDS = 0.2
_SOCKET_TIMEOUT_SECONDS = 0.2

_CIRCUIT_COOLDOWN_SECONDS = 10.0
_last_failure_at: float | None = None


def get_redis_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=_CONNECT_TIMEOUT_SECONDS,
            socket_timeout=_SOCKET_TIMEOUT_SECONDS,
            retry_on_timeout=False,
        )
    return _client


def get_redis_client_or_none() -> redis.Redis | None:
    """`get_redis_client()`のfail-open版（改善計画T464）。

    `redis.from_url()`はURLスキーム不正（`settings.redis_url`の設定ミス）等で同期的に
    例外を送出しうる。この関数の呼び出し元（各cache-asideモジュール）は`client =
    get_redis_client()`の直後にある`try/except`で実際のRedisコマンド呼び出しの障害は
    fail-openにできているが、クライアント生成自体の例外はそのtry/exceptの外で起きるため
    捕捉されず、モジュールdocstringが謳う「Redis自体の障害はfail-fastさせない」契約を
    破ってルート生成・タイル配信自体を落としうる。ここで先んじて捕捉し、通常のRedis
    コマンド障害と同じ`record_redis_failure()`を記録した上でNoneを返す——呼び出し元は
    Noneを見て通常のfail-open（PostGIS等の正本へフォールバック）経路へ進めばよい。
    """
    try:
        return get_redis_client()
    except Exception:
        record_redis_failure()
        return None


def redis_available() -> bool:
    """直近のRedis障害からクールダウン期間を過ぎているか（＝呼び出す価値があるか）を返す。"""
    if _last_failure_at is None:
        return True
    return time.monotonic() - _last_failure_at >= _CIRCUIT_COOLDOWN_SECONDS


def record_redis_failure() -> None:
    global _last_failure_at
    _last_failure_at = time.monotonic()


def record_redis_success() -> None:
    global _last_failure_at
    _last_failure_at = None


def reset_circuit_breaker() -> None:
    """テスト用: サーキットブレーカーの状態をクリアする（tests/conftest.py参照）。"""
    global _last_failure_at
    _last_failure_at = None
