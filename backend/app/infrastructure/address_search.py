"""住所の区画の表（`address_search_keys`・`address_areas`・`address_blocks`）を、入力した文字列で引く（地点の検索の住所の候補）。

入力を鍵と同じ揃え方（`domain/address_area.py: standardize_address`）にかけ、鍵を3通りで引く。

- 全部に当たる: 鍵が入力と同じか、入力に区切りを足したもの（「本町2」で二丁目の鍵「本町2-」）。
- 番地付き: 入力の頭に当たる最も長い鍵のうち、残りの頭が番地の形（`NUMBERED_REMAINDER_PATTERN`）のもの
  （「西新宿2-8-1」で二丁目の鍵「西新宿2-」）。残りの最初の数字（`BLOCK_NUMBER_PATTERN`。「8」）を、その区画の街区の番号
  として街区の表で引き、当たれば街区・地番に、当たらなければ区画（丁目・字か大字）に当たる。号は持たない。
- 続き: 続きに使う鍵（大字・町の段まで）のうち、入力を頭に持つもの（「西新」で「西新宿」）。長さごとの件数を部分索引で
  数え、短いほうから数えて上限に届く長さまでの鍵だけを引く（1文字の入力でも、当たる鍵の全部を読まない）。

入力の一部にだけ当たった鍵（「小杉湯」の頭の「小杉」で、残りが番地の形でないもの）は引かない。範囲では落とさない
（表に入る区画は派生の段が取込の範囲で決める）。
"""

from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.address_area import (
    ADDRESS_AREA_LEVELS,
    BLOCK_NUMBER_PATTERN,
    NUMBERED_REMAINDER_PATTERN,
    area_label,
    block_label,
    standardize_address,
)
from app.domain.geo import LatLon
from app.domain.place_search import PLACE_PREDICTION_LIMIT, PLACE_PREDICTION_MIN_LENGTH, PlaceCandidate

#: 上限までの区画（`found`）ごとに、祖先を都道府県から自分まで並べた段（`levels`）と名前（`names`）の配列を1行ずつ出す。
_AREA_CHAINS = """
WITH RECURSIVE chain AS (
    SELECT a.area_id AS leaf, a.parent_id, a.level, a.name, 0 AS depth
    FROM address_areas a WHERE a.area_id IN (SELECT area_id FROM found WHERE position <= CAST(:limit AS integer))
    UNION ALL
    SELECT c.leaf, a.parent_id, a.level, a.name, c.depth + 1
    FROM chain c JOIN address_areas a ON a.area_id = c.parent_id
)
SELECT leaf AS area_id, array_agg(level ORDER BY depth DESC) AS levels, array_agg(name ORDER BY depth DESC) AS names
FROM chain GROUP BY leaf
"""

#: 続きの件数を長さごとに数える幅（入力より何文字長い鍵まで数えるか）。この幅で上限に届かなければ、長さで切らずに引く。
_CONTINUATION_LENGTH_WINDOW = 40

# 同じ区画に当たった鍵は1件にまとめる（当たり方は良いほうを採る）。並びは「全部に当たる・続き」→ 番地付き、その中は
# 段の粗いもの → 全部に当たるもの → 続き → 検索の中心に近いもの（測地の距離。街区・地番はその点から）——段を当たり方より
# 先にするのは、1文字の入力（「柏」）で同じ名前の大字が上限を埋め、市区町村（「柏市」）が漏れないため。並びの最後の鍵は、同じ位置の
# 区画の並びを毎回同じにするため。表示名は、上限までの区画から`parent_id`をたどった祖先の名前で組み立てる
# （`_AREA_CHAINS`）。
# 鍵の等号と`LIKE`は、索引で引けるよう引数を直に比べる（`LIKE`の頭の文字列が別の表の列のように問い合わせを組み立てる時に
# 分からないと、索引の範囲にできず表の全部を読む）。
_SEARCH_SQL = text(f"""
    WITH hits AS (
        SELECT area_id, 0 AS numbered, 0 AS continued, CAST(NULL AS text) AS number
        FROM address_search_keys
        WHERE key = :query OR key = :query_with_separator
        UNION ALL
        SELECT area_id, 1, 0, number FROM (
            SELECT area_id, rank() OVER (ORDER BY length(key) DESC) AS longest,
                   substring(substr(CAST(:query AS text), length(key) + 1) from :block_number) AS number
            FROM address_search_keys
            WHERE key = ANY(CAST(:heads AS text[]))
              AND substr(CAST(:query AS text), length(key) + 1) ~ :numbered_remainder
        ) numbered WHERE longest = 1
        UNION ALL
        SELECT area_id, 0, 1, NULL
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
        SELECT a.area_id, b.number, b.kind, coalesce(b.geom, a.geom) AS geom,
               row_number() OVER (ORDER BY min(h.numbered), array_position(CAST(:levels AS text[]), a.level), min(h.continued),
                                  ST_Distance(coalesce(b.geom, a.geom)::geography,
                                              ST_SetSRID(ST_MakePoint(:near_lon, :near_lat), 4326)::geography),
                                  a.area_id) AS position
        FROM hits h
        JOIN address_areas a USING (area_id)
        LEFT JOIN address_blocks b ON b.area_id = h.area_id AND b.number = h.number
        GROUP BY a.area_id, a.level, a.geom, b.number, b.kind, b.geom
    )
    SELECT a.level, f.number, f.kind, c.levels, c.names, ST_Y(f.geom) AS latitude, ST_X(f.geom) AS longitude
    FROM found f
    JOIN address_areas a USING (area_id)
    JOIN ({_AREA_CHAINS}) c USING (area_id)
    WHERE f.position <= CAST(:limit AS integer)
    ORDER BY f.position
""")


def _like_prefix(query: str) -> str:
    """`query`を頭に持つ文字列に当たる`LIKE`の型。入力の`%`・`_`・`\\`は文字として当てる。"""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped + "%"


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
            "block_number": BLOCK_NUMBER_PATTERN,
            "continues": len(q) >= PLACE_PREDICTION_MIN_LENGTH,
            "levels": list(ADDRESS_AREA_LEVELS),
            "near_lat": near.latitude, "near_lon": near.longitude,
            "limit": PLACE_PREDICTION_LIMIT,
        })).mappings()
        return [_candidate(row) for row in rows]


def _candidate(row: RowMapping) -> PlaceCandidate:
    """区画か、番地まで当たった街区・地番の候補。"""
    name = area_label(zip(row["levels"], row["names"], strict=True))
    if row["number"] is None:
        return PlaceCandidate(kind="address", level=row["level"], name=name, area=None,
                              latitude=row["latitude"], longitude=row["longitude"])
    return PlaceCandidate(kind="address", level="block", name=block_label(name, row["number"], row["kind"]), area=None,
                          latitude=row["latitude"], longitude=row["longitude"])
