"""環境省 熱中症予防情報サイトのクライアント（改善計画T174）。

情報提供地点マスタ（CSV）と暑さ指数（WBGT）予測値取得WebAPI（JSON、`man15NH/
wbgt_data_api_service_manual.pdf`、2026-08-22取得のAPI仕様書を典拠）の2つを叩く。
サイト側の利用上の注意（wbgt_data_download.php）に「自動化ツールからの高頻度アクセスは
控えて」と明記されているため、weather_client.pyのような429前提のtenacity再試行は設けず、
TTLキャッシュで呼び出し頻度自体を抑える。取得失敗はNoneを返し、呼び出し元
（wbgt_service.py）が「警告なし」として扱う（T205のjma_warning_client.pyと同じ方針）。
"""

import csv
import io

import httpx
from cachetools import TTLCache

from app.domain.wbgt_points import WbgtPoint
from app.infrastructure.debug_log import error_type_label, log_external_call

# ファイル名に更新日が埋め込まれた命名規則（環境省サイト側の運用）のため、地点構成が
# 変わった際はURLごと差し替えが必要になる（自動追従の仕組みは無い。年1回程度の更新
# 頻度と見込まれるため、遭遇したら気づいて直す前提でハードコードする）。
WBGT_POINT_MASTER_URL = "https://www.wbgt.env.go.jp/man15NH/wbgt_point_master-20260515.csv"
WBGT_FORECAST_API_URL = "https://www.wbgt.env.go.jp/api/v1/getForecastData"

# 地点構成は年1回程度しか変わらないため長いTTL（jma_warning_client.pyのarea.jsonと同じ思想）。
_POINT_MASTER_CACHE_TTL_SECONDS = 24 * 60 * 60
# 予測値は3時間刻みでしか更新されないため、サイト側の注意書き（高頻度アクセスを控える）
# に配慮して1時間TTLとする。
_FORECAST_CACHE_TTL_SECONDS = 60 * 60

REQUEST_TIMEOUT = httpx.Timeout(connect=3.0, read=8.0, write=5.0, pool=5.0)

_POINT_MASTER_CACHE_KEY = "point_master"
_point_master_cache: TTLCache = TTLCache(maxsize=1, ttl=_POINT_MASTER_CACHE_TTL_SECONDS)
# forecast_no単位の粒度でキャッシュする（地点ごとに問い合わせ元の緯度経度は丸められて
# 同じ地点へ収束するため、地点番号キーで十分にキャッシュが効く）。maxsizeは全国の
# 情報提供地点数（約840地点）に十分な余裕を持たせた値。
_forecast_cache: TTLCache = TTLCache(maxsize=2048, ttl=_FORECAST_CACHE_TTL_SECONDS)


async def fetch_point_master(client: httpx.AsyncClient) -> list[WbgtPoint] | None:
    """情報提供地点マスタ（全国約840地点）を取得する。運用終了済み地点
    （End Year-End Month-End Dayが"9999-99-99"以外）は除外する。"""
    with log_external_call("weather:wbgt-point-master") as fields:
        cached = _point_master_cache.get(_POINT_MASTER_CACHE_KEY)
        if cached is not None:
            fields["cache"] = "hit"
            return cached
        fields["cache"] = "miss"
        try:
            response = await client.get(WBGT_POINT_MASTER_URL, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            points = _parse_point_master(response.text)
        except (httpx.HTTPError, ValueError) as exc:
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            return None
        fields["result"] = "ok"
        _point_master_cache[_POINT_MASTER_CACHE_KEY] = points
        return points


def _parse_point_master(csv_text: str) -> list[WbgtPoint]:
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    points: list[WbgtPoint] = []
    for row in rows[1:]:  # 先頭行はヘッダー
        if len(row) < 13:
            continue
        end_date = row[12].strip()
        if end_date != "9999-99-99":
            continue  # 運用終了済み地点は近傍検索の対象外
        try:
            no = row[2].strip()
            name = row[3].strip()
            latitude = float(row[7].strip()) + float(row[8].strip()) / 60.0
            longitude = float(row[9].strip()) + float(row[10].strip()) / 60.0
        except (ValueError, IndexError):
            continue  # 欠損行はスキップ（他地点で近傍検索を続行できる）
        points.append(WbgtPoint(no=no, name=name, latitude=latitude, longitude=longitude))
    return points


async def fetch_forecast(client: httpx.AsyncClient, wbgt_no: str, range_from: str, range_to: str) -> list[dict] | None:
    """指定地点の暑さ指数予測値列（3時間刻み、翌々日まで）を取得する。

    `range_from`/`range_to`はYYYYMMDDHHMMSS形式（発表時刻=reference_timeの検索範囲。
    呼び出し元が「現在時刻を含む直近N時間」を渡す想定）。date_search_type=3
    （特定時刻）は指定時刻ちょうどに発表（reference_time）が存在しないと空を返す
    厳格な一致検索であることが実機確認で判明した（2026-08-22: 20:00:00ちょうどを
    指定すると20時発表がまだ無く空、19:00:00なら19時発表がヒット）。発表は概ね毎時
    行われるが遅延もありうるため、date_search_type=1（連続期間指定）で直近の発表を
    幅広く取得し、複数の発表回（reference_time）が返ってきた場合は呼び出し元
    （wbgt_service.py）が最新の発表回だけを使う。
    レスポンスの`forecast_val`は暑さ指数を10倍した整数文字列（実機確認、2026-08-22:
    東京地点でforecast_val="280"→暑さ指数28.0）のため、呼び出し元で10で割ること。
    """
    with log_external_call("weather:wbgt-forecast", wbgt_no=wbgt_no) as fields:
        cached = _forecast_cache.get(wbgt_no)
        if cached is not None:
            fields["cache"] = "hit"
            return cached
        fields["cache"] = "miss"
        params = {
            "location_type": 1,
            "date_search_type": 1,
            "wbgt_nos": wbgt_no,
            "range_date_from": range_from,
            "range_date_to": range_to,
        }
        try:
            response = await client.get(WBGT_FORECAST_API_URL, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            return None
        if body.get("status") != "success" or not isinstance(body.get("data"), list):
            fields["result"] = "error"
            fields["error_type"] = "unexpected_shape"
            return None
        fields["result"] = "ok"
        data = body["data"]
        _forecast_cache[wbgt_no] = data
        return data
