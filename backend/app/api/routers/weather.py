import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError

from app.api.dependencies import (
    get_amedas_service,
    get_flood_service,
    get_ingested_area,
    get_warning_service,
    get_wbgt_service,
    get_weather_service,
)
from app.api.rate_limit import enforce_rate_limit
from app.config import settings
from app.domain.geo import Latitude, Longitude
from app.domain.jma_amedas import AmedasObservation
from app.domain.region import BoundingBox
from app.domain.route import Coordinates
from app.domain.time_zone import JST
from app.domain.weather import WeatherConditions
from app.domain.wind_grid import (
    WIND_GRID_DETAIL_MAX_POINTS,
    WIND_GRID_DETAIL_MIN_SPACING_DEG,
    WIND_GRID_DETAIL_SPACING_DEG,
    WindGridResponse,
    count_wind_grid_detail_points,
    generate_wind_grid_detail_points,
    generate_wind_grid_points,
)
from app.services.flood_service import FloodForecasts, FloodService
from app.services.warning_service import WarningService, WeatherWarnings
from app.services.wbgt_service import WbgtService, WbgtStatus
from app.services.jma_amedas_service import JmaAmedasService
from app.services.weather_service import WeatherService

logger = logging.getLogger("ridecompass.weather")

router = APIRouter()

# 警報系バッジの失敗の文。画面は出所の名前を前に付けて出す（「警報・注意報: 取得できませんでした。」）。
_BADGE_SOURCE_UNAVAILABLE = "取得できませんでした。"


@router.get("/api/weather", response_model=WeatherConditions)
async def get_weather(
    http_request: Request,
    latitude: Latitude,
    longitude: Longitude,
    weather_service: WeatherService = Depends(get_weather_service),
) -> WeatherConditions:
    """「今日」のパネル（1日の最大・最小と一定間隔のコマ）向けの、数値予報モデル（MSM）の計算値。
    常設ヘッダー（現在値の気温・体感温度・風速風向）はアメダス実測を使う
    `GET /api/weather/amedas`が担う。"""
    enforce_rate_limit(http_request, "weather", settings.weather_rate_limit_per_minute)
    conditions = await weather_service.get_conditions(Coordinates(latitude=latitude, longitude=longitude))
    if conditions is None:
        raise HTTPException(status_code=502, detail="天候情報の取得に失敗しました")
    return conditions


@router.get("/api/weather/warnings", response_model=WeatherWarnings)
async def get_weather_warnings(
    http_request: Request,
    latitude: Latitude,
    longitude: Longitude,
    warning_service: WarningService = Depends(get_warning_service),
) -> WeatherWarnings:
    """出発地点近傍のJMA警報・注意報を、サイクリングに関連する種別へ絞ってバッジ用に返す。
    地点→区域→警報エリアの解決か、警報自体の取得に失敗したら502（空の応答は「警報なし」だけを表す）。"""
    enforce_rate_limit(http_request, "weather-warnings", settings.weather_warnings_rate_limit_per_minute)
    warnings = await warning_service.get_warnings(Coordinates(latitude=latitude, longitude=longitude))
    if warnings is None:
        raise HTTPException(status_code=502, detail=_BADGE_SOURCE_UNAVAILABLE)
    return warnings


@router.get("/api/weather/wbgt", response_model=WbgtStatus)
async def get_wbgt(
    http_request: Request,
    latitude: Latitude,
    longitude: Longitude,
    wbgt_service: WbgtService = Depends(get_wbgt_service),
) -> WbgtStatus:
    """出発地点近傍の暑さ指数（WBGT）警戒レベルをバッジ用に返す。
    「ほぼ安全」（21未満）と、提供期間の外で今の時刻の値が得られないときは空（reading=None）。
    提供期間の中で地点解決・取得に失敗したか今の時刻の値が得られなければ502。"""
    enforce_rate_limit(http_request, "weather-wbgt", settings.weather_wbgt_rate_limit_per_minute)
    status = await wbgt_service.get_status(Coordinates(latitude=latitude, longitude=longitude), datetime.now(JST))
    if status is None:
        raise HTTPException(status_code=502, detail=_BADGE_SOURCE_UNAVAILABLE)
    return status


@router.get("/api/weather/flood-forecast", response_model=FloodForecasts)
async def get_flood_forecast(
    http_request: Request,
    latitude: Latitude,
    longitude: Longitude,
    flood_service: FloodService = Depends(get_flood_service),
) -> FloodForecasts:
    """出発地点近傍のJMA指定河川洪水予報（レベル2〜5）をバッジ用に返す。
    地点解決か洪水予報自体の取得に失敗したら502（空の応答は「予報なし」だけを表す）。"""
    enforce_rate_limit(
        http_request, "weather-flood-forecast", settings.weather_flood_forecast_rate_limit_per_minute
    )
    forecasts = await flood_service.get_forecasts(Coordinates(latitude=latitude, longitude=longitude))
    if forecasts is None:
        raise HTTPException(status_code=502, detail=_BADGE_SOURCE_UNAVAILABLE)
    return forecasts


