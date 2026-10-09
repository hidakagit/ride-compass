"""地点の検索（`GET /api/place-search`）。"""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import get_place_search_service
from app.api.rate_limit import enforce_rate_limit
from app.config import settings
from app.domain.geo import Latitude, LatLonPoint, Longitude
from app.domain.place_search import PlaceQuery, PlaceSearchResult
from app.services.place_search_service import PlaceSearchAreaUnavailable, PlaceSearchService

router = APIRouter()


@router.get("/api/place-search", response_model=PlaceSearchResult)
async def search_places(
    http_request: Request,
    q: PlaceQuery,
    latitude: Latitude,
    longitude: Longitude,
    service: PlaceSearchService = Depends(get_place_search_service),
) -> PlaceSearchResult:
    """入力した文字列に当たる地点の候補（対象範囲の中だけ）。住所と施設は`latitude`・`longitude`（画面が見ている所の
    真ん中）に近いものを先に並べる。何も当たらなければ空の並び。対象範囲を読めなければ502。"""
    enforce_rate_limit(http_request, "place-search", settings.place_search_rate_limit_per_minute)
    try:
        return await service.search(q, LatLonPoint(latitude, longitude))
    except PlaceSearchAreaUnavailable:
        raise HTTPException(status_code=502, detail="対象範囲を読めませんでした") from None
