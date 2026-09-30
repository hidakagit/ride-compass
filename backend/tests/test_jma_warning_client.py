"""`infrastructure/jma_warning_client.py`——JMA警報電文・地域マスタ(area.json)を引き、形を解く。

入力は気象庁の応答の形（2026-09-27に取得した東京の電文・地域マスタの形）で与える。

ここで見ないもの:
- キャッシュ参照・形の検査・例外をNoneへ倒す骨格 → `test_simple_api_client.py`
- 地域マスタの階層を辿る処理 → `test_jma_area.py`
- 種別から発表中の警報を取り出す処理 → `test_jma_warning_domain.py`
"""

import pytest
import respx
from cachetools import TTLCache

from app.domain.jma_area import AreaEntry, AreaMaster
from app.domain.jma_warning import AreaWarningKind
from app.infrastructure import jma_warning_client
from app.domain.jma_warning import WarningBulletin
from tests.fake_http import answering, client_for

#: 地域マスタの千代田区から府県予報区までの行（実際の応答の形のまま。`children`等は使わない）。
AREA_JSON = {
    "centers": {"010300": {"name": "関東甲信地方", "children": ["130000"]}},
    "offices": {"130000": {"name": "東京都", "parent": "010300", "children": ["130010"]}},
    "class10s": {"130010": {"name": "東京地方", "enName": "Tokyo Region", "parent": "130000", "children": ["130011"]}},
    "class15s": {"130011": {"name": "２３区西部", "parent": "130010", "children": ["1310100"]}},
    "class20s": {"1310100": {"name": "千代田区", "enName": "Chiyoda City", "kana": "ちよだく", "parent": "130011"}},
}

#: 警報の電文1件（r8）。区域の項目と二次細分区域の項目を持つ。
BULLETIN = {
    "publishingOffice": "気象庁",
    "reportDatetime": "2026-09-27T05:00:00+09:00",
    "infoType": "発表",
    "headlineText": "",
    "warning": {
        "class10Items": [{"areaCode": "130010", "kinds": [{"code": "03", "status": "解除"}]}],
        "class20Items": [
            {"areaCode": "1310100", "kinds": [{"code": "14", "status": "発表", "additions": ["竜巻"]}]},
            {"areaCode": "1310200", "kinds": [{"status": "発表警報・注意報はなし"}]},
        ],
    },
}


@pytest.fixture(autouse=True)
def _clear_module_caches():
    """プロセス内TTLCacheはテスト間で持ち越される。モジュールが持つキャッシュを
    名前で並べずに走査して空にする（キャッシュが増えても取りこぼさない）。"""
    for value in vars(jma_warning_client).values():
        if isinstance(value, TTLCache):
            value.clear()


# ---- 地域マスタ ----


async def test_area_master_keeps_the_parent_and_name_of_each_tier():
    master = await jma_warning_client.fetch_area_data(answering(json=AREA_JSON))

    assert master == AreaMaster(
        class20s={"1310100": AreaEntry(parent="130011", name="千代田区")},
        class15s={"130011": AreaEntry(parent="130010", name="２３区西部")},
        class10s={"130010": AreaEntry(parent="130000", name="東京地方")},
    )


async def test_an_area_master_missing_whole_tiers_reads_them_as_empty():
    master = await jma_warning_client.fetch_area_data(answering(json={"class20s": AREA_JSON["class20s"]}))

    assert master.class15s == {} and master.class10s == {}


async def test_an_area_without_a_parent_or_a_name_keeps_them_absent():
    master = await jma_warning_client.fetch_area_data(answering(json={"class20s": {"1310100": {}}}))

    assert master.class20s == {"1310100": AreaEntry(parent=None, name=None)}


async def test_area_data_is_cached_across_calls():
    upstream = respx.Router()
    upstream.route().respond(json=AREA_JSON)
    client = client_for(upstream)

    first = await jma_warning_client.fetch_area_data(client)
    assert await jma_warning_client.fetch_area_data(client) == first
    assert upstream.calls.call_count == 1


