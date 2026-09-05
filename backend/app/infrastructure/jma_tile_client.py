import asyncio
import re
import time

import httpx
from cachetools import TTLCache

from app.config import settings
from app.infrastructure import jma_tile_redis_cache
from app.infrastructure.debug_log import error_type_label, log_external_call
from app.infrastructure.jma_tile_redis_cache import TileNotFound

# JMA bosai タイル/時刻一覧API（降水ナウキャスト・降水短時間予報・雷/竜巻ナウキャスト・
# キキクル・線状降水帯予測マップ、dynamicWeather.ts「動的気象レイヤー」節参照）を透過的に
# プロキシする。basemap_client.pyと同じ「path丸ごとプロキシ」方式だが、
# targetTimes.json（数分〜数十分単位で更新される時刻一覧）とラスタタイル本体
# （basetime/validtime/z/x/yが確定した時点で内容が不変、OpenFreeMapタイルと同じ性質）で
# キャッシュ戦略を分ける（詳細はdocs/modules/backend/weather-dynamic-layers.md
# 「JMAタイル系の共通プロキシ」節参照）。
UPSTREAM_HOST = "https://www.jma.go.jp"


class JmaTileNotFoundError(Exception):
    """指定パスが上流（JMA）に存在しない（404）。降水・浸水想定区域等の疎な格子状タイルは
    ズームレベル・場所によって存在しないz/x/yが珍しくないため、タイムアウトや5xx等の
    他の失敗と区別し、`jma_tile.py`が502ではなく404を返す判断材料にする。"""

# targetTimes*.jsonは実況・ナウキャスト系で5〜10分おき、キキクル系でも10分おきに更新される
# （riskMap.ts/precipitationNowcast.tsのコメント参照）。TTLは更新間隔より十分短く、かつ
# 同一TTL窓内の多数ユーザーがキャッシュを共有できる程度の長さとして2分を選んだ。
_TARGET_TIMES_TTL_SECONDS = 2 * 60
# 同時に存在しうる時刻一覧の種類（nowc N1/N2/N3・rasrf・risk）は高々数個のため、
# 余裕を持たせても小さい上限で足りる。
_target_times_cache: TTLCache = TTLCache(maxsize=16, ttl=_TARGET_TIMES_TTL_SECONDS)

# targetTimes_N1.json / targetTimes_N2.json / targetTimes_N3.json / targetTimes.json のいずれも
# 末尾がtargetTimes*.jsonという共通パターンを持つ。
_TARGET_TIMES_PATTERN = re.compile(r"targetTimes[^/]*\.json$")

# JMA非公式APIへの実フェッチ（fetch）を秒間settings.jma_tile_upstream_
# max_requests_per_second回までに抑える。`JmaTileClient`はリクエストごとに使い捨てで
# インスタンス化される（api/dependencies.py: get_jma_tile_client、
# _prewarm_jma_tile_job）ため、プロセス全体で共有する状態はモジュールレベルで持つ
# （_target_times_cacheと同じ理由）。backendはuvicornをワーカー数指定無し＝単一プロセスで
# 起動する構成（Dockerfile参照）のため、プロセス内の状態だけで実際の総リクエスト数を
# 正しく制御できる。
_rate_limit_lock = asyncio.Lock()
_last_fetch_at: float | None = None


async def _wait_for_upstream_rate_limit() -> None:
    """直前の実フェッチから`1/jma_tile_upstream_max_requests_per_second`秒未満しか
    経っていなければ、その差分だけ待つ。キャッシュヒット（get_cached）はこの待機の
    対象外——実際にJMAへ問い合わせる直前（fetch）でのみ呼ぶ。"""
    global _last_fetch_at
    min_interval = 1.0 / settings.jma_tile_upstream_max_requests_per_second
    async with _rate_limit_lock:
        now = time.monotonic()
        if _last_fetch_at is not None:
            wait_seconds = _last_fetch_at + min_interval - now
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
        _last_fetch_at = time.monotonic()


