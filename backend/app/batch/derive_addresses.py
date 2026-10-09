"""住所の区画（`address_areas`）・区画を引く鍵（`address_search_keys`）・小地域の境界に当たる区画（`address_boundary_links`）・
区画の中の街区と地番（`address_blocks`）を、アドレス・ベース・レジストリ（生データ`abr`）と e-Stat の小地域の境界
（`estat_small_area`）と街区レベル位置参照情報（`isj_block`）から作り直す。

**区画の木はここで作る**。取込は配布の行をそのまま入れるだけで、段・親・範囲の判断は派生の側にある。段の語彙・町字区分と段の
対応・表記の揃え方・鍵の作り方は`domain/address_area.py`が持つ。

- 都道府県・市区町村・区は廃止の日の無い行。区の親は同じ名前の政令市、市区町村の親は都道府県。
- 町字は廃止の日の無い行のうち、区画にする町字区分（`MACHIAZA_TYPE_LEVELS`）のもの。大字・町の親は市区町村（区）、丁目・字の
  親は大字（大字の名前の無い字は市区町村か区）。ABR に大字自身の行が無い大字（代表点が無く取り込まれていないものも）は、
  子の町字IDの頭4桁で1つにまとめ、子の代表点の重心を代表点にする。
- 表に入れるのは、代表点が取込の範囲（道路の成功した最新の取込の範囲。`road_graph_repository.py: INGESTED_BBOX_SQL`）の中に
  ある区画と、その祖先（祖先の代表点は範囲の外でもよい）。道路を取り込んでいなければ何も入れない。
- 鍵は区画ごとに、書き始める段の違う別形を作る（`search_keys`）。丁目は区切り付き（「西新宿2-」）、字は「字」を挟む形と
  挟まない形。大字・町の段までの区画の鍵だけが続き（`continuable`）に使われる。
- 境界は同じ市区町村（5桁）の中で、名前（字の「字」を除いて揃えた形）で順に結ぶ: ①区画の名前（大字＋丁目・字）と同じ
  ②境界の名前の頭に当たる最も長い区画の名前（2文字以上） ③お尻に当たる最も長い区画の名前（2文字以上）。どれにも当たらない
  境界は、中に代表点がある区画（字・丁目を先に）に結ぶ。それも無い境界は行にしない。同じ鍵に区画が2つ以上当たれば
  区画のIDの小さいほう。境界の名前の括弧の中は除いて結ぶ——1つの町丁・字を分けた小地域は、名前の途中に括弧の印を挟む
  （「横山（一）四丁目」「下九沢（番一）」）ので、除かないと頭の大字にしか当たらない。
- 街区は、住居表示の区域では ABR の街区（廃止の日の無い行）を町字の鍵（`<市区町村>`＋`<町字ID>`）でそのまま区画に結ぶ。
  それ以外の区域は、位置参照情報の住居表示でない行を、市区町村の名前（郡・政令市の区を含む書き方）で市区町村に当て、
  その中で大字・丁目名＋小字・通称名を境界と同じ名前の結び方で区画に結ぶ。ABR の街区を1つでも持つ区画（住居表示の区域）
  には位置参照情報の地番を入れない。同じ区画に同じ番号が2つ以上当たれば（区画にしない小字の地番が大字に寄る等）1つにする。

`abr`の取込が無ければ止まる（区画の無い作り直しは、検索と施設の辺りを黙って空にする）。境界の取込が無ければ結び付きは空、
位置参照情報の取込が無ければ地番は空（住居表示の街区は入る）。
道の網とは何も読み合わない。施設の辺り（立ち寄り先の段）を区画から決められるよう、立ち寄り先の段より前に置く。
"""

import logging
import re
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

import asyncpg

from app.domain.address_area import (
    ADDRESS_AREA_LEVELS,
    CONTINUABLE_LEVELS,
    MACHIAZA_TYPE_LEVELS,
    chome_name,
    search_keys,
    standardize_address,
)
from app.domain.place_search import PlaceMatchLevel
from app.infrastructure.road_graph_repository import INGESTED_BBOX_SQL
from app.infrastructure.source_models import (
    ABR_BLOCKS_SOURCE_SQL,
    ABR_CITIES_SOURCE_SQL,
    ABR_PREFECTURES_SOURCE_SQL,
    ABR_TOWNS_SOURCE_SQL,
    ESTAT_SMALL_AREAS_SOURCE_SQL,
    ISJ_BLOCKS_SOURCE_SQL,
    Source,
    latest_succeeded_run_sql,
)

logger = logging.getLogger("ridecompass.derive_addresses")

#: 境界の名前の頭・お尻に当てる区画の名前の最短の長さ（揃えた形の文字数）。1文字では無関係な名前に当たる。
_PARTIAL_NAME_MIN_LENGTH = 2

