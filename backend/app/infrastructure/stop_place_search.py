"""立ち寄り先の表（`stop_places`）を施設の名前で引く（地点の検索の施設の候補）。

名前は、派生の段が入れた表記の揺れを除いた形の列（`search_name`）を、入力を同じ式（`domain/stop_place.py: normalized_sql`）で
整えて部分一致で引く。引くたびに名前を整えると表の全部の行に式がかかって遅い（時間は docs/modules/backend/place-search.md
「引き方」）。候補には、派生の段が入れた辺り（`area`）を添える。
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.geo import LatLon
from app.domain.place_search import PLACE_PREDICTION_LIMIT, PlaceCandidate
from app.domain.region import BoundingBox
from app.domain.stop_place import normalized_sql

#: 子午線の曲率半径の下限（m）。WGS84 の赤道での値 a(1−e²)（約 6,335,439m）より小さく丸め、緯度の帯を計算の誤差の分だけ広げる。
_MERIDIAN_RADIUS_LOWER_M = 6_335_000

# 整えると空になる入力（中点・ハイフンだけ）は、空の文字列がどの名前にも含まれるので引かない。
# 近さは測地の距離で測る（度のままの距離は、関東の緯度で東西を2割ほど短く数える）。並びの最後の鍵は、同じ位置の店の
# 並びを毎回同じにするため。
# 文は接続ごとに準備して使い回されるので、入力の値を知らない一般の計画でも速い形にしてある:
# - 整えた入力と中心は副問い合わせにして、行ごとでなく1回だけ求める。
# - 範囲は列を式で包んで`&&`で比べ、範囲の索引を選ばせない。範囲は表のほぼ全部に当たるのに、一般の計画は当たる行を少なく
#   見積もって索引でたどる。座標の大小で比べないのは、`&&`が箱を float4 へ外へ丸めて比べ、範囲の境の外の点も入れるため。
# - 測地の距離は、候補に入りうる行にだけ求める。平面の近さで上限の件数を選んで測地の距離を求め、その最大を上限の件数目の
#   距離の上限にする。測地の距離は緯度の差の子午線の弧より短くならないので、緯度の差がその上限に届かない行だけを並べ直せば、
#   全部の行に測地の距離を求めて並べたのと同じ答えになる。
_SEARCH_SQL = text(f"""
    WITH q AS (
        SELECT (SELECT {normalized_sql(":query")}) AS name,
               (SELECT ST_SetSRID(ST_MakePoint(:near_lon, :near_lat), 4326)::geography) AS center
    ),
    hit AS MATERIALIZED (
        SELECT s.name, s.area, s.geom, s.source, s.source_key,
               CASE WHEN s.search_name = (SELECT name FROM q) THEN 0
                    WHEN starts_with(s.search_name, (SELECT name FROM q)) THEN 1 ELSE 2 END AS rank
        FROM stop_places s
        WHERE (SELECT name FROM q) <> '' AND strpos(s.search_name, (SELECT name FROM q)) > 0
          AND ST_Force2D(s.geom) && ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)
    ),
    nearest AS (
        SELECT rank, ST_Distance(geom::geography, (SELECT center FROM q)) AS distance
        FROM hit
        ORDER BY rank, ((ST_X(geom) - :near_lon) * cos(radians(:near_lat))) ^ 2 + (ST_Y(geom) - :near_lat) ^ 2
        LIMIT :limit
    ),
    bound AS (SELECT rank, max(distance) AS distance FROM nearest GROUP BY rank ORDER BY rank DESC LIMIT 1)
    SELECT h.name, h.area, ST_Y(h.geom) AS latitude, ST_X(h.geom) AS longitude
    FROM hit h, bound b
    WHERE h.rank < b.rank
       OR (h.rank = b.rank AND abs(ST_Y(h.geom) - :near_lat) <= degrees(b.distance / {_MERIDIAN_RADIUS_LOWER_M}))
    ORDER BY h.rank, ST_Distance(h.geom::geography, (SELECT center FROM q)), h.source, h.source_key
    LIMIT :limit
""")


class StopPlaceSearchQuery:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def search(self, query: str, area: BoundingBox, near: LatLon) -> list[PlaceCandidate]:
        """対象範囲の中で、名前に入力を含む施設を`PLACE_PREDICTION_LIMIT`件まで。並びは、名前が入力と同じ → 入力で
        始まる → 入力を含む、同じ中では`near`に近い順——同じ名前の店が上限を超えても、`near`の近くの店が入る。"""
        rows = (await self._session.execute(_SEARCH_SQL, {
            "query": query,
            "min_lat": area.min_latitude, "min_lon": area.min_longitude,
            "max_lat": area.max_latitude, "max_lon": area.max_longitude,
            "near_lat": near.latitude, "near_lon": near.longitude,
            "limit": PLACE_PREDICTION_LIMIT,
        })).mappings()
        return [
            PlaceCandidate(kind="facility", level="point", name=row["name"], area=row["area"],
                           latitude=row["latitude"], longitude=row["longitude"])
            for row in rows
        ]
