from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import client_id, get_weather_service
from app.config import settings
from app.domain.route import Coordinates
from app.domain.weather import WeatherConditions
from app.domain.wind_grid import WindGridPoint, generate_wind_grid_points
from app.infrastructure.debug_log import record_rate_limit_rejection
from app.infrastructure.rate_limiter import check_rate_limit
from app.services.weather_service import WeatherService

router = APIRouter()


@router.get("/api/weather", response_model=WeatherConditions)
async def get_weather(
    http_request: Request,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    weather_service: WeatherService = Depends(get_weather_service),
) -> WeatherConditions:
    # 以前はここでの範囲チェックをCoordinates（Pydanticモデル）任せにしており、
    # 範囲外の値（例: latitude=999）はFastAPIの422ではなくpydantic.ValidationErrorが
    # 関数内から送出され未処理の500になっていた。Queryのge/leでFastAPI層で弾く。
    if not check_rate_limit(f"weather:{client_id(http_request)}", settings.weather_rate_limit_per_minute):
        record_rate_limit_rejection(
            "weather", client_id(http_request), f"{settings.weather_rate_limit_per_minute}/min"
        )
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    conditions = await weather_service.get_conditions(Coordinates(latitude=latitude, longitude=longitude))
    if conditions is None:
        raise HTTPException(status_code=502, detail="天候情報の取得に失敗しました")
    return conditions


@router.get("/api/weather/wind-grid", response_model=list[WindGridPoint])
async def get_wind_grid(
    http_request: Request,
    weather_service: WeatherService = Depends(get_weather_service),
) -> list[WindGridPoint]:
    """風の格子点マップ（改善計画T178フォローアップ）。関東本土全域の固定格子点
    （domain/wind_grid.py: WIND_GRID_BBOX/WIND_GRID_SPACING_DEG）ぶんの時間別風向・風速を
    まとめて返す。取得に失敗した地点はレスポンスから除外する（他の外部API連携と同じ
    「取得失敗は握りつぶす」方針、1地点の失敗で全体を502にしない）。"""
    if not check_rate_limit(f"wind-grid:{client_id(http_request)}", settings.wind_grid_rate_limit_per_minute):
        record_rate_limit_rejection(
            "wind-grid", client_id(http_request), f"{settings.wind_grid_rate_limit_per_minute}/min"
        )
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    grid = await weather_service.get_wind_grid(generate_wind_grid_points())
    return [point for point in grid if point is not None]
