"""JMA警報・注意報API、地域マスタ(area.json)のクライアント。

どちらも更新頻度が低い（area.jsonは行政区画変更でしか変わらず、
警報自体も分単位では動かない）ため、429前提の再試行は設けない。取得失敗はNoneを返し、呼び出し元
（warning_service.py）が「警報なし」として扱う（安全側ではない既知のトレードオフを
WBGTと共有する）。応答の形はここで解き、呼び出し元へは`AreaMaster`・`WarningBulletin`で渡す。
"""

from dataclasses import dataclass

import httpx
from cachetools import TTLCache

from app.domain.jma_area import AreaEntry, AreaMaster
from app.domain.jma_warning import AreaWarningKind
from app.infrastructure.simple_api_client import UnexpectedShapeError, cached_fetch

JMA_AREA_JSON_URL = "https://www.jma.go.jp/bosai/common/const/area.json"
JMA_WARNING_URL_TEMPLATE = "https://www.jma.go.jp/bosai/warning/data/r8/{office_code}.json"

# area.jsonは行政区画変更でしか変わらない静的に近いデータのため長いTTL。
_AREA_DATA_CACHE_TTL_SECONDS = 24 * 60 * 60

# 警報は数分〜数十分単位で更新されうるため、area.jsonより短いTTL。
_WARNING_CACHE_TTL_SECONDS = 10 * 60

REQUEST_TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)

# maxsizeは実運用で想定されるキー数（府県予報区約50）に十分な余裕を持たせた上限
# （LRU的なサイズ超過退避が実質発生しない値。TTL切れによる鮮度管理が主）。
_area_data_cache: TTLCache = TTLCache(maxsize=1, ttl=_AREA_DATA_CACHE_TTL_SECONDS)
_warning_cache: TTLCache = TTLCache(maxsize=256, ttl=_WARNING_CACHE_TTL_SECONDS)
_AREA_DATA_CACHE_KEY = "area"


@dataclass(frozen=True)
class WarningBulletin:
    """警報・注意報の電文1件。地域のコード→その地域の種別。電文が地域の項目を持たない
    （例: 高潮の電文は対象外の地域の区域を載せないことがある）なら、その地域のキーが無い。"""

    report_datetime: str | None
    class20_kinds: dict[str, tuple[AreaWarningKind, ...]]
    class10_kinds: dict[str, tuple[AreaWarningKind, ...]]


def _parse_area_entries(section: object) -> dict[str, AreaEntry]:
    if not isinstance(section, dict):
        return {}
    return {
        code: AreaEntry(parent=entry.get("parent"), name=entry.get("name"))
        for code, entry in section.items()
        if isinstance(entry, dict)
    }


def _parse_area_master(payload: dict) -> AreaMaster:
    return AreaMaster(
        class20s=_parse_area_entries(payload.get("class20s")),
        class15s=_parse_area_entries(payload.get("class15s")),
        class10s=_parse_area_entries(payload.get("class10s")),
    )


def _parse_area_items(items: object) -> dict[str, tuple[AreaWarningKind, ...]]:
    """地域ごとの種別。同じ地域のコードが2度現れたら最初の項目を使う。"""
    if not isinstance(items, list):
        return {}
    kinds_by_area: dict[str, tuple[AreaWarningKind, ...]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        area_code = item.get("areaCode")
        if not isinstance(area_code, str) or area_code in kinds_by_area:
            continue
        kinds_by_area[area_code] = tuple(
            # 警報が何も無い地域の種別は`{"status": "発表警報・注意報はなし"}`でコードを持たない。
            AreaWarningKind(code=kind.get("code"), status=kind.get("status"), additions=tuple(kind.get("additions", ())))
            for kind in item.get("kinds", ())
        )
    return kinds_by_area


def _parse_bulletin(document: dict) -> WarningBulletin:
    warning = document.get("warning")
    if not isinstance(warning, dict):
        warning = {}
    report_datetime = document.get("reportDatetime")
    return WarningBulletin(
        report_datetime=report_datetime if isinstance(report_datetime, str) else None,
        class20_kinds=_parse_area_items(warning.get("class20Items")),
        class10_kinds=_parse_area_items(warning.get("class10Items")),
    )


async def fetch_area_data(client: httpx.AsyncClient) -> AreaMaster | None:
    """気象庁の地域マスタ(area.json)を取得する。行政区画変更以外では変化しないため
    プロセス内で長時間キャッシュする。"""

    async def fetch() -> AreaMaster:
        response = await client.get(JMA_AREA_JSON_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise UnexpectedShapeError(f"area master is {type(payload).__name__}")
        return _parse_area_master(payload)

    return await cached_fetch(
        "weather:jma-area", fetch, cache=_area_data_cache, key=_AREA_DATA_CACHE_KEY
    )


async def fetch_warning_documents(client: httpx.AsyncClient, office_code: str) -> list[WarningBulletin] | None:
    """指定した府県予報区コードの警報・注意報電文一覧（r8スキーマ、令和8年5月29日の
    運用切替以降の現行API）を取得する。

    JMAは大雨・土砂災害・高潮・暴風/暴風雪・波浪・大雪・その他の注意報を別々の電文
    （VPWW55〜61）として発表するため、レスポンスは1地点でも複数電文の配列になる
    （domain/jma_warning.py参照）。"""

    async def fetch() -> list[WarningBulletin]:
        response = await client.get(JMA_WARNING_URL_TEMPLATE.format(office_code=office_code), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise UnexpectedShapeError(f"warning bulletins are {type(payload).__name__}")
        return [_parse_bulletin(document) for document in payload if isinstance(document, dict)]

    return await cached_fetch(
        "weather:jma-warning",
        fetch,
        cache=_warning_cache,
        key=office_code,
        office_code=office_code,
    )
