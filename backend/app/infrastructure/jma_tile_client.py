import re

import httpx
from cachetools import TTLCache

from app.infrastructure import jma_tile_redis_cache
from app.infrastructure.debug_log import error_type_label, log_external_call

# JMA bosai タイル/時刻一覧API（降水ナウキャスト・降水短時間予報・雷/竜巻ナウキャスト・
# キキクル・線状降水帯予測マップ、dynamicWeather.ts「動的気象レイヤー」節参照）を透過的に
# プロキシする（改善計画T412）。basemap_client.pyと同じ「path丸ごとプロキシ」方式だが、
# targetTimes.json（数分〜数十分単位で更新される時刻一覧）とラスタタイル本体
# （basetime/validtime/z/x/yが確定した時点で内容が不変、OpenFreeMapタイルと同じ性質）で
# キャッシュ戦略を分ける必要がある。改善計画T510: タイル本体はファイル永続キャッシュ
# （tile_cache.py、有効期限なし）からRedis cache-aside（jma_tile_redis_cache.py、TTL付き）へ
# 移した——キャッシュヒットでも`jma_tile.py`のレート制限を消費していた問題（429の直接原因）
# を、キャッシュ参照をレート制限より先に行う構成へ入れ替えるにあたり、無期限に肥大化する
# ファイルキャッシュより定期プリウォーム（jma_tile_prewarm_service.py）と相性の良いTTL付き
# キャッシュへ揃える判断をした。
UPSTREAM_HOST = "https://www.jma.go.jp"

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


class JmaTileClient:
    """JMAの動的タイル系レイヤーが使うbosaiエンドポイント（時刻一覧JSON・ラスタタイルPNG）の
    プロキシ＋キャッシュ。改善計画T412: 従来これらはフロントエンド（各ユーザーのブラウザ）が
    直接JMAへfetchしており、常時ON化（実機フィードバック「キキクルのような防災級の情報は
    ユーザー操作を待たず表示すべき」）の前提として、利用者数に比例してJMAの非公式内部APIへの
    負荷が線形に増えない構成へ切り替える。
    """

    def __init__(self, http_client: httpx.AsyncClient):
        self._http_client = http_client

    async def get_cached(self, path: str) -> tuple[bytes, str] | None:
        """キャッシュのみを参照する（外部フェッチはしない）。改善計画T510:
        `jma_tile.py`がレート制限を適用する前にこれを呼び、ヒットすればレート制限を
        一切経由せず即座に返せるようにする（キャッシュヒットでもレート制限を消費して
        いた429の直接原因への対応）。"""
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
        呼び出し元（`jma_tile.py`）はレート制限を適用済みである前提。"""
        is_target_times = _TARGET_TIMES_PATTERN.search(path) is not None
        with log_external_call("weather:jma-tile", path=path, cache="miss") as fields:
            try:
                response = await self._http_client.get(f"{UPSTREAM_HOST}/{path}")
                response.raise_for_status()
            except httpx.HTTPError as exc:
                fields["result"] = "error"
                fields["error"] = repr(exc)
                fields["error_type"] = error_type_label(exc)
                return None

            fields["result"] = "ok"
            fields["status"] = getattr(response, "status_code", None)
            content_type = response.headers.get("content-type", "application/octet-stream")
            content = response.content
            result = (content, content_type)
            if is_target_times:
                _target_times_cache[path] = result
            else:
                await jma_tile_redis_cache.set(path, content, content_type)
            return result

    async def get(self, path: str) -> tuple[bytes, str] | None:
        """キャッシュ参照→ミスなら外部フェッチ、という従来通りの一括呼び出し。
        レート制限の適用順序を気にしない呼び出し元（プリウォームバッチ・テスト等）向け。"""
        cached = await self.get_cached(path)
        if cached is not None:
            return cached
        return await self.fetch(path)
