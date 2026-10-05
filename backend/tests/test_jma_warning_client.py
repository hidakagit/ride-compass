"""`infrastructure/jma_warning_client.py`——気象庁の地域マスタ（area.json）と警報・注意報の電文の取得と、応答の形の解き方。

入口は`fetch_area_data`・`fetch_warning_documents`の2つで、気象庁の代役（respx）へ本物の`httpx.AsyncClient`を
向けて呼ぶ。見るのは、返る値（`AreaMaster`・`WarningBulletin`）と、取得に失敗したときのNone、プロセス内
キャッシュで上流を引き直さないこと（電文は府県予報区ごと）。

ここで見ないもの:
- キャッシュの骨格（失敗をキャッシュしない・ログの`fields`）→ `test_simple_api_client.py`
- 地域マスタを辿って警報エリアを解く → `test_jma_area.py`
- 電文から区域の種別を引く・発表中の警報の抽出 → `test_jma_warning_domain.py`
- 地点から警報を返すまでの通し → `test_warning_service.py`
"""

import pytest
import respx

from app.domain.jma_area import AreaEntry, AreaMaster
from app.domain.jma_warning import AreaWarningKind, WarningBulletin
from app.infrastructure import jma_warning_client
from app.infrastructure.jma_warning_client import new_area_data_cache, new_warning_cache
from tests.fake_http import answering, client_for


def _warning_url(office_code: str) -> str:
    return jma_warning_client.JMA_WARNING_URL_TEMPLATE.format(office_code=office_code)


# --- 地域マスタ ---


async def test_area_master_keeps_parent_and_name_of_each_level():
    payload = {
        "centers": {"010300": {"name": "気象庁"}},
        "offices": {"130000": {"name": "東京都"}},
        "class10s": {"130010": {"name": "東京地方", "enName": "Tokyo Region", "parent": "130000"}},
        "class15s": {"130011": {"name": "２３区西部", "parent": "130010"}},
        "class20s": {"1310100": {"name": "千代田区", "kana": "ちよだく", "parent": "130011"}},
    }

    master = await jma_warning_client.fetch_area_data(answering(json=payload), new_area_data_cache())

    assert master == AreaMaster(
        class20s={"1310100": AreaEntry(parent="130011", name="千代田区")},
        class15s={"130011": AreaEntry(parent="130010", name="２３区西部")},
        class10s={"130010": AreaEntry(parent="130000", name="東京地方")},
    )


async def test_area_master_tolerates_missing_or_malformed_sections():
    """無い階層・辞書でない階層は空、辞書でない区域は載せない。親・名前の無い区域はNoneで持つ。"""
    payload = {
        "class20s": {"1310100": {"name": "千代田区"}, "9999999": "壊れた行"},
        "class15s": ["辞書でない"],
    }

    master = await jma_warning_client.fetch_area_data(answering(json=payload), new_area_data_cache())

    assert master == AreaMaster(class20s={"1310100": AreaEntry(parent=None, name="千代田区")}, class15s={}, class10s={})


async def test_area_master_is_fetched_once_while_cached():
    router = respx.Router()
    route = router.get(jma_warning_client.JMA_AREA_JSON_URL).respond(json={"class20s": {}})
    client = client_for(router)

    cache = new_area_data_cache()

    await jma_warning_client.fetch_area_data(client, cache)
    await jma_warning_client.fetch_area_data(client, cache)

    assert route.call_count == 1


@pytest.mark.parametrize(
    "response",
    [
        pytest.param({"status_code": 500}, id="サーバの失敗"),
        pytest.param({"json": ["class20s"]}, id="辞書でない"),
        pytest.param({"text": "<html>"}, id="JSONでない"),
    ],
)
async def test_area_master_failure_is_none(response):
    assert await jma_warning_client.fetch_area_data(answering(**response), new_area_data_cache()) is None


# --- 警報・注意報の電文 ---


