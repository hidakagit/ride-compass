import asyncio
import re

import httpx
from cachetools import TTLCache

from app.infrastructure import tile_cache
from app.infrastructure.debug_log import error_type_label, log_external_call

# JMA bosai タイル/時刻一覧API（降水ナウキャスト・降水短時間予報・雷/竜巻ナウキャスト・
# キキクル・線状降水帯予測マップ、dynamicWeather.ts「動的気象レイヤー」節参照）を透過的に
# プロキシする（改善計画T412）。basemap_client.pyと同じ「path丸ごとプロキシ」方式だが、
# targetTimes.json（数分〜数十分単位で更新される時刻一覧）とラスタタイル本体
# （basetime/validtime/z/x/yが確定した時点で内容が不変、OpenFreeMapタイルと同じ性質）で
# キャッシュ戦略を分ける必要がある。basemap_client.pyのtile_cache（永続ファイルキャッシュ）を
# そのままtargetTimes.jsonへ使うと、更新後も古い時刻一覧を無期限に返し続けてしまう。
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

    async def get(self, path: str) -> tuple[bytes, str] | None:
        is_target_times = _TARGET_TIMES_PATTERN.search(path) is not None
        with log_external_call("weather:jma-tile", path=path) as fields:
            if is_target_times:
                cached = _target_times_cache.get(path)
            else:
                # tile_cacheの読み書きは同期的なディスクI/O（basemap_client.pyと同じ理由で
                # asyncio.to_threadへ逃がす）。
                cached = await asyncio.to_thread(tile_cache.get, path)
            if cached is not None:
                fields["cache"] = "hit"
                return cached
            fields["cache"] = "miss"

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
                await asyncio.to_thread(tile_cache.set, path, content, content_type)
            return result
