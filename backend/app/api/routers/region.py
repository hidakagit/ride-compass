import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, model_validator

from app.api.dependencies import client_id, get_region_service
from app.api.routers.routes import (
    MotorVehicleDensityRecipeOverride,
    RoadSuitabilityRecipeOverride,
    SafetyRecipeOverride,
    TrafficStressRecipeOverride,
    validate_lanes_threshold_order,
)
from app.config import settings
from app.domain.recipe import MotorVehicleDensityRecipe, RoadSuitabilityRecipe
from app.domain.region import ROAD_TILE_MAX_ZOOM, ROAD_TILE_MIN_ZOOM
from app.domain.safety import SafetyBreakdown, SafetyRecipe
from app.domain.traffic import TrafficStressBreakdown, TrafficStressRecipe
from app.infrastructure.debug_log import record_rate_limit_rejection
from app.infrastructure.rate_limiter import check_rate_limit
from app.services.region_service import RegionService

router = APIRouter()

# 地域タイル（路面・停止要因POI）の同時実行上限
# （settings.road_tile_max_concurrent、値の根拠はconfig.py参照）。
#
# かつて密集した都市部のタイルはPostGISから1万件超のway行を転送してPython側でMVT
# エンコードしており（実測: 東京駅付近z13タイルで約7.6秒）、地図の短時間パン/ズームで
# ブラウザが並列に大量のタイルを要求すると、この重い処理が同時に積み上がりCPUを奪い合い、
# Renderのヘルスチェックすら応答できず「Instance failed」でプロセスごと再起動される事故が
# 実機で発生した。現在はMVT生成をPostGIS側（ST_AsMVT、road_graph_repository.py）へ移して
# 1タイルのコストを大幅に下げたが、キャッシュミスのバーストが遠隔DB/Session poolerへ
# 無制限に並ぶのを防ぐ歯止めとして同時実行数制限は維持する。
#
# 上限超過分は即座に429を返すルート生成とは異なり、こちらは「待たせて全件処理する」
# （semaphoreの取得をブロックさせる）方式にしている。MapLibreは失敗したタイル要求を
# 自動再試行しないため、429にすると1画面に収まる範囲で上限を超えるタイル（皇居周辺のような
# 広い範囲では珍しくない）が永久に空白のまま描画されない不具合が実機で発生した。
# 待たせる方式でもRender再起動事故の再発防止という目的は変わらない（同時に重い処理が
# 走る数は上限のまま増えないため）。/healthはこのsemaphoreを経由しない別の同期ハンドラの
# ため、待機中のタイル要求に巻き込まれず応答し続けられる。
#
# 停止要因POIタイル（改善計画T54、T97で交差点密度レイヤーの配信は撤去）も同じDB接続
# プールを取り合うため、専用semaphoreを新設せずこれを共有する（プール上限15接続に対し、
# 独立semaphoreを追加すると2種のタイルの同時実行数の合計がプール上限を超えうる）。
_region_tile_semaphore = asyncio.Semaphore(settings.road_tile_max_concurrent)


def _check_tile_rate_limit(request: Request, prefix: str) -> None:
    """認証なしで叩ける地域タイルへの簡易な歯止め（1クライアントIPあたり1分間の上限）。
    地域タイルはPostGISへの実問い合わせ・ディスクキャッシュ書き込みを伴うため、
    無制限に叩かれるとDB負荷やディスク消費に繋がる（詳細はrate_limiter.py）。
    路面・POIタイルで同じ上限値（settings.road_tile_rate_limit_per_minute）を
    使うが、キー・記録先の`prefix`は種別ごとに分ける。
    """
    if not check_rate_limit(f"{prefix}:{client_id(request)}", settings.road_tile_rate_limit_per_minute):
        record_rate_limit_rejection(prefix, client_id(request), f"{settings.road_tile_rate_limit_per_minute}/min")
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")


def _validate_tile_coords(z: int, x: int, y: int) -> None:
    """路面・POIタイルで共通のズーム/座標範囲チェック
    （T54: POIタイルは既存の路面レイヤーと同じズーム範囲に準拠する）。
    """
    # MapLibre側もvector sourceのminzoom/maxzoomでこの範囲外は要求しないが、
    # 直接APIを叩かれた場合の安全弁として範囲外は拒否する。
    if z < ROAD_TILE_MIN_ZOOM or z > ROAD_TILE_MAX_ZOOM:
        raise HTTPException(status_code=400, detail="対応していないズームレベルです。")
    # x/yがそのズームレベルで存在しうる範囲（0 <= x,y < 2**z）を外れると、
    # domain/region.pyのtile_bounds_lonlatがmath.sinhでOverflowErrorを送出しうるため、
    # ここで先に弾く（例: 直接APIを叩かれてy=10**18のような極端な値が渡された場合）。
    tile_index_max = 2**z
    if not (0 <= x < tile_index_max) or not (0 <= y < tile_index_max):
        raise HTTPException(status_code=400, detail="タイル座標が範囲外です。")