async def test_bulletins_are_read_per_document_of_the_office():
    """府県予報区の電文の配列を1件ずつ解く。区域・二次細分区域ごとに種別を持ち、警報の無い地域は
    コードの無い「なし」の1件になる。"""
    router = respx.Router()
    router.get(_warning_url("130000")).respond(
        json=[
            {
                "reportDatetime": "2026-08-29T17:00:00+09:00",
                "warning": {
                    "class20Items": [
                        {"areaCode": "1310100", "kinds": [{"code": "10", "status": "発表", "additions": ["土砂災害"]}]},
                        {"areaCode": "1310200", "kinds": [{"status": "発表警報・注意報はなし"}]},
                    ],
                    "class10Items": [{"areaCode": "130010", "kinds": [{"code": "14", "status": "継続"}]}],
                },
            },
            {"reportDatetime": "2026-08-29T16:00:00+09:00", "warning": {"class10Items": []}},
        ]
    )

    bulletins = await jma_warning_client.fetch_warning_documents(client_for(router), "130000", new_warning_cache())

    assert bulletins == [
        WarningBulletin(
            report_datetime="2026-08-29T17:00:00+09:00",
            class20_kinds={
                "1310100": (AreaWarningKind(code="10", status="発表", additions=("土砂災害",)),),
                "1310200": (AreaWarningKind(code=None, status="発表警報・注意報はなし", additions=()),),
            },
            class10_kinds={"130010": (AreaWarningKind(code="14", status="継続", additions=()),)},
        ),
        WarningBulletin(report_datetime="2026-08-29T16:00:00+09:00", class20_kinds={}, class10_kinds={}),
    ]


async def test_first_item_wins_when_an_area_appears_twice():
    payload = [
        {
            "warning": {
                "class20Items": [
                    {"areaCode": "1310100", "kinds": [{"code": "10", "status": "発表"}]},
                    {"areaCode": "1310100", "kinds": [{"code": "03", "status": "発表"}]},
                ]
            }
        }
    ]

    [bulletin] = await jma_warning_client.fetch_warning_documents(answering(json=payload), "130000", new_warning_cache())

    assert bulletin.class20_kinds == {"1310100": (AreaWarningKind(code="10", status="発表", additions=()),)}


async def test_malformed_parts_of_a_bulletin_are_skipped():
    """辞書でない電文・項目、コードが文字列でない地域は載せない。区域の項目が配列でない・
    `warning`が無い・発表時刻が文字列でない電文は、その部分を空として持つ。"""
    payload = [
        "辞書でない電文",
        {
            "reportDatetime": 20260829,
            "warning": {
                "class20Items": ["辞書でない項目", {"areaCode": 1310100, "kinds": []}, {"kinds": []}],
                "class10Items": {"130010": "配列でない"},
            },
        },
        {"reportDatetime": "2026-08-29T17:00:00+09:00", "warning": "辞書でない"},
    ]

    bulletins = await jma_warning_client.fetch_warning_documents(answering(json=payload), "130000", new_warning_cache())

    assert bulletins == [
        WarningBulletin(report_datetime=None, class20_kinds={}, class10_kinds={}),
        WarningBulletin(report_datetime="2026-08-29T17:00:00+09:00", class20_kinds={}, class10_kinds={}),
    ]


async def test_bulletins_are_cached_per_office():
    router = respx.Router()
    tokyo = router.get(_warning_url("130000")).respond(json=[])
    osaka = router.get(_warning_url("270000")).respond(json=[])
    client = client_for(router)

    cache = new_warning_cache()

    await jma_warning_client.fetch_warning_documents(client, "130000", cache)
    await jma_warning_client.fetch_warning_documents(client, "130000", cache)
    await jma_warning_client.fetch_warning_documents(client, "270000", cache)

    assert (tokyo.call_count, osaka.call_count) == (1, 1)


@pytest.mark.parametrize(
    "response",
    [
        pytest.param({"status_code": 404}, id="無い府県予報区"),
        pytest.param({"json": {"warning": {}}}, id="配列でない"),
        pytest.param({"text": "["}, id="JSONでない"),
    ],
)
async def test_bulletin_failure_is_none(response):
    assert await jma_warning_client.fetch_warning_documents(answering(**response), "130000", new_warning_cache()) is None
