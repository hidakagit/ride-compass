"""JMA高解像度降水ナウキャストのタイル配信支援サービス（改善計画T387）。

このサービスはナウキャストのPNGタイル本体を取得・中継しない。MapLibre等が直接JMAの
タイルURLを参照できるよう、(1) 最新の発表時刻（basetime/validtime）の解決と
URLテンプレートの組み立て、(2) 個々のタイル座標が「取得済み」かどうかを判定する
Redisベースのフラグ管理ヘルパー、の2つに責務を絞る（CLAUDE.md指示の機能②の
スコープどおり。フロント側でのタイル表示配線・実際のPNG中継キャッシュは別タスクとする）。

最新時刻の情報自体もRedis（`jma:nowcast:latest`）へ短命キャッシュする——JMAデータは
PostGISへ書き込まずRedis上で完結させる方針（CLAUDE.md「JMA気象データ連携・キャッシュ
基盤」節）。
"""

import logging

import httpx

from app.infrastructure import jma_tile_client
from app.infrastructure.debug_log import log_throttled_warning
from app.infrastructure.redis_client import (
    get_redis_client,
    record_redis_failure,
    record_redis_success,
    redis_available,
)

logger = logging.getLogger("app.services.jma_tile_service")

_NOWCAST_TILE_URL_TEMPLATE = (
    "https://www.jma.go.jp/bosai/jmatile/data/nowc/{basetime}/none/{validtime}/surf/hrpns/{{z}}/{{x}}/{{y}}.png"
)

# 気象庁の高解像度降水ナウキャストは公式仕様で5分間隔で発表される（ユーザー指示
# 2026-08-29「気象庁側の更新頻度に合わせて」「10分とかは適当な数字なので最適化して」を
# 受け、実際の公式配信周期で裏付けた値）。main.pyの定期バッチ間隔
# （NOWCAST_REFRESH_INTERVAL_MINUTES）もこれに合わせて5分にする。
NOWCAST_REFRESH_INTERVAL_MINUTES = 5

_LATEST_REDIS_KEY = "jma:nowcast:latest"
# バッチ間隔（5分）の2倍にしておくことで、1回のバッチ失敗を吸収できる安全マージンを
# 持たせる（バッチ間隔と同値だと、失敗直後のリクエストがそのままJMAへの同期フェッチに
# 落ちてしまいレイテンシが乗る）。
_LATEST_TTL_SECONDS = 10 * 60

_TILE_FETCHED_KEY_PREFIX = "jma:tile:fetched"
# タイルはbasetime/validtimeが5分ごとに変わるため、フラグも同じ周期で自然に無効化されて
# よい（basetimeをキーへ明示的に含めなくても、TTL経由で実質「今のナウキャストに対する
# 取得済みフラグ」として機能する）。
_TILE_FETCHED_TTL_SECONDS = 5 * 60


def _tile_fetched_key(z: int, x: int, y: int) -> str:
    return f"{_TILE_FETCHED_KEY_PREFIX}:{z}:{x}:{y}"


class NowcastTimestamp:
    """ナウキャストの最新basetime/validtimeとタイルURLテンプレート。"""

    def __init__(self, basetime: str, validtime: str):
        self.basetime = basetime
        self.validtime = validtime

    @property
    def tile_url_template(self) -> str:
        """{z}/{x}/{y}のプレースホルダを残したタイルURL（MapLibreのraster sourceにそのまま渡せる形）。"""
        return _NOWCAST_TILE_URL_TEMPLATE.format(basetime=self.basetime, validtime=self.validtime)


async def get_latest_nowcast_timestamp(http_client: httpx.AsyncClient) -> NowcastTimestamp | None:
    """最新のナウキャスト実況（"hrpns"要素を持つ最新basetime＝validtime）のタイムスタンプを返す。

    Redisに直近の結果があればそれを使い、無ければJMAへ問い合わせて書き戻す。
    """
    cached = None
    if redis_available():
        client = get_redis_client()
        try:
            cached = await client.hgetall(_LATEST_REDIS_KEY)
        except Exception as exc:  # noqa: BLE001 Redis障害はJMAへの直接取得にfail-open
            record_redis_failure()
            log_throttled_warning("cache:jma-nowcast-redis", "[cache:jma-nowcast-redis] read failed error=%r", exc)
            cached = None
        else:
            record_redis_success()
    if cached:
        return NowcastTimestamp(basetime=cached["basetime"], validtime=cached["validtime"])

    target_times = await jma_tile_client.fetch_target_times(http_client)
    if not target_times:
        return None
    # "hrpns"（高解像度降水ナウキャスト実況+予測の現況コマ）を含むエントリの先頭が最新実況。
    latest = next((entry for entry in target_times if "hrpns" in entry.get("elements", [])), None)
    if latest is None:
        return None
    timestamp = NowcastTimestamp(basetime=latest["basetime"], validtime=latest["validtime"])

    if redis_available():
        client = get_redis_client()
        try:
            await client.hset(
                _LATEST_REDIS_KEY, mapping={"basetime": timestamp.basetime, "validtime": timestamp.validtime}
            )
            await client.expire(_LATEST_REDIS_KEY, _LATEST_TTL_SECONDS)
        except Exception as exc:  # noqa: BLE001 書き込み失敗は戻り値の成否に影響しない
            record_redis_failure()
            log_throttled_warning("cache:jma-nowcast-redis", "[cache:jma-nowcast-redis] write failed error=%r", exc)
        else:
            record_redis_success()
    return timestamp


async def is_tile_fetched(z: int, x: int, y: int) -> bool:
    """指定タイルが（現在のナウキャストコマについて）取得済みとマークされているかを返す。
    Redis障害時はFalse（未取得扱い）を返す——fail-openの方向を「毎回律儀に取得し直す」側へ
    倒すことで、フラグ喪失時に「実際は変わっているのに古いタイルを表示し続ける」事故を防ぐ。"""
    if not redis_available():
        return False
    client = get_redis_client()
    try:
        result = bool(await client.exists(_tile_fetched_key(z, x, y)))
    except Exception as exc:  # noqa: BLE001
        record_redis_failure()
        log_throttled_warning("cache:jma-tile-redis", "[cache:jma-tile-redis] read failed error=%r", exc)
        return False
    record_redis_success()
    return result


async def mark_tile_fetched(z: int, x: int, y: int) -> None:
    """タイルの取得完了をマークする。書き込み失敗はレスポンス自体には影響しない。"""
    if not redis_available():
        return
    client = get_redis_client()
    try:
        await client.set(_tile_fetched_key(z, x, y), "1", ex=_TILE_FETCHED_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        record_redis_failure()
        log_throttled_warning("cache:jma-tile-redis", "[cache:jma-tile-redis] write failed error=%r", exc)
    else:
        record_redis_success()