#: 境界の名前の括弧とその中（全角・半角）。
_PARENTHESIZED = re.compile(r"[（(][^）)]*[）)]")

_AREAS = """
CREATE TEMP TABLE _address_areas (
    area_id text, parent_id text, level text, name text, county_name text, lon float8, lat float8
) ON COMMIT DROP
"""

_INSERT_AREAS = """
INSERT INTO address_areas (area_id, parent_id, level, name, county_name, geom)
SELECT area_id, parent_id, level, name, county_name, ST_SetSRID(ST_MakePoint(lon, lat), 4326) FROM _address_areas
"""

#: 名前で結べなかった境界を、中に代表点がある区画（字・丁目を先に）に結ぶ。
_LINK_BY_POINT = f"""
INSERT INTO address_boundary_links (key_code, area_id)
SELECT DISTINCT ON (e.key_code) e.key_code, a.area_id
FROM {ESTAT_SMALL_AREAS_SOURCE_SQL} e
JOIN address_areas a ON a.level = ANY($1::text[]) AND ST_Covers(e.geom, a.geom)
WHERE NOT EXISTS (SELECT 1 FROM address_boundary_links l WHERE l.key_code = e.key_code)
ORDER BY e.key_code, a.level = $2 DESC, a.area_id
"""


#: 住居表示の区域の街区を、町字の鍵で区画に結んで入れる。
_INSERT_RESIDENTIAL_BLOCKS = f"""
INSERT INTO address_blocks (area_id, number, kind, geom)
SELECT DISTINCT ON (a.area_id, b.number) a.area_id, b.number, 'residential', ST_SetSRID(ST_MakePoint(b.lon, b.lat), 4326)
FROM {ABR_BLOCKS_SOURCE_SQL} b
JOIN address_areas a ON a.area_id = b.city_code || b.town_id
WHERE b.abolished = '' AND b.number <> ''
ORDER BY a.area_id, b.number, b.lon, b.lat
"""

_PARCEL_LINKS = """
CREATE TEMP TABLE _parcel_links (prefecture text, city text, oaza text, koaza text, area_id text) ON COMMIT DROP
"""

#: 住居表示でない区域の地番を、名前で結べた区画に入れる。住居表示の街区を持つ区画には入れない。
_INSERT_PARCELS = f"""
INSERT INTO address_blocks (area_id, number, kind, geom)
SELECT DISTINCT ON (l.area_id, i.number) l.area_id, i.number, 'parcel', i.geom
FROM {ISJ_BLOCKS_SOURCE_SQL} i
JOIN _parcel_links l USING (prefecture, city, oaza, koaza)
WHERE NOT i.residential AND i.number <> ''
  AND NOT EXISTS (SELECT 1 FROM address_blocks b WHERE b.area_id = l.area_id)
ORDER BY l.area_id, i.number, i.koaza
"""

_PARCEL_NAMES = f"""
SELECT prefecture, city, oaza, koaza FROM {ISJ_BLOCKS_SOURCE_SQL} i WHERE NOT residential GROUP BY 1, 2, 3, 4
"""


@dataclass(frozen=True)
class _Area:
    area_id: str
    parent_id: str | None
    level: PlaceMatchLevel
    name: str
    county_name: str | None
    #: (経度, 緯度)。
    point: tuple[float, float]
    keys: frozenset[str]


def _point(row: asyncpg.Record) -> tuple[float, float]:
    return (row["lon"], row["lat"])


