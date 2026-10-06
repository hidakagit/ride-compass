"""JMA警報・注意報API、地域マスタ(area.json)のクライアント。

どちらも更新頻度が低い（area.jsonは行政区画変更でしか変わらず、
警報自体も分単位では動かない）ため、429前提の再試行は設けない。取得失敗はNoneを返し、呼び出し元
（warning_service.py）が「警報なし」と分けて返す。応答の形はここで解き、呼び出し元へは
`AreaMaster`・`WarningBulletin`で渡す。
"""

import logging

import httpx
from cachetools import TTLCache

from app.domain.jma_area import AreaEntry, AreaMaster
from app.domain.jma_warning import AreaWarningKind, WarningBulletin
from app.infrastructure.simple_api_client import UnexpectedShapeError, cached_fetch

JMA_AREA_JSON_URL = "https://www.jma.go.jp/bosai/common/const/area.json"
JMA_WARNING_URL_TEMPLATE = "https://www.jma.go.jp/bosai/warning/data/r8/{office_code}.json"

# area.jsonは行政区画変更でしか変わらない静的に近いデータのため長いTTL。
_AREA_DATA_CACHE_TTL_SECONDS = 24 * 60 * 60

# 警報は数分〜数十分単位で更新されうるため、area.jsonより短いTTL。
_WARNING_CACHE_TTL_SECONDS = 10 * 60

logger = logging.getLogger("ridecompass.jma_warning_client")

REQUEST_TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)

_AREA_DATA_CACHE_KEY = "area"


def new_area_data_cache() -> TTLCache:
    """`fetch_area_data`へ渡すキャッシュ。リクエストをまたいで持つのは組み立てる側（`api/dependencies.py`）。"""
    return TTLCache(maxsize=1, ttl=_AREA_DATA_CACHE_TTL_SECONDS)


def new_warning_cache() -> TTLCache:
    """`fetch_warning_documents`へ渡すキャッシュ。リクエストをまたいで持つのは組み立てる側（`api/dependencies.py`）。"""
    # maxsizeは実運用で想定されるキー数（府県予報区約50）に十分な余裕を持たせた上限
    # （LRU的なサイズ超過退避が実質発生しない値。TTL切れによる鮮度管理が主）。
    return TTLCache(maxsize=256, ttl=_WARNING_CACHE_TTL_SECONDS)


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _parse_area_entries(section: object) -> dict[str, AreaEntry]:
    if not isinstance(section, dict):
        return {}
    return {
        code: AreaEntry(parent=_str_or_none(entry.get("parent")))
        for code, entry in section.items()
        if isinstance(entry, dict)
    }


def _parse_area_master(payload: dict) -> AreaMaster:
    sections = {key: payload.get(key) for key in ("class20s", "class15s", "class10s")}
    parsed = {key: _parse_area_entries(section) for key, section in sections.items()}
    total = sum(len(section) for section in sections.values() if isinstance(section, dict))
    unreadable = total - sum(len(entries) for entries in parsed.values())
    # 読めない区域は他の区域を解くために飛ばすが、飛ばしたことは取得1回につき1行で出す（logging.md「外部データの読み飛ばし」）。
    if unreadable:
        logger.warning(
            "気象庁の地域マスタに読めない区域があり読み飛ばしました unreadable=%d entries=%d", unreadable, total
        )
    return AreaMaster(**parsed)


def _parse_kind(kind: object) -> AreaWarningKind | None:
    """電文の1種別。辞書でない・コードか状態が文字列でないなら読めない（None）。警報が何も無い地域の種別は
    `{"status": "発表警報・注意報はなし"}`でコードを持たない。付加事項は補足なので、
    配列でなければ無いとし、文字列でない要素は落とす——付加事項が壊れても警報そのものは出す。"""
    if not isinstance(kind, dict):
        return None
    code = kind.get("code")
    status = kind.get("status")
    if not (code is None or isinstance(code, str)) or not (status is None or isinstance(status, str)):
        return None
    additions = kind.get("additions")
    return AreaWarningKind(
        code=code,
        status=status,
        additions=tuple(a for a in additions if isinstance(a, str)) if isinstance(additions, list) else (),
    )


def _parse_area_items(items: object) -> tuple[dict[str, tuple[AreaWarningKind, ...]], int]:
    """地域ごとの種別と、読めずに飛ばした項目・種別の数。同じ地域のコードが2度現れたら最初の項目を使う。"""
    if not isinstance(items, list):
        return {}, 0
    kinds_by_area: dict[str, tuple[AreaWarningKind, ...]] = {}
    unreadable = 0
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("areaCode"), str):
            unreadable += 1
            continue
        area_code = item["areaCode"]
        if area_code in kinds_by_area:
            continue
        raw_kinds = item.get("kinds")
        parsed = [_parse_kind(kind) for kind in raw_kinds] if isinstance(raw_kinds, list) else []
        kinds_by_area[area_code] = tuple(kind for kind in parsed if kind is not None)
        unreadable += len(parsed) - len(kinds_by_area[area_code])
    return kinds_by_area, unreadable


def _parse_bulletin(document: dict) -> tuple[WarningBulletin, int]:
    """電文1件と、その中で読めずに飛ばした項目・種別の数。"""
    warning = document.get("warning")
    if not isinstance(warning, dict):
        warning = {}
    class20_kinds, skipped20 = _parse_area_items(warning.get("class20Items"))
    class10_kinds, skipped10 = _parse_area_items(warning.get("class10Items"))
    bulletin = WarningBulletin(
        class20_kinds=class20_kinds,
        class10_kinds=class10_kinds,
    )
    return bulletin, skipped20 + skipped10


def _parse_bulletins(payload: list, office_code: str) -> list[WarningBulletin]:
    parsed = [_parse_bulletin(document) for document in payload if isinstance(document, dict)]
    unreadable = len(payload) - len(parsed) + sum(skipped for _, skipped in parsed)
    # 読めない部分は他の警報を出すために飛ばすが、飛ばしたことは取得1回につき1行で出す（logging.md「外部データの読み飛ばし」）。
    # 一部の警報だけが落ちる形は、画面も/api/debug/statsも正常に見える。
    if unreadable:
        logger.warning(
            "気象庁の警報の電文に読めない部分があり読み飛ばしました unreadable=%d bulletins=%d office=%s",
            unreadable, len(payload), office_code,
        )
    return [bulletin for bulletin, _ in parsed]


async def fetch_area_data(client: httpx.AsyncClient, cache: TTLCache) -> AreaMaster | None:
    """気象庁の地域マスタ(area.json)を取得する。行政区画変更以外では変化しないため
    プロセス内で長時間キャッシュする。"""

    async def fetch() -> AreaMaster:
        response = await client.get(JMA_AREA_JSON_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise UnexpectedShapeError(f"area master is {type(payload).__name__}")
        return _parse_area_master(payload)

    return await cached_fetch("weather:jma-area", fetch, cache=cache, key=_AREA_DATA_CACHE_KEY)


async def fetch_warning_documents(
    client: httpx.AsyncClient, office_code: str, cache: TTLCache
) -> list[WarningBulletin] | None:
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
        return _parse_bulletins(payload, office_code)

    return await cached_fetch(
        "weather:jma-warning",
        fetch,
        cache=cache,
        key=office_code,
        office_code=office_code,
    )
