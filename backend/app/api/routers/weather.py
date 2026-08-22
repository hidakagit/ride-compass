import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import client_id, get_weather_service
from app.config import settings
from app.domain.route import Coordinates
from app.domain.weather import WeatherConditions
from app.domain.wind_grid import (
    WIND_GRID_DETAIL_ALLOWED_SPACINGS_DEG,
    WIND_GRID_DETAIL_MAX_POINTS,
    WIND_GRID_DETAIL_SPACING_DEG,
    WindGridPoint,
    generate_wind_grid_detail_points,
    generate_wind_grid_points,
)
from app.infrastructure.debug_log import record_rate_limit_rejection
from app.infrastructure.rate_limiter import check_rate_limit
from app.services.weather_service import WeatherService

logger = logging.getLogger("ridecompass.weather")

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


def _reject_if_all_points_failed(label: str, points: list, grid: list) -> None:
    """全地点が取得失敗（Open-Meteo全滅、429常態化等）の場合のみ502で明示的に失敗を返す
    （改善計画T200、統合レビュー2026-08-22指摘）。以前は1地点の失敗を握りつぶす方針
    （T178）のまま全地点失敗時も空リスト+200 OKを返しており、フロントの`windError`
    表示が機能せず「時刻スライダーが動かせるコマが無い」という形でしか症状が見えず
    診断に実機コンソール計装を要した（T194の根本原因調査で判明）。`/api/weather`
    （単一地点）は取得失敗を502で返す設計のため、この非対称を解消する。1地点でも
    成功していれば従来どおり部分結果を200で返す（1地点の失敗で全体を落とさない
    というT178の方針自体は維持）。`WeatherService.get_wind_grid`は常に`points`と
    同じ長さの結果（失敗地点はNone）を返す契約のため、`grid`が空のまま（=呼び出し自体が
    行われていない等）のケースは対象外にする（`grid and`のチェック）。"""
    if points and grid and all(point is None for point in grid):
        logger.warning("%s: 全%d地点が取得失敗しました（Open-Meteo障害の可能性）", label, len(points))
        raise HTTPException(status_code=502, detail="気象データの取得に失敗しました")


@router.get("/api/weather/wind-grid", response_model=list[WindGridPoint])
async def get_wind_grid(
    http_request: Request,
    weather_service: WeatherService = Depends(get_weather_service),
) -> list[WindGridPoint]:
    """風・降水延長予報の格子点マップ（改善計画T178フォローアップ、T183で降水を追加）。
    関東本土全域の固定格子点（domain/wind_grid.py: WIND_GRID_BBOX/WIND_GRID_SPACING_DEG）
    ぶんの時間別風向・風速・降水量をまとめて返す。取得に失敗した地点はレスポンスから
    除外する（他の外部API連携と同じ「取得失敗は握りつぶす」方針、1地点の失敗で全体を
    502にしない）。ただし全地点が失敗した場合は502を返す（改善計画T200、
    _reject_if_all_points_failed参照）。"""
    if not check_rate_limit(f"wind-grid:{client_id(http_request)}", settings.wind_grid_rate_limit_per_minute):
        record_rate_limit_rejection(
            "wind-grid", client_id(http_request), f"{settings.wind_grid_rate_limit_per_minute}/min"
        )
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    points = generate_wind_grid_points()
    grid = await weather_service.get_wind_grid(points)
    _reject_if_all_points_failed("wind-grid", points, grid)
    return [point for point in grid if point is not None]


@router.get("/api/weather/wind-grid-detail", response_model=list[WindGridPoint])
async def get_wind_grid_detail(
    http_request: Request,
    min_lon: float = Query(ge=-180, le=180),
    min_lat: float = Query(ge=-90, le=90),
    max_lon: float = Query(ge=-180, le=180),
    max_lat: float = Query(ge=-90, le=90),
    spacing_deg: float = Query(default=WIND_GRID_DETAIL_SPACING_DEG),
    weather_service: WeatherService = Depends(get_weather_service),
) -> list[WindGridPoint]:
    """風・降水延長予報の詳細格子（改善計画T180、ヒートマップ等の面表現用。T185でspacing_deg
    をズーム依存にして間隔可変化）。呼び出し元（フロント）が渡した表示範囲（bbox）に交差する
    密格子点（domain/wind_grid.py: generate_wind_grid_detail_points、固定ラティス上の座標の
    ため近い範囲を見る別ユーザーとキャッシュを共有できる）ぶんの時間別風向・風速・降水量を
    返す。get_wind_gridと同じく取得失敗地点は結果から除外する。

    spacing_degはWIND_GRID_DETAIL_ALLOWED_SPACINGS_DEGの離散値のみ許可する（任意の連続値を
    許すとユーザーごとにラティスの絶対座標がずれてキャッシュ共有が効かなくなるため、
    フロント側windLayer.ts: windGridDetailSpacingDegForZoomと同じ段階に固定する）。
    全地点が失敗した場合は502を返す（改善計画T200、_reject_if_all_points_failed参照）。"""
    if not check_rate_limit(
        f"wind-grid-detail:{client_id(http_request)}", settings.wind_grid_detail_rate_limit_per_minute
    ):
        record_rate_limit_rejection(
            "wind-grid-detail", client_id(http_request), f"{settings.wind_grid_detail_rate_limit_per_minute}/min"
        )
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(status_code=400, detail="表示範囲が不正です。")
    if spacing_deg not in WIND_GRID_DETAIL_ALLOWED_SPACINGS_DEG:
        raise HTTPException(status_code=400, detail="spacing_degの値が不正です。")
    points = generate_wind_grid_detail_points((min_lon, min_lat, max_lon, max_lat), spacing_deg)
    if len(points) > WIND_GRID_DETAIL_MAX_POINTS:
        raise HTTPException(status_code=400, detail="表示範囲が広すぎます。ズームインしてください。")
    grid = await weather_service.get_wind_grid(points)
    _reject_if_all_points_failed("wind-grid-detail", points, grid)
    return [point for point in grid if point is not None]
