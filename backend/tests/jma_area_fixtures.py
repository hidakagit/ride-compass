"""区域コード階層を引くサービスのテストが共有するデータとパッチヘルパ。

`flood_service`・`warning_service`はどちらも「緯度経度→市区町村コード→area.jsonの
階層→発表文書」という同じ順で上流を引くため、フェイクの張り方も同じになる。

既定は**区域が解決できる世界**で、テストが見る区域コード・地方名はここの名前で参照する
（値を書き写すと、ここを変えたときに関係ないテストが落ちる）。
"""

from app.domain.jma_area import municipality_code_to_class20_code
from app.domain.route import Coordinates

MUNICIPALITY_CODE = "13101"
CLASS20_CODE = municipality_code_to_class20_code(MUNICIPALITY_CODE)
CLASS10_CODE = "130010"
CLASS10_NAME = "東京地方"

AREA_DATA = {
    "class20s": {CLASS20_CODE: {"name": "千代田区", "parent": "130011"}},
    "class15s": {"130011": {"name": "２３区西部", "parent": CLASS10_CODE}},
    "class10s": {CLASS10_CODE: {"name": CLASS10_NAME, "parent": "130000"}},
}

CHIYODA_POINT = Coordinates(latitude=35.6812, longitude=139.7671)


def patch_area_lookup(
    monkeypatch,
    service_module,
    documents_attr,
    *,
    muni_cd=MUNICIPALITY_CODE,
    area_data=AREA_DATA,
    documents=None,
):
    """サービスが呼ぶ3つの取得関数をフェイクへ差し替える。

    文書の取得関数はサービスごとに名前も引数の数も違うため、名前は`documents_attr`で
    受け取り、フェイク側は位置引数を受け流す。
    """

    async def fake_muni_cd(client, lat, lon):
        return muni_cd

    async def fake_area_data(client):
        return area_data

    async def fake_documents(*args):
        return documents

    monkeypatch.setattr(service_module, "fetch_municipality_code", fake_muni_cd)
    monkeypatch.setattr(service_module, "fetch_area_data", fake_area_data)
    monkeypatch.setattr(service_module, documents_attr, fake_documents)
