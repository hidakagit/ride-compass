"""立ち寄り先の表（`stop_places`）を施設の名前で引く（地点の検索の施設の候補）。

名前は、派生の段が入れた表記の揺れを除いた形の列（`search_name`）を、入力を同じ式（`domain/stop_place.py: normalized_sql`）で
整えて部分一致で引く。引くたびに名前を整えると表の全部の行に式がかかって遅い（時間は docs/modules/backend/place-search.md
「引き方」）。候補には、派生の段が入れた辺り（`area`）を添える。
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.place_search import PLACE_PREDICTION_LIMIT, PlaceCandidate
from app.domain.region import BoundingBox
from app.domain.stop_place import normalized_sql

# 整えると空になる入力（中点・ハイフンだけ）は、空の文字列がどの名前にも含まれるので引かない。
# 並びの最後の鍵は、同じ名前・同じ確からしさの店の並びを毎回同じにするため。
_SEARCH_SQL = text(f"""
    WITH q AS (SELECT {normalized_sql(":query")} AS name)
    SELECT s.name, s.area, ST_Y(s.geom) AS latitude, ST_X(s.geom) AS longitude
    FROM stop_places s, q
    WHERE q.name <> '' AND strpos(s.search_name, q.name) > 0
      AND s.geom && ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)
    ORDER BY CASE WHEN s.search_name = q.name THEN 0 WHEN starts_with(s.search_name, q.name) THEN 1 ELSE 2 END,
             length(s.name), s.confidence DESC, s.source, s.source_key
    LIMIT :limit
""")


class StopPlaceSearchQuery:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def search(self, query: str, area: BoundingBox) -> list[PlaceCandidate]:
        """対象範囲の中で、名前に入力を含む施設を`PLACE_PREDICTION_LIMIT`件まで。並びは、名前が入力と同じ → 入力で
        始まる → 入力を含む、同じ中では名前の短い順 → 確からしさの高い順。"""
        rows = (await self._session.execute(_SEARCH_SQL, {
            "query": query,
            "min_lat": area.min_latitude, "min_lon": area.min_longitude,
            "max_lat": area.max_latitude, "max_lon": area.max_longitude,
            "limit": PLACE_PREDICTION_LIMIT,
        })).mappings()
        return [
            PlaceCandidate(kind="facility", level="point", name=row["name"], area=row["area"],
                           latitude=row["latitude"], longitude=row["longitude"])
            for row in rows
        ]
