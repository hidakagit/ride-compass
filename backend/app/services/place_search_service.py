"""地点の検索の段取り: 入力を整え、住所の辞書を引き、対象範囲の外の候補を落とす。

対象範囲はサービスの対象範囲（取り込んだ道路の範囲、`RegionService.get_ingested_area`）で、範囲の外の地点では
ルートを作れない。辞書は全国を持つ。
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from app.domain.place_search import PlaceSearchResult, normalize_place_query
from app.infrastructure.address_dictionary import search_addresses
from app.services.region_service import RegionService


class PlaceSearchAreaUnavailable(Exception):
    """対象範囲を読めない（原因は`RegionService.get_ingested_area`がWARNINGで残す）。候補が範囲に入るかを決められない。"""


class PlaceSearchService:
    """対象範囲は読む間だけ地域サービスを開く——辞書を引く間にDBの接続を持たない。"""

    def __init__(self, open_region_service: Callable[[], AbstractAsyncContextManager[RegionService]]):
        self._open_region_service = open_region_service

    async def search(self, query: str) -> PlaceSearchResult:
        """辞書を開けなければ`AddressDictionaryUnavailableError`、対象範囲を読めなければ
        `PlaceSearchAreaUnavailable`を送出する。"""
        candidates = await search_addresses(normalize_place_query(query))
        async with self._open_region_service() as region_service:
            area = await region_service.get_ingested_area()
        if area is None:
            raise PlaceSearchAreaUnavailable
        return PlaceSearchResult(candidates=[c for c in candidates if area.contains(c)])
