"""住所の区画（`address_areas`）・区画を引く鍵（`address_search_keys`）・小地域の境界に当たる区画（`address_boundary_links`）を、
アドレス・ベース・レジストリ（生データ`abr`）と e-Stat の小地域の境界（`estat_small_area`）から作り直す。

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
  区画のIDの小さいほう。

`abr`の取込が無ければ止まる（区画の無い作り直しは、検索と施設の辺りを黙って空にする）。境界の取込が無ければ結び付きは空。
道の網とは何も読み合わない。施設の辺り（立ち寄り先の段）を区画から決められるよう、立ち寄り先の段より前に置く。
"""

import logging
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

import asyncpg

from app.domain.address_area import (
    ADDRESS_AREA_LEVELS,
    CONTINUABLE_LEVELS,
    MACHIAZA_TYPE_LEVELS,
    search_keys,
    standardize_address,
)
from app.domain.place_search import PlaceMatchLevel
from app.infrastructure.road_graph_repository import INGESTED_BBOX_SQL
from app.infrastructure.source_models import (
    ABR_CITIES_SOURCE_SQL,
    ABR_PREFECTURES_SOURCE_SQL,
    ABR_TOWNS_SOURCE_SQL,
    ESTAT_SMALL_AREAS_SOURCE_SQL,
    Source,
    latest_succeeded_run_sql,
)

logger = logging.getLogger("ridecompass.derive_addresses")

#: 境界の名前の頭・お尻に当てる区画の名前の最短の長さ（揃えた形の文字数）。1文字では無関係な名前に当たる。
_PARTIAL_NAME_MIN_LENGTH = 2

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
        name = row["chome"] if row["chome"] else row["koaza"]
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


def _link_by_name(areas: Sequence[_Area], boundaries: Sequence[asyncpg.Record]) -> list[tuple[str, str]]:
    """名前で結べた (境界のコード, 区画)。"""
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

    links = []
    for boundary in boundaries:
        name = _name_key(boundary["name"])
        if not name:
            continue
        city = boundary["city_code"]
        candidates = [name,
                      *(name[:n] for n in range(len(name) - 1, _PARTIAL_NAME_MIN_LENGTH - 1, -1)),
                      *(name[n:] for n in range(1, len(name) - _PARTIAL_NAME_MIN_LENGTH + 1))]
        hit = next((by_name[(city, c)] for c in candidates if (city, c) in by_name), None)
        if hit is not None:
            links.append((boundary["key_code"], hit))
    return links


async def derive(conn: asyncpg.Connection) -> int:
    """住所の区画・鍵・境界の結び付きを入れ直し、入れた区画の数を返す。"""
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
    async with conn.transaction():
        await conn.execute("TRUNCATE address_boundary_links, address_search_keys, address_areas")
        await conn.execute(_AREAS)
        await conn.copy_records_to_table("_address_areas", records=[
            (a.area_id, a.parent_id, a.level, a.name, a.county_name, *a.point) for a in areas])
        await conn.execute(_INSERT_AREAS)
        await conn.copy_records_to_table("address_search_keys", records=keys,
                                         columns=["key", "area_id", "continuable"])
        await conn.copy_records_to_table("address_boundary_links", records=named, columns=["key_code", "area_id"])
        by_point = int((await conn.execute(_LINK_BY_POINT, ["oaza", "aza"], "aza")).split()[-1])
    await conn.execute("ANALYZE address_areas, address_search_keys, address_boundary_links")
    logger.info("住所: 区画 %d件・鍵 %d件、境界 %d件のうち名前で %d件・代表点で %d件を結んだ / %.1f秒",
                len(areas), len(keys), len(boundaries), len(named), by_point, time.perf_counter() - started)
    return len(areas)
