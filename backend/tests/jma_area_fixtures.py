"""区域コード階層を引くサービスのテストが共有するデータとパッチヘルパ。

`flood_service`・`warning_service`はどちらも「緯度経度→区域の境界→area.jsonの
階層→発表文書」という同じ順で引くため、フェイクの張り方も同じになる。

既定は**区域が解決できる世界**で、テストが見る区域コード・地方名はここの名前で参照する
（値を書き写すと、ここを変えたときに関係ないテストが落ちる）。
"""

from shapely.geometry import box

from app.domain.route import Coordinates
from app.infrastructure import jma_area_boundaries
from tests.bound_fake import bound

CLASS20_CODE = "1310100"
CLASS10_CODE = "130010"
CLASS10_NAME = "東京地方"

AREA_DATA = {
    "class20s": {CLASS20_CODE: {"name": "千代田区", "parent": "130011"}},
    "class15s": {"130011": {"name": "２３区西部", "parent": CLASS10_CODE}},
    "class10s": {CLASS10_CODE: {"name": CLASS10_NAME, "parent": "130000"}},
}

CHIYODA_POINT = Coordinates(latitude=35.6812, longitude=139.7671)
#: どの区域の境界からも最寄りの区域へ寄せる距離より遠い地点（海上）。
OFFSHORE_POINT = Coordinates(latitude=34.0, longitude=141.0)


def patch_area_lookup(
    monkeypatch,
    tmp_path,
    service_module,
    documents_attr,
    *,
    class20_code=CLASS20_CODE,
    area_data=AREA_DATA,
    documents=None,
):
    """区域の境界を`CHIYODA_POINT`を囲む1区域だけにし、サービスが呼ぶ取得関数をフェイクへ差し替える。

    境界はディスクから読む本物を通す（置き場だけを`tmp_path`へ移す）。文書の取得関数は
    サービスごとに名前も引数の数も違うため、名前は`documents_attr`で受け取り、フェイク側は
    位置引数を受け流す（数と並びは本物の署名で確かめる）。
    """
    boundary_path = tmp_path / "boundaries.json"
    jma_area_boundaries.write_boundaries(
        boundary_path,
        {class20_code: box(CHIYODA_POINT.longitude - 0.01, CHIYODA_POINT.latitude - 0.01,
                           CHIYODA_POINT.longitude + 0.01, CHIYODA_POINT.latitude + 0.01)},
    )
    monkeypatch.setattr(jma_area_boundaries, "BOUNDARY_PATH", boundary_path)

    async def fake_area_data(client):
        return area_data

    async def fake_documents(*args):
        return documents

    monkeypatch.setattr(service_module, "fetch_area_data", fake_area_data)
    monkeypatch.setattr(service_module, documents_attr, bound(getattr(service_module, documents_attr), fake_documents))