@router.get("/api/region/road-surface-tiles/{z}/{x}/{y}.pbf")
async def region_road_surface_tile(
    z: int,
    x: int,
    y: int,
    request: Request,
    region_service: RegionService = Depends(get_region_service),
) -> Response:
    _check_tile_rate_limit(request, "road-tile")
    _validate_tile_coords(z, x, y)
    # 同時実行数の上限（_region_tile_semaphoreのコメント参照）は、超過分を待たせて
    # 全件処理する（即座に429で拒否しない）。キャッシュヒットは軽量（実測数ms）なので
    # すぐ解放され、実質的に重い（PostGIS問い合わせを伴う）リクエストだけが待ち行列の
    # 原因になる。
    async with _region_tile_semaphore:
        tile_bytes = await region_service.get_road_surface_tile(z, x, y)
    # ブラウザ側HTTPキャッシュを1時間許可する。路面データはPBF取込時にしか変わらないため、
    # ページ再読み込み・再訪時の同一タイル再取得（＝バーストの主成分）を丸ごと省ける。
    # サーバーからブラウザキャッシュは無効化できないため、取込・範囲拡大の反映遅れを
    # 最大1時間に抑える値にする（サーバー側ディスクキャッシュの一括削除とは独立）。
    return Response(
        content=tile_bytes,
        media_type="application/vnd.mapbox-vector-tile",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/api/region/poi-tiles/{z}/{x}/{y}.pbf")
async def region_poi_tile(
    z: int,
    x: int,
    y: int,
    request: Request,
    region_service: RegionService = Depends(get_region_service),
) -> Response:
    """停止要因POI（信号・横断歩道・一時停止・踏切）レイヤー（改善計画T54）。
    静的道路属性P1で評価にのみ使われていたosm_raw_poisの可視化。交差点密度
    （road_nodes次数）レイヤーもT54で同じタイルへ焼き込んでいたが、T96で地図上の
    独立可視化レイヤーとしては撤去され参照が無くなったため、T97でこの配信からも削除した
    （ルーティング材料のintersection_weightとしては`get_intersection_counts`等を引き続き使う）。
    路面タイルと同じ歯止め・同時実行制御をそのまま流用する。
    """
    _check_tile_rate_limit(request, "poi-tile")
    _validate_tile_coords(z, x, y)
    async with _region_tile_semaphore:
        tile_bytes = await region_service.get_poi_tile(z, x, y)
    return Response(
        content=tile_bytes,
        media_type="application/vnd.mapbox-vector-tile",
        headers={"Cache-Control": "public, max-age=3600"},
    )


async def _breakdown_response(
    http_request: Request,
    rate_limit_prefix: str,
    osm_way_id: int,
    recipe: Any,
    road_suitability_recipe: Any,
    motor_vehicle_density_recipe: Any,
    service_call: Callable[[int, Any, Any, Any], Awaitable[Any]],
) -> Any:
    """交通ストレス・安全度の内訳エンドポイントが共有するリクエスト処理（改善計画T123）。
    歯止め（レート制限）→サービス呼び出しという共通の骨格だけを引数化する（レシピの
    APIモデル→domainモデル変換はエンドポイントごとに型が異なるため呼び出し元に残す）。
    """
    _check_tile_rate_limit(http_request, rate_limit_prefix)
    return await service_call(osm_way_id, recipe, road_suitability_recipe, motor_vehicle_density_recipe)


class TrafficStressBreakdownRequest(BaseModel):
    osm_way_id: int
    # 研究モードでレシピを上書き中の内訳表示用（改善計画: 交通ストレスレシピ外出し基盤）。
    # 省略時はdomain/traffic.py: DEFAULT_TRAFFIC_STRESS_RECIPEで計算する。
    traffic_stress_recipe: TrafficStressRecipeOverride | None = None
    # 交通ストレス・安全度が共有する「車との近さ」(N2)の材料の上書き（改善計画: 車との
    # 近さ材料の共有元化）。省略時はそれぞれdomain/recipe.py:
    # DEFAULT_ROAD_SUITABILITY_RECIPE/DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPEで計算する。
    road_suitability_recipe: RoadSuitabilityRecipeOverride | None = None
    motor_vehicle_density_recipe: MotorVehicleDensityRecipeOverride | None = None

    @model_validator(mode="after")
    def _check_lanes_threshold_order(self) -> "TrafficStressBreakdownRequest":
        validate_lanes_threshold_order(self.traffic_stress_recipe, self.motor_vehicle_density_recipe)
        return self


@router.post("/api/region/traffic-stress-breakdown")
async def region_traffic_stress_breakdown(
    body: TrafficStressBreakdownRequest,
    http_request: Request,
    region_service: RegionService = Depends(get_region_service),
) -> TrafficStressBreakdown | None:
    """交通ストレスの判定内訳（改善計画T90）。クリックされた道路（osm_way_id、
    路面タイルのMVTプロパティに含まれる識別子）について、`domain/traffic.py:
    traffic_stress_level`が計算に使ったベース値・各補正・最終値を返す。該当wayが存在しない、
    highwayが判定基準に未登録、またはDBなし構成の場合はlevel=null（タイル・区間評価と同じ
    「不明・他」の扱い）。緯度経度の空間マッチではなく完全一致で引く理由は
    RegionService.get_traffic_stress_breakdownのdocstring参照（交差点付近での取り違え対策）。
    タイル取得と同じ歯止め（クリックの連打対策）を流用する。

    GETではなくPOST+JSONボディなのは、`traffic_stress_recipe`（レシピ上書き、改善計画:
    交通ストレスレシピ外出し基盤）という複雑なオブジェクトをクエリパラメータで渡すのが
    不自然なため。`/api/routes/generate`と同じ「読み取り専用だがボディ渡し」の形に揃えた。
    """
    recipe = TrafficStressRecipe(**body.traffic_stress_recipe.model_dump()) if body.traffic_stress_recipe else None
    road_suitability_recipe = (
        RoadSuitabilityRecipe(**body.road_suitability_recipe.model_dump()) if body.road_suitability_recipe else None
    )
    motor_vehicle_density_recipe = (
        MotorVehicleDensityRecipe(**body.motor_vehicle_density_recipe.model_dump())
        if body.motor_vehicle_density_recipe
        else None
    )
    return await _breakdown_response(
        http_request,
        "traffic-stress-breakdown",
        body.osm_way_id,
        recipe,
        road_suitability_recipe,
        motor_vehicle_density_recipe,
        region_service.get_traffic_stress_breakdown,
    )


class SafetyBreakdownRequest(BaseModel):
    osm_way_id: int
    # 研究モードでレシピを上書き中の内訳表示用（改善計画: 安全度レシピ）。
    # 省略時はdomain/safety.py: DEFAULT_SAFETY_RECIPEで計算する。
    safety_recipe: SafetyRecipeOverride | None = None
    # TrafficStressBreakdownRequestと同じ「車との近さ」(N2)材料の上書き
    # （改善計画: 車との近さ材料の共有元化）。
    road_suitability_recipe: RoadSuitabilityRecipeOverride | None = None
    motor_vehicle_density_recipe: MotorVehicleDensityRecipeOverride | None = None


@router.post("/api/region/safety-breakdown")
async def region_safety_breakdown(
    body: SafetyBreakdownRequest,
    http_request: Request,
    region_service: RegionService = Depends(get_region_service),
) -> SafetyBreakdown | None:
    """安全度の判定内訳（改善計画: 安全度レシピ）。region_traffic_stress_breakdownと
    完全に同じ構造（POST+JSONボディの理由・osm_way_id完全一致の理由は同エンドポイントの
    docstring参照）。
    """
    recipe = SafetyRecipe(**body.safety_recipe.model_dump()) if body.safety_recipe else None
    road_suitability_recipe = (
        RoadSuitabilityRecipe(**body.road_suitability_recipe.model_dump()) if body.road_suitability_recipe else None
    )
    motor_vehicle_density_recipe = (
        MotorVehicleDensityRecipe(**body.motor_vehicle_density_recipe.model_dump())
        if body.motor_vehicle_density_recipe
        else None
    )
    return await _breakdown_response(
        http_request,
        "safety-breakdown",
        body.osm_way_id,
        recipe,
        road_suitability_recipe,
        motor_vehicle_density_recipe,
        region_service.get_safety_breakdown,
    )
