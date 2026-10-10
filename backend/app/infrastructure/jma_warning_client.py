"""JMA警報・注意報API、地域マスタ(area.json)のクライアント。

どちらも更新頻度が低い（area.jsonは行政区画変更でしか変わらず、
警報自体も分単位では動かない）ため、429前提の再試行は設けない。取得失敗はNoneを返し、
「警報なし」とは分ける。応答の形はここで解き、呼び出し元へは
`AreaMaster`・`WarningBulletin`で渡す。

警報のコード→種別の名称の表は、気象庁「気象警報・注意報（Ｒ０６）」電文フォーマット解説資料の別表3
（警戒レベル等対応コード表、令和8年5月29日の運用切替以降の現行r8スキーマ）を典拠とする。表は決まった所から
機械で読める形では配られないため、ここへ写して持つ（警報のページは圧縮したスクリプトの中へ埋め込み、
防災情報XMLの技術資料 https://xml.kishou.go.jp/tec_material.html はコード表を版の日付入りのファイル名で置く）。
"""

import logging
from dataclasses import dataclass

import httpx
from cachetools import TTLCache

from app.domain.jma_area import AreaEntry, AreaMaster
from app.domain.jma_warning import NOT_RELEVANT_TO_CYCLING, AreaWarningKind, WarningBulletin
from app.infrastructure.simple_api_client import cached_fetch, get_json

JMA_AREA_JSON_URL = "https://www.jma.go.jp/bosai/common/const/area.json"
JMA_WARNING_URL_TEMPLATE = "https://www.jma.go.jp/bosai/warning/data/r8/{office_code}.json"

# area.jsonは行政区画変更でしか変わらない静的に近いデータのため長いTTL。
_AREA_DATA_CACHE_TTL_SECONDS = 24 * 60 * 60

# 警報は数分〜数十分単位で更新されうるため、area.jsonより短いTTL。
_WARNING_CACHE_TTL_SECONDS = 10 * 60

logger = logging.getLogger("ridecompass.jma_warning_client")

REQUEST_TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)

_AREA_DATA_CACHE_KEY = "area"

# 別表3の全コード→種別の名称。「レベルN」の接頭辞は段（`domain/jma_warning.py: warning_level`）が名称から
# 導くため省く。対応表で※1（予約領域）とされ割り当ての無いコードは含めない。
WARNING_KINDS: dict[str, str] = {
    "00": "解除",
    "02": "暴風雪警報",
    "03": "大雨警報",
    "04": "洪水警報",
    "05": "暴風警報",
    "06": "大雪警報",
    "07": "波浪警報",
    "08": "高潮警報",
    "09": "土砂災害警報",
    "10": "大雨注意報",
    "12": "大雪注意報",
    "13": "風雪注意報",
    "14": "雷注意報",
    "15": "強風注意報",
    "16": "波浪注意報",
    "17": "融雪注意報",
    "18": "洪水注意報",
    "19": "高潮注意報",
    "20": "濃霧注意報",
    "21": "乾燥注意報",
    "22": "なだれ注意報",
    "23": "低温注意報",
    "24": "霜注意報",
    "25": "着氷注意報",
    "26": "着雪注意報",
    "27": "その他の注意報",
    "29": "土砂災害注意報",
    "32": "暴風雪特別警報",
    "33": "大雨特別警報",
    "35": "暴風特別警報",
    "36": "大雪特別警報",
    "37": "波浪特別警報",
    "38": "高潮特別警報",
    "39": "土砂災害特別警報",
    "43": "大雨危険警報",
    "48": "高潮危険警報",
    "49": "土砂災害危険警報",
}

_UNNAMED_IRRELEVANT = sorted(NOT_RELEVANT_TO_CYCLING - set(WARNING_KINDS.values()))
if _UNNAMED_IRRELEVANT:
    # 出さない側に書いた名称が表に無ければ、その指定は何も起きないまま残る。
    raise RuntimeError(f"出さない種別の名称が警報のコード表に無い: {_UNNAMED_IRRELEVANT}")

# 種別が「現在発表中」であることを示す状態。「解除」（直前まで出ていたが取り下げられた）と
# 「発表警報・注意報はなし」（元々何も出ていない、コード自体を持たない）はどちらも発表中ではない。
_ACTIVE_STATUSES = frozenset({"発表", "継続"})


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


