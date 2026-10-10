"""地点の検索の段取り: 対象範囲と住所と施設を同じ接続でDBから読み、住所と施設を並べる。置いた位置の辺りも引く。

対象範囲はサービスの対象範囲（取り込んだ道路の範囲、`RegionService.get_ingested_area`）で、範囲の外の地点では
ルートを作れない。施設は範囲で絞る。住所の区画の表は派生の段が範囲の中の区画だけを入れるので、範囲で絞らない。
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from app.domain.geo import LatLon
from app.domain.place_search import PlaceArea, PlaceSearchResult
from app.infrastructure.address_search import AddressSearchQuery
from app.infrastructure.place_area_query import PlaceAreaQuery
from app.infrastructure.stop_place_search import StopPlaceSearchQuery
from app.services.region_service import RegionService


class PlaceSearchAreaUnavailable(Exception):
    """対象範囲を読めない（原因は`RegionService.get_ingested_area`がWARNINGで残す）。候補が範囲に入るかを決められない。"""


@dataclass(frozen=True)
class PlaceSearchReads:
    """地点の検索がDBから読むもの。同じ接続で読む。"""

    region: RegionService
    addresses: AddressSearchQuery
    stop_places: StopPlaceSearchQuery
    areas: PlaceAreaQuery


class PlaceSearchService:
    def __init__(self, open_reads: Callable[[], AbstractAsyncContextManager[PlaceSearchReads]]):
        self._open_reads = open_reads

    async def search(self, query: str, near: LatLon) -> PlaceSearchResult:
        """住所と施設は`near`に近いものを先に並べる。対象範囲を読めなければ`PlaceSearchAreaUnavailable`を送出する。"""
        async with self._open_reads() as reads:
            area = await reads.region.get_ingested_area()
            if area is None:
                raise PlaceSearchAreaUnavailable
            addresses = await reads.addresses.search(query, near)
            facilities = await reads.stop_places.search(query, area, near)
        return PlaceSearchResult(candidates=[*addresses, *facilities])

    async def area_at(self, point: LatLon) -> PlaceArea:
        """`point`を含む小地域の境界の辺り。範囲では絞らない（境界の生データは取込の範囲に掛かる都道府県の分だけ）。"""
        async with self._open_reads() as reads:
            return PlaceArea(area=await reads.areas.area_at(point))
