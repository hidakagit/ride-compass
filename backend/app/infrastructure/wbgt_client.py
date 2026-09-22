"""環境省 熱中症予防情報サイトのクライアント。

情報提供地点マスタ（CSV）と暑さ指数（WBGT）予測値取得WebAPI（JSON、典拠は
`man15NH/wbgt_data_api_service_manual.pdf`）を叩く。サイト側の利用上の注意
（wbgt_data_download.php）に「自動化ツールからの高頻度アクセスは控えて」と明記されて
いるため、再試行は設けずTTLキャッシュで呼び出し頻度自体を抑える。取得失敗はNoneを返し、
呼び出し元（wbgt_service.py）が「警告なし」として扱う。
"""

import csv
import io

import httpx
from cachetools import TTLCache

from app.domain.wbgt_points import WbgtPoint
from app.infrastructure.simple_api_client import UnexpectedShapeError, cached_fetch

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

    async def fetch() -> list[WbgtPoint]:
        response = await client.get(WBGT_POINT_MASTER_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return _parse_point_master(response.text)

    return await cached_fetch(
        "weather:wbgt-point-master", fetch, cache=_point_master_cache, key=_POINT_MASTER_CACHE_KEY
    )


def _parse_point_master(csv_text: str) -> list[WbgtPoint]:
    """地点マスタCSVから、運用中の地点の番号・名称・緯度経度を取り出す。

    **列の典拠はCSVの先頭行（ヘッダー）そのもの**で、別の仕様書は無い。18列あり、
    使うのは`地点番号`(2)・`観測所名`(3)・`Latitude`(7)/`Latitude_3`(8)・
    `Longitude`(9)/`Longitude_4`(10)・`End Year-End Month-End Day`(12)。

    ヘッダーを読んでも分からないことが2つある。**緯度経度は度と分に分かれている**
    （`45`と`31.2`で45度31.2分）ので、度へ直すには分を60で割って足す。終了日の
    `9999-99-99`は**運用中**を表す番兵で、それ以外の日付が入っている地点は終了済み。
    """
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
        except ValueError:
            continue  # 欠損行はスキップ（他地点で近傍検索を続行できる）
        points.append(WbgtPoint(no=no, name=name, latitude=latitude, longitude=longitude))
    return points


async def fetch_forecast(client: httpx.AsyncClient, wbgt_no: str, range_from: str, range_to: str) -> list[dict] | None:
    """指定地点の暑さ指数予測値列（3時間刻み、翌々日まで）を取得する。

    `range_from`/`range_to`はYYYYMMDDHHMMSS形式（発表時刻=reference_timeの検索範囲。
    呼び出し元が「現在時刻を含む直近N時間」を渡す想定）。date_search_type=3
    （特定時刻）は指定時刻ちょうどに発表（reference_time）が存在しないと空を返す
    厳格な一致検索（20:00:00ちょうどを指定すると20時発表がまだ無く空、19:00:00なら
    19時発表がヒットする、等）。発表は概ね毎時行われるが遅延もありうるため、
    date_search_type=1（連続期間指定）で直近の発表を幅広く取得し、複数の発表回
    （reference_time）が返ってきた場合は呼び出し元（wbgt_service.py）が最新の発表回
    だけを使う。レスポンスの`forecast_val`は暑さ指数を10倍した整数文字列（例:
    東京地点でforecast_val="280"→暑さ指数28.0）のため、呼び出し元で10で割ること。
    """
    params = {
        "location_type": 1,
        "date_search_type": 1,
        "wbgt_nos": wbgt_no,
        "range_date_from": range_from,
        "range_date_to": range_to,
    }

    async def fetch() -> list[dict]:
        response = await client.get(WBGT_FORECAST_API_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        body = response.json()
        if body.get("status") != "success":
            raise UnexpectedShapeError("wbgt forecast response is not successful")
        return body.get("data")

    return await cached_fetch(
        "weather:wbgt-forecast",
        fetch,
        cache=_forecast_cache,
        key=wbgt_no,
        expect=list,
        wbgt_no=wbgt_no,
    )