class JmaTileClient:
    """JMAの動的タイル系レイヤーが使うbosaiエンドポイント（時刻一覧JSON・ラスタタイルPNG）の
    プロキシ＋キャッシュ。利用者数に比例してJMAの非公式内部APIへの負荷が線形に増えない
    構成にする。
    """

    def __init__(self, http_client: httpx.AsyncClient):
        self._http_client = http_client

    async def get_cached(self, path: str) -> tuple[bytes, str] | TileNotFound | None:
        """キャッシュのみを参照する（外部フェッチはしない）。
        `jma_tile.py`がレート制限を適用する前にこれを呼び、ヒットすればレート制限を
        一切経由せず即座に返せるようにする。`TileNotFound`（確認済みの恒久404）が
        返ることもあり、その場合`jma_tile.py`は上流へ問い合わせずそのまま404を返す。"""
        is_target_times = _TARGET_TIMES_PATTERN.search(path) is not None
        with log_external_call("weather:jma-tile", path=path) as fields:
            if is_target_times:
                cached = _target_times_cache.get(path)
            else:
                cached = await jma_tile_redis_cache.get(path)
            fields["result"] = "ok"
            fields["cache"] = "hit" if cached is not None else "miss"
            return cached

    async def fetch(self, path: str) -> tuple[bytes, str] | None:
        """キャッシュを一切参照せず外部フェッチのみ行い、結果をキャッシュへ書き戻す。
        呼び出し元（`jma_tile.py`）はレート制限を適用済みである前提。
        実際にJMAへ問い合わせる直前で`_wait_for_upstream_rate_limit`を待つ（プリウォーム
        バッチ・オンデマンドのfetch双方が経由するこの関数1箇所に置くことで、呼び出し元を
        問わずJMAへの総リクエスト数を一律に抑える）。待機自体は「実フェッチ」の所要時間
        ではないため、`log_external_call`の計測（elapsed_ms）に含めないよう、
        `with`ブロックへ入る前に済ませる。

        上流の404は`JmaTileNotFoundError`を送出する（疎な格子状タイルでは珍しくない正常系
        のため、`result="ok"`のまま記録しWARNINGを出さない。他の失敗はNoneを返す）。
        """
        await _wait_for_upstream_rate_limit()
        is_target_times = _TARGET_TIMES_PATTERN.search(path) is not None
        # not_found/resultは`with`ブロックの中で確定させ、実際のreturn/raiseは抜けた後で行う
        # （`log_external_call`はブロックを例外無しで抜けたときだけfields["result"]で
        # 成功/失敗を判定するため、404を非エラー扱いにするにはブロック内で例外を送出しない
        # 必要がある）。
        not_found = False
        result: tuple[bytes, str] | None = None
        with log_external_call("weather:jma-tile", path=path, cache="miss") as fields:
            try:
                response = await self._http_client.get(f"{UPSTREAM_HOST}/{path}")
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    fields["result"] = "ok"
                    fields["status"] = 404
                    not_found = True
                    # 恒久404をキャッシュし、次回以降は上流へ問い合わせず
                    # TileNotFoundで即座に済ませる（basetime/validtimeが確定した過去の
                    # 一時点への結果のため、再フェッチしても変わらない）。
                    if is_target_times:
                        _target_times_cache[path] = jma_tile_redis_cache.TILE_NOT_FOUND
                    else:
                        await jma_tile_redis_cache.set_not_found(path)
                else:
                    fields["result"] = "error"
                    fields["error"] = repr(exc)
                    fields["error_type"] = error_type_label(exc)
            except httpx.HTTPError as exc:
                fields["result"] = "error"
                fields["error"] = repr(exc)
                fields["error_type"] = error_type_label(exc)
            else:
                fields["result"] = "ok"
                fields["status"] = getattr(response, "status_code", None)
                content_type = response.headers.get("content-type", "application/octet-stream")
                content = response.content
                result = (content, content_type)
                if is_target_times:
                    _target_times_cache[path] = result
                else:
                    await jma_tile_redis_cache.set(path, content, content_type)
        if not_found:
            raise JmaTileNotFoundError(path)
        return result

    async def get(self, path: str) -> tuple[bytes, str] | None:
        """キャッシュ参照→ミスなら外部フェッチ、という従来通りの一括呼び出し。
        レート制限の適用順序を気にしない呼び出し元（プリウォームバッチ・テスト等）向け。
        `TileNotFound`（キャッシュ済みの恒久404）・`fetch`が送出する`JmaTileNotFoundError`は
        いずれもここでNoneへ揃える——呼び出し元（`jma_tile_prewarm_service.py`）は404を
        「取得失敗の1種」として件数集計するだけで、404と他の失敗を区別する必要が無い
        （区別が要るのはHTTPステータスを返す`jma_tile.py`のみ、そちらは`get_cached`/`fetch`を
        直接呼ぶ）。"""
        cached = await self.get_cached(path)
        if isinstance(cached, TileNotFound):
            return None
        if cached is not None:
            return cached
        try:
            return await self.fetch(path)
        except JmaTileNotFoundError:
            return None
