"""JMA高解像度降水ナウキャストのタイムスタンプAPIクライアント（改善計画T387）。

jma_warning_client.py・jma_amedas_client.pyと同じ「JMA公式の非公開だが広く使われている
エンドポイント」を使う。ナウキャスト自体（PNGタイル本体）はここでは取得せず、
MapLibre等がタイルを直接参照するためのURL組み立てに必要なタイムスタンプ
（basetime/validtime）だけを扱う（jma_tile_service.py参照）。
"""

import httpx

from app.infrastructure.debug_log import error_type_label, log_external_call

NOWCAST_TARGET_TIMES_URL = "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json"

REQUEST_TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)


async def fetch_target_times(client: httpx.AsyncClient) -> list | None:
    """ナウキャストの発表時刻一覧（[{"basetime", "validtime", "elements"}, ...]）を取得する。

    キャッシュはここでは持たない（呼び出し元jma_tile_service.pyがRedis上でTTL管理する。
    CLAUDE.md「JMA気象データ連携・キャッシュ基盤」節: JMAデータはRedisで完結させる方針）。
    """
    with log_external_call("weather:jma-nowcast-times") as fields:
        try:
            response = await client.get(NOWCAST_TARGET_TIMES_URL, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            return None
        if not isinstance(data, list) or not data:
            fields["result"] = "error"
            fields["error_type"] = "unexpected_shape"
            return None
        fields["result"] = "ok"
        return data