def _build_areas(prefectures: Sequence[asyncpg.Record], cities: Sequence[asyncpg.Record],
                 towns: Sequence[asyncpg.Record]) -> dict[str, _Area]:
    """生データの行から、全部の区画（範囲で選ぶ前）を作る。"""
    areas: dict[str, _Area] = {}
    prefecture_ids: dict[str, str] = {}
    for row in prefectures:
        if row["abolished"]:
            continue
        prefecture_ids[row["code"][:2]] = row["code"]
        areas[row["code"]] = _Area(row["code"], None, "prefecture", row["name"], None, _point(row),
                                   search_keys([("prefecture", row["name"])]))

    current = [row for row in cities if not row["abolished"] and row["code"][:2] in prefecture_ids]
    designated = {(row["prefecture"], row["city"]): row["code"] for row in current if not row["ward"]}
    for row in current:
        prefecture_id = prefecture_ids[row["code"][:2]]
        heads = [("prefecture", row["prefecture"]), ("county", row["county"]), ("city", row["city"])]
        if row["ward"]:
            parent = designated.get((row["prefecture"], row["city"]), prefecture_id)
            areas[row["code"]] = _Area(row["code"], parent, "ward", row["ward"], None, _point(row),
                                       search_keys([*heads, ("ward", row["ward"])]))
        else:
            areas[row["code"]] = _Area(row["code"], prefecture_id, "city", row["city"], row["county"] or None,
                                       _point(row), search_keys(heads))

    # 大字自身の行が無いときに作る大字の名前・鍵の段と、子の代表点。
    unowned_oaza: dict[str, tuple[str, str, list[tuple[str, str]]]] = {}
    child_points: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in towns:
        level = MACHIAZA_TYPE_LEVELS.get(row["town_type"])
        city = areas.get(row["city_code"])
        if row["abolished"] or level is None or city is None or city.level not in ("city", "ward"):
            continue
        area_id = row["city_code"] + row["town_id"]
        heads = [("prefecture", row["prefecture"]), ("county", row["county"]), ("city", row["city"]),
                 ("ward", row["ward"])]
        if level == "oaza":
            areas[area_id] = _Area(area_id, row["city_code"], "oaza", row["oaza"], None, _point(row),
                                   search_keys([*heads, ("oaza", row["oaza"])]))
            continue
        name = chome_name(row["chome_number"], row["chome"]) if row["chome"] else row["koaza"]
        if not name:
            continue
        if row["chome"]:
            tails: tuple[str, ...] = (name,)
        else:
            bare = name.removeprefix("字")
            tails = (bare, "字" + bare)
        parent = row["city_code"]
        if row["oaza"]:
            # 大字自身の行の町字IDは、子の頭4桁に`000`をつないだもの。
            parent = row["city_code"] + row["town_id"][:4] + "000"
            unowned_oaza.setdefault(parent, (row["city_code"], row["oaza"], heads))
            child_points[parent].append(_point(row))
            heads = [*heads, ("oaza", row["oaza"])]
        areas[area_id] = _Area(area_id, parent, "aza", name, None, _point(row), search_keys(heads, tails))

    for oaza_id, (city_code, name, heads) in unowned_oaza.items():
        if oaza_id in areas:
            continue
        points = child_points[oaza_id]
        center = (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))
        areas[oaza_id] = _Area(oaza_id, city_code, "oaza", name, None, center,
                               search_keys([*heads, ("oaza", name)]))
    return areas


def _in_range(areas: dict[str, _Area], bbox: asyncpg.Record | None) -> list[_Area]:
    """代表点が範囲の中にある区画と、その祖先。粗い段から並べる（親が子より先）。"""
    if bbox is None:
        return []
    chosen: set[str] = set()
    for area in areas.values():
        lon, lat = area.point
        if not (bbox["min_lat"] <= lat <= bbox["max_lat"] and bbox["min_lon"] <= lon <= bbox["max_lon"]):
            continue
        current: str | None = area.area_id
        while current is not None and current not in chosen:
            chosen.add(current)
            current = areas[current].parent_id
    order = {level: index for index, level in enumerate(ADDRESS_AREA_LEVELS)}
    return sorted((areas[area_id] for area_id in chosen), key=lambda a: (order[a.level], a.area_id))


def _name_key(name: str) -> str:
    """境界と区画を名前で結ぶ形。字の「字」を除いて揃え、丁目の区切りの`-`を末尾から除く（「２丁目」→「2」）。"""
    return standardize_address(name.removeprefix("字")).replace("字", "").rstrip("-")


def _names_by_city(areas: Sequence[_Area]) -> dict[tuple[str, str], str]:
    """(市区町村（5桁）, 区画の名前（大字＋丁目・字を揃えた形）) → 区画。同じ鍵に区画が2つ以上当たれば区画のIDの小さいほう。"""
    by_id = {area.area_id: area for area in areas}
    by_name: dict[tuple[str, str], str] = {}
    for area in areas:
        if area.level not in ("oaza", "aza"):
            continue
        parent = by_id.get(area.parent_id or "")
        full = parent.name + area.name if area.level == "aza" and parent is not None and parent.level == "oaza" \
            else area.name
        key = (area.area_id[:5], _name_key(full))
        if key not in by_name or area.area_id < by_name[key]:
            by_name[key] = area.area_id
    return by_name


def _match_name(by_name: dict[tuple[str, str], str], city: str, written: str) -> str | None:
    """`city`（5桁）の中で名前`written`に当たる区画。同じ → 頭に当たる最も長い → お尻に当たる最も長い（2文字以上）の順。
    名前の括弧の中は除く。"""
    name = _name_key(_PARENTHESIZED.sub("", written))
    if not name:
        return None
    candidates = [name,
                  *(name[:n] for n in range(len(name) - 1, _PARTIAL_NAME_MIN_LENGTH - 1, -1)),
                  *(name[n:] for n in range(1, len(name) - _PARTIAL_NAME_MIN_LENGTH + 1))]
    return next((by_name[(city, c)] for c in candidates if (city, c) in by_name), None)


