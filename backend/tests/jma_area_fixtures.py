"""区域コード階層を引くサービスのテストが共有するデータと上流の代役。

`flood_service`・`warning_service`はどちらも「緯度経度→区域の境界→area.jsonの
階層→発表文書」という同じ順で引くため、上流の代役の張り方も同じになる。差し替えるのは
プロセス境界（区域の境界の置き場・気象庁への取得）だけで、応答の形を解くクライアントは本物を通す。

既定は**区域が解決できる世界**で、テストが見る区域コード・地方名はここの名前で参照する
（値を書き写すと、ここを変えたときに関係ないテストが落ちる）。
"""

from cachetools import TTLCache
from shapely.geometry import box

from app.domain.route import Coordinates
from app.infrastructure import flood_client, jma_area_boundaries, jma_warning_client
from tests.fake_api_http import FakeResponse, RoutingHttpClient

CLASS20_CODE = "1310100"
CLASS10_CODE = "130010"
CLASS10_NAME = "東京地方"
OFFICE_CODE = "130000"

#: 地域マスタ（area.json）の千代田区から府県予報区までの行。項目は実際の応答の形のまま。
AREA_DATA = {
    "class20s": {CLASS20_CODE: {"name": "千代田区", "enName": "Chiyoda City", "kana": "ちよだく", "parent": "130011"}},
    "class15s": {"130011": {"name": "２３区西部", "enName": "Western Region of 23 wards", "parent": CLASS10_CODE}},
    "class10s": {CLASS10_CODE: {"name": CLASS10_NAME, "enName": "Tokyo Region", "parent": OFFICE_CODE}},
}

CHIYODA_POINT = Coordinates(latitude=35.6812, longitude=139.7671)
#: どの区域の境界からも最寄りの区域へ寄せる距離より遠い地点（海上）。
OFFSHORE_POINT = Coordinates(latitude=34.0, longitude=141.0)


def area_lookup_upstream(
    monkeypatch,
    tmp_path,
    *,
    class20_code=CLASS20_CODE,
    area_data=AREA_DATA,
    warning_documents=None,
    flood_documents=None,
) -> RoutingHttpClient:
    """区域の境界を`CHIYODA_POINT`を囲む1区域だけにし、気象庁の代役を返す。

    境界はディスクから読む本物を通す（置き場だけを`tmp_path`へ移す）。代役は地域マスタ・
    `OFFICE_CODE`の警報・洪水予報をURLで返し（Noneなら接続の失敗）、それ以外のURL（別の府県予報区の
    警報等）を引かれたら落ちる。クライアントのプロセス内キャッシュは空にする。
    """
    boundary_path = tmp_path / "boundaries.json"
    jma_area_boundaries.write_boundaries(
        boundary_path,
        {class20_code: box(CHIYODA_POINT.longitude - 0.01, CHIYODA_POINT.latitude - 0.01,
                           CHIYODA_POINT.longitude + 0.01, CHIYODA_POINT.latitude + 0.01)},
    )
    monkeypatch.setattr(jma_area_boundaries, "BOUNDARY_PATH", boundary_path)
    monkeypatch.setattr(jma_warning_client, "_area_data_cache", TTLCache(maxsize=1, ttl=60))
    monkeypatch.setattr(jma_warning_client, "_warning_cache", TTLCache(maxsize=8, ttl=60))
    monkeypatch.setattr(flood_client, "_flood_cache", TTLCache(maxsize=1, ttl=60))

    payloads = {
        jma_warning_client.JMA_AREA_JSON_URL: area_data,
        jma_warning_client.JMA_WARNING_URL_TEMPLATE.format(office_code=OFFICE_CODE): warning_documents,
        flood_client.FLOOD_API_URL: flood_documents,
    }

    def route(url):
        payload = payloads[url]
        return None if payload is None else FakeResponse(payload)

    return RoutingHttpClient(route)
