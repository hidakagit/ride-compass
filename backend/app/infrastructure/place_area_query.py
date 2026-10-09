"""位置の辺り（地図で置いた地点・現在地の詳しくに出す）を、住所の区画の表と小地域の境界から引く。

区画の決め方は施設の辺りと同じ（`address_area_lookup.py: boundary_area_sql`）で、名前は区画の祖先の並びから
`domain/address_area.py: area_label`が組み立てる。
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.address_area import area_label
from app.domain.geo import LatLon
from app.infrastructure.address_area_lookup import area_chains_sql, boundary_area_sql

_AREA_AT_SQL = text(area_chains_sql(
    f"SELECT {boundary_area_sql('ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)')}"))


class PlaceAreaQuery:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def area_at(self, point: LatLon) -> str | None:
        """`point`の辺り。区画に結んだ境界に含まれなければNone。"""
        row = (await self._session.execute(
            _AREA_AT_SQL, {"latitude": point.latitude, "longitude": point.longitude})).mappings().first()
        return None if row is None else area_label(zip(row["levels"], row["names"], strict=True))
