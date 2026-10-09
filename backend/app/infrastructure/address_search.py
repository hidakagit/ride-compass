"""住所の区画の表（`address_search_keys`・`address_areas`）を、入力した文字列で引く（地点の検索の住所の候補）。

入力を鍵と同じ揃え方（`domain/address_area.py: standardize_address`）にかけ、鍵を3通りで引く。

- 全部に当たる: 鍵が入力と同じか、入力に区切りを足したもの（「本町2」で二丁目の鍵「本町2-」）。
- 番地付き: 入力の頭に当たる最も長い鍵のうち、残りの頭が番地の形（`NUMBERED_REMAINDER_PATTERN`）のもの
  （「西新宿2-8-1」で二丁目の鍵「西新宿2-」）。番地は持たないので、番地まで打った入力は丁目・字までに当たる。
- 続き: 続きに使う鍵（大字・町の段まで）のうち、入力を頭に持つもの（「西新」で「西新宿」）。長さごとの件数を部分索引で
  数え、短いほうから数えて上限に届く長さまでの鍵だけを引く（1文字の入力でも、当たる鍵の全部を読まない）。

入力の一部にだけ当たった鍵（「小杉湯」の頭の「小杉」で、残りが番地の形でないもの）は引かない。範囲では落とさない
（表に入る区画は派生の段が取込の範囲で決める）。
"""

from collections.abc import Sequence
from itertools import groupby

from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.address_area import (
    ADDRESS_AREA_LEVELS,
    NUMBERED_REMAINDER_PATTERN,
    AddressAreaName,
    address_full_name,
    standardize_address,
)
from app.domain.geo import LatLon
from app.domain.place_search import PLACE_PREDICTION_LIMIT, PLACE_PREDICTION_MIN_LENGTH, PlaceCandidate

#: 続きの件数を長さごとに数える幅（入力より何文字長い鍵まで数えるか）。この幅で上限に届かなければ、長さで切らずに引く。
_CONTINUATION_LENGTH_WINDOW = 40

# 同じ区画に当たった鍵は1件にまとめる（当たり方は「全部に当たる・続き」を、鍵は短いほうを採る）。並びは「全部に当たる・続き」
# → 番地付き、その中は段の粗いもの → 鍵の短いもの → 検索の中心に近いもの（測地の距離）——段を鍵の長さより先にするのは、
# 1文字の入力（「柏」）で同じ名前の大字が上限を埋め、市区町村（「柏市」）が漏れないため。並びの最後の鍵は、同じ位置の
# 区画の並びを毎回同じにするため。表示名は、上限までの区画から`parent_id`をたどった祖先の名前で組み立てる。
# 鍵の等号と`LIKE`は、索引で引けるよう引数を直に比べる（`LIKE`の頭の文字列が別の表の列のように問い合わせを組み立てる時に
# 分からないと、索引の範囲にできず表の全部を読む）。
_SEARCH_SQL = text(f"""
    WITH RECURSIVE hits AS (
        SELECT area_id, 0 AS numbered, length(key) AS len
        FROM address_search_keys
        WHERE key = :query OR key = :query_with_separator
        UNION ALL
        SELECT area_id, 1, len FROM (
            SELECT area_id, length(key) AS len, rank() OVER (ORDER BY length(key) DESC) AS longest
            FROM address_search_keys
            WHERE key = ANY(CAST(:heads AS text[]))
              AND substr(CAST(:query AS text), length(key) + 1) ~ :numbered_remainder
        ) numbered WHERE longest = 1
        UNION ALL
        SELECT area_id, 0, length(key)
        FROM address_search_keys
        WHERE :continues AND continuable AND key LIKE :prefix AND length(key) > :query_length
          AND length(key) <= coalesce((
              SELECT min(counted.n) FROM (
                  SELECT l.n, sum(c.count) OVER (ORDER BY l.n) AS total
                  FROM generate_series(:query_length + 1, :query_length + {_CONTINUATION_LENGTH_WINDOW}) AS l(n),
                       LATERAL (SELECT count(*) AS count FROM address_search_keys
                                WHERE continuable AND length(key) = l.n AND key LIKE :prefix) c
              ) counted
              WHERE counted.total >= CAST(:limit AS integer)), 2147483647)
    ),
    found AS (
        SELECT a.area_id,
               row_number() OVER (ORDER BY min(h.numbered), array_position(CAST(:levels AS text[]), a.level),
                                  min(h.len),
                                  ST_Distance(a.geom::geography,
                                              ST_SetSRID(ST_MakePoint(:near_lon, :near_lat), 4326)::geography),
                                  a.area_id) AS position
        FROM hits h JOIN address_areas a USING (area_id)
        GROUP BY a.area_id, a.level, a.geom
    ),
    chain AS (
        SELECT f.position, 0 AS depth, a.parent_id, a.level, a.name, a.county_name,
               ST_Y(a.geom) AS latitude, ST_X(a.geom) AS longitude
        FROM found f JOIN address_areas a USING (area_id)
        WHERE f.position <= CAST(:limit AS integer)
        UNION ALL
        SELECT c.position, c.depth + 1, p.parent_id, p.level, p.name, p.county_name,
               CAST(NULL AS float8), CAST(NULL AS float8)
        FROM chain c JOIN address_areas p ON p.area_id = c.parent_id
    )
    SELECT position, depth, level, name, county_name, latitude, longitude FROM chain ORDER BY position, depth DESC
""")


def _like_prefix(query: str) -> str:
    """`query`を頭に持つ文字列に当たる`LIKE`の型。入力の`%`・`_`・`\\`は文字として当てる。"""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped + "%"


def _candidate(chain: Sequence[RowMapping]) -> PlaceCandidate:
    """祖先から区画自身まで（粗い→細かい）の行から、区画の候補。位置は区画自身の代表点。"""
    area = chain[-1]
    return PlaceCandidate(
        kind="address", level=area["level"],
        name=address_full_name(AddressAreaName(row["name"], row["county_name"]) for row in chain),
        area=None, latitude=area["latitude"], longitude=area["longitude"])


class AddressSearchQuery:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def search(self, query: str, near: LatLon) -> list[PlaceCandidate]:
        """入力に当たる住所の区画を、当たりの良い順に`PLACE_PREDICTION_LIMIT`件まで（並びは`_SEARCH_SQL`の前の文）。"""
        q = standardize_address(query)
        # 揃えると空になる入力（「大字」）は、空の頭がどの鍵にも当たる。
        if not q:
            return []
        rows = (await self._session.execute(_SEARCH_SQL, {
            "query": q,
            "query_with_separator": q + "-",
            "query_length": len(q),
            "prefix": _like_prefix(q),
            "heads": [q[:n] for n in range(1, len(q))],
            "numbered_remainder": NUMBERED_REMAINDER_PATTERN,
            "continues": len(q) >= PLACE_PREDICTION_MIN_LENGTH,
            "levels": list(ADDRESS_AREA_LEVELS),
            "near_lat": near.latitude, "near_lon": near.longitude,
            "limit": PLACE_PREDICTION_LIMIT,
        })).mappings().all()
        return [_candidate(list(chain)) for _, chain in groupby(rows, key=lambda row: row["position"])]