async def test_area_data_http_error_returns_none():
    assert await jma_warning_client.fetch_area_data(answering(500)) is None


async def test_an_area_master_that_is_not_an_object_returns_none():
    assert await jma_warning_client.fetch_area_data(answering(json=[])) is None


# ---- 警報の電文 ----


async def test_a_bulletin_is_read_into_the_kinds_of_each_area():
    (bulletin,) = await jma_warning_client.fetch_warning_documents(answering(json=[BULLETIN]), "130000")

    assert bulletin == WarningBulletin(
        report_datetime="2026-09-27T05:00:00+09:00",
        class20_kinds={
            "1310100": (AreaWarningKind(code="14", status="発表", additions=("竜巻",)),),
            "1310200": (AreaWarningKind(code=None, status="発表警報・注意報はなし", additions=()),),
        },
        class10_kinds={"130010": (AreaWarningKind(code="03", status="解除", additions=()),)},
    )


async def test_a_bulletin_without_items_for_a_tier_has_no_area_of_that_tier():
    """高潮等の電文は区域の項目自体を持たないことがある。呼び出し元はそれを見て二次細分区域で探す。"""
    document = {**BULLETIN, "warning": {"class10Items": BULLETIN["warning"]["class10Items"]}}

    (bulletin,) = await jma_warning_client.fetch_warning_documents(answering(json=[document]), "130000")

    assert bulletin.class20_kinds == {}
    assert set(bulletin.class10_kinds) == {"130010"}


async def test_the_first_item_of_an_area_wins():
    items = [
        {"areaCode": "1310100", "kinds": [{"status": "発表警報・注意報はなし"}]},
        {"areaCode": "1310100", "kinds": [{"code": "14", "status": "発表"}]},
    ]
    document = {**BULLETIN, "warning": {"class20Items": items}}

    (bulletin,) = await jma_warning_client.fetch_warning_documents(answering(json=[document]), "130000")

    assert bulletin.class20_kinds["1310100"] == (AreaWarningKind(code=None, status="発表警報・注意報はなし", additions=()),)


@pytest.mark.parametrize("report_datetime", [None, 20260927])
async def test_a_report_time_that_is_not_text_is_absent(report_datetime):
    document = {**BULLETIN, "reportDatetime": report_datetime}

    (bulletin,) = await jma_warning_client.fetch_warning_documents(answering(json=[document]), "130000")

    assert bulletin.report_datetime is None


async def test_documents_that_are_not_objects_and_bulletins_without_a_warning_carry_no_areas():
    documents = ["broken", {"reportDatetime": "2026-09-27T05:00:00+09:00"}]

    bulletins = await jma_warning_client.fetch_warning_documents(answering(json=documents), "130000")

    assert bulletins == [
        WarningBulletin(report_datetime="2026-09-27T05:00:00+09:00", class20_kinds={}, class10_kinds={})
    ]


async def test_warning_documents_requests_the_office_code_url():
    upstream = respx.Router()
    upstream.route().respond(json=[BULLETIN])

    await jma_warning_client.fetch_warning_documents(client_for(upstream), "130000")

    assert upstream.calls.last.request.url.path.endswith("/130000.json")


async def test_warning_documents_reject_non_list_payload():
    """1地点でも複数電文の配列で返る。単独の電文（dict）は読めないためNoneへ倒す。"""
    assert await jma_warning_client.fetch_warning_documents(answering(json=BULLETIN), "130000") is None


async def test_warning_documents_are_cached_per_office_code():
    upstream = respx.Router()
    upstream.route().respond(json=[])
    client = client_for(upstream)

    await jma_warning_client.fetch_warning_documents(client, "130000")
    await jma_warning_client.fetch_warning_documents(client, "130000")
    assert upstream.calls.call_count == 1

    await jma_warning_client.fetch_warning_documents(client, "140000")
    assert upstream.calls.call_count == 2