@router.get("/api/weather/amedas", response_model=AmedasObservation)
async def get_amedas(
    http_request: Request,
    latitude: Latitude,
    longitude: Longitude,
    amedas_service: JmaAmedasService = Depends(get_amedas_service),
) -> AmedasObservation:
    """出発地点近傍の最寄りアメダス観測所の直近観測値を返す。
    観測値本体はRedis Hash（TTL 15分）でキャッシュされる（infrastructure/jma_amedas_store.py参照）。
    観測所解決・取得のいずれかに失敗した場合は502を返す。"""
    enforce_rate_limit(http_request, "amedas", settings.weather_amedas_rate_limit_per_minute)
    observation = await amedas_service.get_nearest_observation(Coordinates(latitude=latitude, longitude=longitude))
    if observation is None:
        raise HTTPException(status_code=502, detail="アメダス観測値の取得に失敗しました")
    return observation


def _require_grid(label: str, grid: WindGridResponse | None) -> WindGridResponse:
    """読めなかった格子（MSMの同期が未完了・予報が現在時刻へ追いついていない等）は502。空の格子で返すと、
    画面は風が無いのと区別できない。"""
    if grid is None:
        logger.warning("%s: 格子を読めませんでした（MSM未同期の可能性）", label)
        raise HTTPException(status_code=502, detail="気象データの取得に失敗しました")
    return grid


def _require_area(area: BoundingBox | None) -> BoundingBox:
    """格子を敷く対象範囲。読めなければ格子を組めないので502（原因は`get_ingested_area`がWARNINGで残す）。"""
    if area is None:
        raise HTTPException(status_code=502, detail="対象範囲を読めませんでした")
    return area


@router.get("/api/weather/wind-grid", response_model=WindGridResponse)
async def get_wind_grid(
    http_request: Request,
    weather_service: WeatherService = Depends(get_weather_service),
    area: BoundingBox | None = Depends(get_ingested_area),
) -> WindGridResponse:
    """風・降水（数値予報モデルの計算値）の格子点マップ。
    対象範囲（取り込んだ道路の範囲）全体の固定格子点（domain/wind_grid.py: generate_wind_grid_points）
    ぶんの時間別風向・風速・降水量をまとめて返す。読めなければ502（_require_grid）。
    時刻配列はpoints内の各点からは外し、応答トップレベルに1本だけ持つ
    （WindGridResponseのdocstring参照）。"""
    enforce_rate_limit(http_request, "wind-grid", settings.wind_grid_rate_limit_per_minute)
    points = generate_wind_grid_points(_require_area(area))
    return _require_grid("wind-grid", await weather_service.get_wind_grid(points))


@router.get("/api/weather/wind-grid-detail", response_model=WindGridResponse)
async def get_wind_grid_detail(
    http_request: Request,
    min_lon: Longitude,
    min_lat: Latitude,
    max_lon: Longitude,
    max_lat: Latitude,
    # 無限大の間隔は索引0の点の座標をNaNにする（0×inf）。
    spacing_deg: float = Query(default=WIND_GRID_DETAIL_SPACING_DEG, allow_inf_nan=False),
    weather_service: WeatherService = Depends(get_weather_service),
    area: BoundingBox | None = Depends(get_ingested_area),
) -> WindGridResponse:
    """風・降水（数値予報モデルの計算値）の詳細格子（ヒートマップ等の面表現用、spacing_degでズーム依存の間隔を
    可変化）。呼び出し元（フロント）が渡した表示範囲（bbox）に交差する
    密格子点（domain/wind_grid.py: generate_wind_grid_detail_points、固定ラティス上の座標）
    ぶんの時間別風向・風速・降水量を返す。get_wind_gridと同じく時刻配列は応答トップレベルに1本だけ持つ。

    spacing_degはWIND_GRID_DETAIL_MIN_SPACING_DEG以上の有限の値を受け付ける。
    読めなければ502（_require_grid）。"""
    enforce_rate_limit(http_request, "wind-grid-detail", settings.wind_grid_detail_rate_limit_per_minute)
    try:
        bbox = BoundingBox(min_latitude=min_lat, min_longitude=min_lon, max_latitude=max_lat, max_longitude=max_lon)
    except ValidationError:
        raise HTTPException(status_code=400, detail="表示範囲が不正です。") from None
    if spacing_deg < WIND_GRID_DETAIL_MIN_SPACING_DEG:
        raise HTTPException(status_code=400, detail="spacing_degの値が不正です。")
    target = _require_area(area)
    # 点を作る処理は同期でイベントループを止めるため、上限を超える範囲は作る前に断る。
    if count_wind_grid_detail_points(target, bbox, spacing_deg) > WIND_GRID_DETAIL_MAX_POINTS:
        raise HTTPException(status_code=400, detail="表示範囲が広すぎます。ズームインしてください。")
    points = generate_wind_grid_detail_points(target, bbox, spacing_deg)
    return _require_grid("wind-grid-detail", await weather_service.get_wind_grid(points))
