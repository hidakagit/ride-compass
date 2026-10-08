"""地点の検索の段取り: 対象範囲と施設をDBから読み、入力を整えて、住所の辞書を範囲の中で引き、住所と施設を並べる。

対象範囲はサービスの対象範囲（取り込んだ道路の範囲、`RegionService.get_ingested_area`）で、範囲の外の地点では
ルートを作れない。辞書は全国を持つ。
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from app.domain.geo import LatLon
from app.domain.place_search import PlaceSearchResult, normalize_place_query
from app.infrastructure.address_dictionary import search_addresses
from app.infrastructure.stop_place_search import StopPlaceSearchQuery
from app.services.region_service import RegionService


class PlaceSearchAreaUnavailable(Exception):
    """対象範囲を読めない（原因は`RegionService.get_ingested_area`がWARNINGで残す）。候補が範囲に入るかを決められない。"""


@dataclass(frozen=True)
class PlaceSearchReads:
    """地点の検索がDBから読むもの。同じ接続で読む。"""

    region: RegionService
    stop_places: StopPlaceSearchQuery


class PlaceSearchService:
    """DBは読む間だけ開く——辞書を引く間にDBの接続を持たない。"""

    def __init__(self, open_reads: Callable[[], AbstractAsyncContextManager[PlaceSearchReads]]):
        self._open_reads = open_reads

    async def search(self, query: str, near: LatLon) -> PlaceSearchResult:
        """施設は`near`に近い順に並べる。辞書を開けなければ`AddressDictionaryUnavailableError`、対象範囲を読めなければ
        `PlaceSearchAreaUnavailable`を送出する。"""
        async with self._open_reads() as reads:
            area = await reads.region.get_ingested_area()
            if area is None:
                raise PlaceSearchAreaUnavailable
            facilities = await reads.stop_places.search(query, area, near)
        addresses = await search_addresses(normalize_place_query(query), area)
        return PlaceSearchResult(candidates=[*addresses.whole, *facilities, *addresses.partial])