def _link_by_name(areas: Sequence[_Area], boundaries: Sequence[asyncpg.Record]) -> list[tuple[str, str]]:
    """名前で結べた (境界のコード, 区画)。"""
    by_name = _names_by_city(areas)
    links = []
    for boundary in boundaries:
        hit = _match_name(by_name, boundary["city_code"], boundary["name"])
        if hit is not None:
            links.append((boundary["key_code"], hit))
    return links


def _cities_by_name(areas: Sequence[_Area]) -> dict[tuple[str, str], str]:
    """(都道府県の名前, 市区町村の名前を揃えた形) → 市区町村（5桁）。名前は市区町村だけの形・郡を付けた形・政令市の区は
    市と区をつないだ形（街区レベル位置参照情報の市区町村名の書き方）。"""
    by_id = {area.area_id: area for area in areas}
    cities: dict[tuple[str, str], str] = {}
    for area in areas:
        if area.level not in ("city", "ward"):
            continue
        chain = [area]
        while chain[-1].parent_id is not None:
            chain.append(by_id[chain[-1].parent_id])
        prefecture = chain[-1].name
        if area.level == "ward":
            names = [chain[1].name + area.name] if chain[1].level == "city" else [area.name]
        else:
            names = [area.name, (area.county_name or "") + area.name]
        for name in names:
            cities[(prefecture, standardize_address(name))] = area.area_id[:5]
    return cities


def _link_parcels(areas: Sequence[_Area], names: Sequence[asyncpg.Record]) -> list[tuple[str, str, str, str, str]]:
    """地番の名前（都道府県・市区町村・大字・丁目・小字）ごとに、境界と同じ結び方（`_match_name`）で結べた区画。"""
    cities = _cities_by_name(areas)
    by_name = _names_by_city(areas)
    links = []
    for row in names:
        city = cities.get((row["prefecture"], standardize_address(row["city"])))
        hit = None if city is None else _match_name(by_name, city, row["oaza"] + row["koaza"])
        if hit is not None:
            links.append((row["prefecture"], row["city"], row["oaza"], row["koaza"], hit))
    return links


async def derive(conn: asyncpg.Connection) -> int:
    """住所の区画・鍵・境界の結び付き・街区を入れ直し、入れた区画の数を返す。"""
    started = time.perf_counter()
    if await conn.fetchval(f"SELECT run_id FROM {latest_succeeded_run_sql(Source.ABR)} latest") is None:
        raise RuntimeError("住所の生データ（abr）の取込が無い。scripts/fetch_abr.py と"
                           " ingest_cli --source abr を流してから作り直す")
    bbox = await conn.fetchrow(INGESTED_BBOX_SQL)
    areas = _in_range(_build_areas(await conn.fetch(ABR_PREFECTURES_SOURCE_SQL), await conn.fetch(ABR_CITIES_SOURCE_SQL),
                                   await conn.fetch(ABR_TOWNS_SOURCE_SQL)), bbox)
    boundaries = await conn.fetch(f"SELECT key_code, city_code, name FROM {ESTAT_SMALL_AREAS_SOURCE_SQL} e")
    keys = [(key, area.area_id, area.level in CONTINUABLE_LEVELS) for area in areas for key in sorted(area.keys)]
    named = _link_by_name(areas, boundaries)
    parcel_links = _link_parcels(areas, await conn.fetch(_PARCEL_NAMES))
    async with conn.transaction():
        await conn.execute("TRUNCATE address_blocks, address_boundary_links, address_search_keys, address_areas")
        await conn.execute(_AREAS)
        await conn.copy_records_to_table("_address_areas", records=[
            (a.area_id, a.parent_id, a.level, a.name, a.county_name, *a.point) for a in areas])
        await conn.execute(_INSERT_AREAS)
        await conn.copy_records_to_table("address_search_keys", records=keys,
                                         columns=["key", "area_id", "continuable"])
        await conn.copy_records_to_table("address_boundary_links", records=named, columns=["key_code", "area_id"])
        by_point = int((await conn.execute(_LINK_BY_POINT, ["oaza", "aza"], "aza")).split()[-1])
        residential = int((await conn.execute(_INSERT_RESIDENTIAL_BLOCKS)).split()[-1])
        await conn.execute(_PARCEL_LINKS)
        await conn.copy_records_to_table("_parcel_links", records=parcel_links)
        parcels = int((await conn.execute(_INSERT_PARCELS)).split()[-1])
    await conn.execute("ANALYZE address_areas, address_search_keys, address_boundary_links, address_blocks")
    logger.info("住所: 区画 %d件・鍵 %d件、境界 %d件のうち名前で %d件・代表点で %d件を結んだ。街区 %d件・地番 %d件"
                "（地番の名前 %d通りを区画に結んだ） / %.1f秒",
                len(areas), len(keys), len(boundaries), len(named), by_point, residential, parcels,
                len(parcel_links), time.perf_counter() - started)
    return len(areas)
