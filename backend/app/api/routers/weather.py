import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import (
    client_id,
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
from app.infrastructure.debug_log import record_rate_limit_rejection
from app.infrastructure.rate_limiter import check_rate_limit
from app.services.flood_service import FloodForecasts, FloodService
from app.services.warning_service import WarningService, WeatherWarnings
from app.services.wbgt_service import WbgtService, WbgtStatus
from app.services.jma_amedas_service import JmaAmedasService
from app.services.weather_service import WeatherService

logger = logging.getLogger("ridecompass.weather")

router = APIRouter()


def _prefer_amedas_current_values(conditions: WeatherConditions, amedas: AmedasObservation | None) -> WeatherConditions:
    """/api/weatherの「現在値」部分（気温・体感温度・風速風向）をアメダス実測優先にする
    （改善計画T387フォローアップ、ユーザー指示2026-08-29）。

    アメダスは実際の観測値のためOpen-Meteoの「現在値」（モデル推定）より正確だが、
    観測専用APIで予報機能を持たない。体感温度はJMAが直接提供しないため、アメダスの
    気温・湿度・風速から自前計算する（domain/jma_amedas.py: apparent_temperature_from_amedas、
    Open-Meteoとは異なる計算式のため厳密には一致しない近似値）。上書き対象は気温・
    体感温度・風速風向のみに限定し、降水確率・降水量・UV指数・weather_code・「今日の
    見通し」（日次集計・today_periods）はいずれもアメダスに相当データが無いか単位が
    異なる（precipitation_mmはOpen-Meteo側が時間降水量[mm/h]、アメダスは10分降水量のため
    単純な倍率換算は精度を偽装することになる）ためOpen-Meteoのまま維持する。
    風は速度・方位を必ずセットで上書きする（一方だけ差し替えると内部矛盾したペアになるため）。
    観測時刻(observed_at)はOpen-Meteo側のまま維持する（レスポンス全体の「いつの情報か」は
    引き続きOpen-Meteo基準とし、アメダス由来の値だけが数分ずれうる点は許容する）。
    アメダスが取得できない（Redis未温間・最寄り観測所がセンサー未搭載等）場合はOpen-Meteoの
    値をそのまま使う（フォールバック）。
    """
    if amedas is None:
        return conditions
    updates: dict[str, float] = {}
    if amedas.temperature_c is not None:
        updates["temperature_c"] = amedas.temperature_c
    if amedas.apparent_temperature_c is not None:
        updates["apparent_temperature_c"] = amedas.apparent_temperature_c
    if amedas.wind_speed_ms is not None and amedas.wind_direction_deg is not None:
        updates["wind_speed_ms"] = amedas.wind_speed_ms
        updates["wind_direction_deg"] = amedas.wind_direction_deg
        updates["wind_direction_label"] = amedas.wind_direction_label
    if not updates:
        return conditions
    return conditions.model_copy(update=updates)


@router.get("/api/weather", response_model=WeatherConditions)
async def get_weather(
    http_request: Request,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    weather_service: WeatherService = Depends(get_weather_service),
    amedas_service: JmaAmedasService = Depends(get_amedas_service),
) -> WeatherConditions:
    # 以前はここでの範囲チェックをCoordinates（Pydanticモデル）任せにしており、
    # 範囲外の値（例: latitude=999）はFastAPIの422ではなくpydantic.ValidationErrorが
    # 関数内から送出され未処理の500になっていた。Queryのge/leでFastAPI層で弾く。
    if not check_rate_limit(f"weather:{client_id(http_request)}", settings.weather_rate_limit_per_minute):
        record_rate_limit_rejection(
            "weather", client_id(http_request), f"{settings.weather_rate_limit_per_minute}/min"
        )
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    point = Coordinates(latitude=latitude, longitude=longitude)
    conditions = await weather_service.get_conditions(point)
    if conditions is None:
        raise HTTPException(status_code=502, detail="天候情報の取得に失敗しました")
    # 改善計画T387フォローアップ: Open-Meteoの取得が成功した場合のみ、現在値の気温・
    # 風速風向をアメダス実測値で上書きする（Open-Meteo自体が失敗した場合は502のまま、
    # アメダス単独でのレスポンス構築はしない——体感温度・今日の見通し等はアメダスに
    # 相当データが無くWeatherConditionsを完成させられないため）。
    amedas = await amedas_service.get_nearest_observation(point)
    return _prefer_amedas_current_values(conditions, amedas)


@router.get("/api/weather/warnings", response_model=WeatherWarnings)
async def get_weather_warnings(
    http_request: Request,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    warning_service: WarningService = Depends(get_warning_service),
) -> WeatherWarnings:
    """出発地点近傍のJMA警報・注意報を、サイクリングに関連する種別へ絞ってバッジ用に返す
    （改善計画T205）。地点→市区町村→警報エリアの解決、または警報自体の取得に失敗した
    場合は例外にせず「警報なし」を返す（warning_service.py参照。他の/api/weather系と異なり
    このfail-openは意図的な仕様のため、502は返さない——T174（WBGT警告）と共有する
    「安全側ではないが失敗時は警告なしとする」という既定の方針）。"""
    if not check_rate_limit(
        f"weather-warnings:{client_id(http_request)}", settings.weather_warnings_rate_limit_per_minute
    ):
        record_rate_limit_rejection(
            "weather-warnings", client_id(http_request), f"{settings.weather_warnings_rate_limit_per_minute}/min"
        )
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    return await warning_service.get_warnings(Coordinates(latitude=latitude, longitude=longitude))


@router.get("/api/weather/wbgt", response_model=WbgtStatus)
async def get_wbgt(
    http_request: Request,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    wbgt_service: WbgtService = Depends(get_wbgt_service),
) -> WbgtStatus:
    """出発地点近傍の暑さ指数（WBGT）警戒レベルをバッジ用に返す（改善計画T174）。
    提供期間外（11〜3月）・地点解決や取得に失敗した場合・「ほぼ安全」（21未満）の
    いずれも例外にせず空（level=None）を返す（wbgt_service.py参照。T205の警報・
    注意報バッジと同じfail-open方針のため502は返さない）。"""
    if not check_rate_limit(f"weather-wbgt:{client_id(http_request)}", settings.weather_wbgt_rate_limit_per_minute):
        record_rate_limit_rejection(
            "weather-wbgt", client_id(http_request), f"{settings.weather_wbgt_rate_limit_per_minute}/min"
        )
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    return await wbgt_service.get_status(Coordinates(latitude=latitude, longitude=longitude))


@router.get("/api/weather/flood-forecast", response_model=FloodForecasts)
async def get_flood_forecast(
    http_request: Request,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    flood_service: FloodService = Depends(get_flood_service),
) -> FloodForecasts:
    """出発地点近傍のJMA指定河川洪水予報（レベル2〜5）をバッジ用に返す（改善計画T212、
    T176調査で発見したAPIを使う）。地点解決・洪水予報自体の取得のどこで失敗しても
    例外にせず空を返す（T205/T174と共有するfail-open方針、502は返さない）。"""
    if not check_rate_limit(
        f"weather-flood-forecast:{client_id(http_request)}", settings.weather_flood_forecast_rate_limit_per_minute
    ):
        record_rate_limit_rejection(
            "weather-flood-forecast",
            client_id(http_request),
            f"{settings.weather_flood_forecast_rate_limit_per_minute}/min",
        )
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    return await flood_service.get_forecasts(Coordinates(latitude=latitude, longitude=longitude))


@router.get("/api/weather/amedas", response_model=AmedasObservation)
async def get_amedas(
    http_request: Request,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    amedas_service: JmaAmedasService = Depends(get_amedas_service),
) -> AmedasObservation:
    """出発地点近傍の最寄りアメダス観測所の直近観測値を返す（改善計画T387）。
    観測値本体はRedis Hash（TTL 15分）でキャッシュされる（jma_amedas_service.py参照）。
    観測所解決・取得のいずれかに失敗した場合は502を返す（/api/weatherと同じ方針。
    警報・注意報バッジ系と違いこちらは表示の主対象になりうる数値のため、fail-openにしない）。"""
    if not check_rate_limit(f"amedas:{client_id(http_request)}", settings.weather_amedas_rate_limit_per_minute):
        record_rate_limit_rejection(
            "amedas", client_id(http_request), f"{settings.weather_amedas_rate_limit_per_minute}/min"
        )
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    observation = await amedas_service.get_nearest_observation(Coordinates(latitude=latitude, longitude=longitude))
    if observation is None:
        raise HTTPException(status_code=502, detail="アメダス観測値の取得に失敗しました")
    return observation


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


@router.get("/api/weather/wind-grid", response_model=WindGridResponse)
async def get_wind_grid(
    http_request: Request,
    weather_service: WeatherService = Depends(get_weather_service),
) -> WindGridResponse:
    """風・降水延長予報の格子点マップ（改善計画T178フォローアップ、T183で降水を追加）。
    関東本土全域の固定格子点（domain/wind_grid.py: WIND_GRID_BBOX/WIND_GRID_SPACING_DEG）
    ぶんの時間別風向・風速・降水量をまとめて返す。取得に失敗した地点はレスポンスから
    除外する（他の外部API連携と同じ「取得失敗は握りつぶす」方針、1地点の失敗で全体を
    502にしない）。ただし全地点が失敗した場合は502を返す（改善計画T200、
    _reject_if_all_points_failed参照）。時刻配列はpoints内の各点からは外し、応答トップ
    レベルに1本だけ持つ（改善計画T203、WindGridResponseのdocstring参照）。"""
    if not check_rate_limit(f"wind-grid:{client_id(http_request)}", settings.wind_grid_rate_limit_per_minute):
        record_rate_limit_rejection(
            "wind-grid", client_id(http_request), f"{settings.wind_grid_rate_limit_per_minute}/min"
        )
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    points = generate_wind_grid_points()
    times, grid = await weather_service.get_wind_grid(points)
    _reject_if_all_points_failed("wind-grid", points, grid)
    return WindGridResponse(times=times, points=[point for point in grid if point is not None])


@router.get("/api/weather/wind-grid-detail", response_model=WindGridResponse)
async def get_wind_grid_detail(
    http_request: Request,
    min_lon: float = Query(ge=-180, le=180),
    min_lat: float = Query(ge=-90, le=90),
    max_lon: float = Query(ge=-180, le=180),
    max_lat: float = Query(ge=-90, le=90),
    spacing_deg: float = Query(default=WIND_GRID_DETAIL_SPACING_DEG),
    weather_service: WeatherService = Depends(get_weather_service),
) -> WindGridResponse:
    """風・降水延長予報の詳細格子（改善計画T180、ヒートマップ等の面表現用。T185でspacing_deg
    をズーム依存にして間隔可変化）。呼び出し元（フロント）が渡した表示範囲（bbox）に交差する
    密格子点（domain/wind_grid.py: generate_wind_grid_detail_points、固定ラティス上の座標の
    ため近い範囲を見る別ユーザーとキャッシュを共有できる）ぶんの時間別風向・風速・降水量を
    返す。get_wind_gridと同じく取得失敗地点は結果から除外し、時刻配列は応答トップレベルに
    1本だけ持つ（改善計画T203）。

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
    times, grid = await weather_service.get_wind_grid(points)
    _reject_if_all_points_failed("wind-grid-detail", points, grid)
    return WindGridResponse(times=times, points=[point for point in grid if point is not None])
