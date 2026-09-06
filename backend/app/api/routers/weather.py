import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.api.dependencies import (
    enforce_rate_limit,
    get_amedas_service,
    get_flood_service,
    get_warning_service,
    get_wbgt_service,
    get_weather_service,
)
from app.config import settings
from app.domain.jma_amedas import AmedasObservation
from app.domain.route import Coordinates
from app.domain.weather import WeatherConditions
from app.domain.wind_grid import (
    WIND_GRID_DETAIL_ALLOWED_SPACINGS_DEG,
    WIND_GRID_DETAIL_MAX_POINTS,
    WIND_GRID_DETAIL_SPACING_DEG,
    WindGridResponse,
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


@router.get("/api/weather", response_model=WeatherConditions)
async def get_weather(
    http_request: Request,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    weather_service: WeatherService = Depends(get_weather_service),
) -> WeatherConditions:
    """今日の見通し（TodayOutlook、日次集計・weather_code・UV指数等の予報値）向け。
    常設ヘッダー（現在値の気温・体感温度・風速風向）はアメダス実測を使う
    `GET /api/weather/amedas`が担うため、このエンドポイントはOpen-Meteoの値を
    そのまま返す。"""
    # Queryのge/leで範囲外の値をFastAPI層で弾く（Coordinatesへの委譲だと
    # pydantic.ValidationErrorが関数内から送出され、422ではなく未処理の500になる）。
    enforce_rate_limit(http_request, "weather", settings.weather_rate_limit_per_minute)
    conditions = await weather_service.get_conditions(Coordinates(latitude=latitude, longitude=longitude))
    if conditions is None:
        raise HTTPException(status_code=502, detail="天候情報の取得に失敗しました")
    return conditions


@router.get("/api/weather/warnings", response_model=WeatherWarnings)
async def get_weather_warnings(
    http_request: Request,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    warning_service: WarningService = Depends(get_warning_service),
) -> WeatherWarnings:
    """出発地点近傍のJMA警報・注意報を、サイクリングに関連する種別へ絞ってバッジ用に返す。
    地点→市区町村→警報エリアの解決、または警報自体の取得に失敗した
    場合は例外にせず「警報なし」を返す（warning_service.py参照。他の/api/weather系と異なり
    このfail-openは意図的な仕様のため、502は返さない——WBGT警告と共有する
    「安全側ではないが失敗時は警告なしとする」という既定の方針）。"""
    enforce_rate_limit(http_request, "weather-warnings", settings.weather_warnings_rate_limit_per_minute)
    return await warning_service.get_warnings(Coordinates(latitude=latitude, longitude=longitude))


@router.get("/api/weather/wbgt", response_model=WbgtStatus)
async def get_wbgt(
    http_request: Request,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    wbgt_service: WbgtService = Depends(get_wbgt_service),
) -> WbgtStatus:
    """出発地点近傍の暑さ指数（WBGT）警戒レベルをバッジ用に返す。
    提供期間外（11〜3月）・地点解決や取得に失敗した場合・「ほぼ安全」（21未満）の
    いずれも例外にせず空（level=None）を返す（wbgt_service.py参照。警報・
    注意報バッジと同じfail-open方針のため502は返さない）。"""
    enforce_rate_limit(http_request, "weather-wbgt", settings.weather_wbgt_rate_limit_per_minute)
    return await wbgt_service.get_status(Coordinates(latitude=latitude, longitude=longitude))


@router.get("/api/weather/flood-forecast", response_model=FloodForecasts)
async def get_flood_forecast(
    http_request: Request,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    flood_service: FloodService = Depends(get_flood_service),
) -> FloodForecasts:
    """出発地点近傍のJMA指定河川洪水予報（レベル2〜5）をバッジ用に返す。
    地点解決・洪水予報自体の取得のどこで失敗しても
    例外にせず空を返す（警報・WBGTと共有するfail-open方針、502は返さない）。"""
    enforce_rate_limit(
        http_request, "weather-flood-forecast", settings.weather_flood_forecast_rate_limit_per_minute
    )
    return await flood_service.get_forecasts(Coordinates(latitude=latitude, longitude=longitude))


@router.get("/api/weather/amedas", response_model=AmedasObservation)
async def get_amedas(
    http_request: Request,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    amedas_service: JmaAmedasService = Depends(get_amedas_service),
) -> AmedasObservation:
    """出発地点近傍の最寄りアメダス観測所の直近観測値を返す。
    観測値本体はRedis Hash（TTL 15分）でキャッシュされる（jma_amedas_service.py参照）。
    観測所解決・取得のいずれかに失敗した場合は502を返す（/api/weatherと同じ方針。
    警報・注意報バッジ系と違いこちらは表示の主対象になりうる数値のため、fail-openにしない）。"""
    enforce_rate_limit(http_request, "amedas", settings.weather_amedas_rate_limit_per_minute)
    observation = await amedas_service.get_nearest_observation(Coordinates(latitude=latitude, longitude=longitude))
    if observation is None:
        raise HTTPException(status_code=502, detail="アメダス観測値の取得に失敗しました")
    return observation


def _reject_if_all_points_failed(label: str, points: list, grid: list) -> None:
    """全地点が取得失敗（Open-Meteo全滅、429常態化等）の場合のみ502で明示的に失敗を返す。
    `/api/weather`（単一地点）は取得失敗を502で返す設計のため、この非対称を解消する。
    1地点でも成功していれば部分結果を200で返す（1地点の失敗で全体を落とさない方針は
    維持）。`WeatherService.get_wind_grid`は常に`points`と同じ長さの結果（失敗地点は
    None）を返す契約のため、`grid`が空のまま（=呼び出し自体が行われていない等）の
    ケースは対象外にする（`grid and`のチェック）。"""
    if points and grid and all(point is None for point in grid):
        logger.warning("%s: 全%d地点が取得失敗しました（Open-Meteo障害の可能性）", label, len(points))
        raise HTTPException(status_code=502, detail="気象データの取得に失敗しました")


# 風グリッドは応答トップレベルに約48時間ぶんの時刻配列を持ち、どの時刻を描画するかは
# クライアント側が選ぶ。上流（Open-Meteo）の更新は1時間ごとのため、数分の再利用で表示が
# 古くなることはない。JMAタイル（`jma_tile.py`）と違いURLに時刻を含まず同じURLのまま内容が
# 更新されるため`immutable`にはできない。詳細格子はパン・ズームのたびに呼ばれうるので、
# 同じ範囲へ戻ったときの再取得を抑える効果が大きい。
_WIND_GRID_CACHE_CONTROL = "public, max-age=300"


@router.get("/api/weather/wind-grid", response_model=WindGridResponse)
async def get_wind_grid(
    http_request: Request,
    response: Response,
    weather_service: WeatherService = Depends(get_weather_service),
) -> WindGridResponse:
    """風・降水延長予報の格子点マップ。
    関東本土全域の固定格子点（domain/wind_grid.py: WIND_GRID_BBOX/WIND_GRID_SPACING_DEG）
    ぶんの時間別風向・風速・降水量をまとめて返す。取得に失敗した地点はレスポンスから
    除外する（他の外部API連携と同じ「取得失敗は握りつぶす」方針、1地点の失敗で全体を
    502にしない）。ただし全地点が失敗した場合は502を返す（_reject_if_all_points_failed
    参照）。時刻配列はpoints内の各点からは外し、応答トップレベルに1本だけ持つ
    （WindGridResponseのdocstring参照）。"""
    enforce_rate_limit(http_request, "wind-grid", settings.wind_grid_rate_limit_per_minute)
    points = generate_wind_grid_points()
    times, grid = await weather_service.get_wind_grid(points)
    _reject_if_all_points_failed("wind-grid", points, grid)
    response.headers["Cache-Control"] = _WIND_GRID_CACHE_CONTROL
    return WindGridResponse(times=times, points=[point for point in grid if point is not None])


@router.get("/api/weather/wind-grid-detail", response_model=WindGridResponse)
async def get_wind_grid_detail(
    http_request: Request,
    response: Response,
    min_lon: float = Query(ge=-180, le=180),
    min_lat: float = Query(ge=-90, le=90),
    max_lon: float = Query(ge=-180, le=180),
    max_lat: float = Query(ge=-90, le=90),
    spacing_deg: float = Query(default=WIND_GRID_DETAIL_SPACING_DEG),
    weather_service: WeatherService = Depends(get_weather_service),
) -> WindGridResponse:
    """風・降水延長予報の詳細格子（ヒートマップ等の面表現用、spacing_degでズーム依存の間隔を
    可変化）。呼び出し元（フロント）が渡した表示範囲（bbox）に交差する
    密格子点（domain/wind_grid.py: generate_wind_grid_detail_points、固定ラティス上の座標の
    ため近い範囲を見る別ユーザーとキャッシュを共有できる）ぶんの時間別風向・風速・降水量を
    返す。get_wind_gridと同じく取得失敗地点は結果から除外し、時刻配列は応答トップレベルに
    1本だけ持つ。

    spacing_degはWIND_GRID_DETAIL_ALLOWED_SPACINGS_DEGの離散値のみ許可する（任意の連続値を
    許すとユーザーごとにラティスの絶対座標がずれてキャッシュ共有が効かなくなるため、
    フロント側windLayer.ts: windGridDetailSpacingDegForZoomと同じ段階に固定する）。
    全地点が失敗した場合は502を返す（_reject_if_all_points_failed参照）。"""
    enforce_rate_limit(http_request, "wind-grid-detail", settings.wind_grid_detail_rate_limit_per_minute)
    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(status_code=400, detail="表示範囲が不正です。")
    if spacing_deg not in WIND_GRID_DETAIL_ALLOWED_SPACINGS_DEG:
        raise HTTPException(status_code=400, detail="spacing_degの値が不正です。")
    points = generate_wind_grid_detail_points((min_lon, min_lat, max_lon, max_lat), spacing_deg)
    if len(points) > WIND_GRID_DETAIL_MAX_POINTS:
        raise HTTPException(status_code=400, detail="表示範囲が広すぎます。ズームインしてください。")
    times, grid = await weather_service.get_wind_grid(points)
    _reject_if_all_points_failed("wind-grid-detail", points, grid)
    response.headers["Cache-Control"] = _WIND_GRID_CACHE_CONTROL
    return WindGridResponse(times=times, points=[point for point in grid if point is not None])