@dataclass(frozen=True)
class _RawKind:
    """電文の1種別の、読み替える前の字句。"""

    code: str | None
    status: str | None
    additions: tuple[str, ...]


def _parse_kind(kind: object) -> _RawKind | None:
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
    return _RawKind(
        code=code,
        status=status,
        additions=tuple(a for a in additions if isinstance(a, str)) if isinstance(additions, list) else (),
    )


_RawArea = dict[str, tuple[_RawKind, ...]]


def _parse_area_items(items: object) -> tuple[_RawArea, int]:
    """地域ごとの種別と、読めずに飛ばした項目・種別の数。同じ地域のコードが2度現れたら最初の項目を使う。"""
    if not isinstance(items, list):
        return {}, 0
    kinds_by_area: _RawArea = {}
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


def _parse_bulletin(document: dict) -> tuple[_RawArea, _RawArea, int]:
    """電文1件の区域・二次細分区域ごとの種別と、その中で読めずに飛ばした項目・種別の数。"""
    warning = document.get("warning")
    if not isinstance(warning, dict):
        warning = {}
    class20_kinds, skipped20 = _parse_area_items(warning.get("class20Items"))
    class10_kinds, skipped10 = _parse_area_items(warning.get("class10Items"))
    return class20_kinds, class10_kinds, skipped20 + skipped10


def _read_kinds(kinds_by_area: _RawArea) -> dict[str, tuple[AreaWarningKind, ...]]:
    """コードを種別の名称へ、状態を発表中かへ読み替える。コードの無い「なし」と表に無いコードは載せない。"""
    return {
        area_code: tuple(
            AreaWarningKind(
                code=kind.code,
                name=WARNING_KINDS[kind.code],
                active=kind.status in _ACTIVE_STATUSES,
                additions=kind.additions,
            )
            for kind in kinds
            if kind.code in WARNING_KINDS
        )
        for area_code, kinds in kinds_by_area.items()
    }


def _parse_bulletins(payload: list, office_code: str) -> list[WarningBulletin]:
    parsed = [_parse_bulletin(document) for document in payload if isinstance(document, dict)]
    unreadable = len(payload) - len(parsed) + sum(skipped for *_, skipped in parsed)
    # 読めない部分は他の警報を出すために飛ばすが、飛ばしたことは取得1回につき1行で出す（logging.md「外部データの読み飛ばし」）。
    # 一部の警報だけが落ちる形は、画面も/api/debug/statsも正常に見える。
    if unreadable:
        logger.warning(
            "気象庁の警報の電文に読めない部分があり読み飛ばしました unreadable=%d bulletins=%d office=%s",
            unreadable, len(payload), office_code,
        )
    # 発表中なのに表に無いコードは、写した表が配信元のコード表より古くなった印。画面へは出さずに飛ばす。
    unknown = sorted({
        kind.code
        for class20_kinds, class10_kinds, _ in parsed
        for kinds in (*class20_kinds.values(), *class10_kinds.values())
        for kind in kinds
        if kind.code is not None and kind.status in _ACTIVE_STATUSES and kind.code not in WARNING_KINDS
    })
    if unknown:
        logger.warning(
            "警報・注意報のコード表に無いコードが発表中 codes=%s office=%s（jma_warning_client.py: WARNING_KINDS）",
            unknown, office_code,
        )
    return [
        WarningBulletin(class20_kinds=_read_kinds(class20_kinds), class10_kinds=_read_kinds(class10_kinds))
        for class20_kinds, class10_kinds, _ in parsed
    ]


async def fetch_area_data(client: httpx.AsyncClient, cache: TTLCache) -> AreaMaster | None:
    """気象庁の地域マスタ(area.json)を取得する。行政区画変更以外では変化しないため
    プロセス内で長時間キャッシュする。"""

    async def fetch() -> AreaMaster:
        payload = await get_json(client, JMA_AREA_JSON_URL, dict, "area master is", timeout=REQUEST_TIMEOUT)
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
        payload = await get_json(
            client,
            JMA_WARNING_URL_TEMPLATE.format(office_code=office_code),
            list,
            "warning bulletins are",
            timeout=REQUEST_TIMEOUT,
        )
        return _parse_bulletins(payload, office_code)

    return await cached_fetch(
        "weather:jma-warning",
        fetch,
        cache=cache,
        key=office_code,
        office_code=office_code,
    )
