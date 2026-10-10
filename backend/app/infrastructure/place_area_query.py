"""位置の辺り（施設の辺りと、地図で置いた地点・現在地の詳しくに出す）を、e-Stat の小地域の境界の生データから引く。

辺りは位置を含む境界の市区町村名と町丁・字等の名前を配布の表記のままつないだもの（「川口市元郷四丁目」
「さいたま市岩槻区本町」。都道府県・郡は持たない）。住所の区画の表には結ばない——境界の名前を区画の名前に当てると、
頭・お尻の一致で別の町字に取り違えうる。
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.geo import LatLon
from app.infrastructure.source_models import ESTAT_SMALL_AREAS_SOURCE_SQL


def area_label_sql(point_sql: str) -> str:
    """位置（`point_sql`。4326 の点の式）の辺りを出す副問い合わせ。派生の段も、要求ごとに位置の辺りを引く口も、これを自分の
    接続の問い合わせへ置く。

    辺の上の点は2つの境界に含まれるので、名前を持つ境界のうち鍵の小さいほうにする。名前を持つ境界に含まれなければ
    NULL（海の上・取り込んだ境界の外・名前の無い境界の中）。
    """
    return (f"(SELECT e.city_name || e.name FROM {ESTAT_SMALL_AREAS_SOURCE_SQL} e"
            f" WHERE e.name <> '' AND ST_Covers(e.geom, {point_sql}) ORDER BY e.key_code LIMIT 1)")


_AREA_AT_SQL = text(f"SELECT {area_label_sql('ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)')}")


class PlaceAreaQuery:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def area_at(self, point: LatLon) -> str | None:
        """`point`の辺り。名前を持つ境界に含まれなければNone。"""
        return await self._session.scalar(_AREA_AT_SQL, {"latitude": point.latitude, "longitude": point.longitude})
