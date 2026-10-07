import asyncio
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.dependencies import (
    get_axis_inspector_service,
    get_dedicated_way_value_service,
    get_region_service,
)
from app.api.rate_limit import enforce_rate_limit
from app.api.routers._tile_http import tile_response, validate_tile_coords
from app.api.routers.routes import RoutePreferenceWeights
from app.config import settings
from app.domain.dynamic_way_values import MissingConditions, WayValueQuery
from app.domain.axis_inspector import AxisInspectorResult
from app.domain.route_preference import RoutePreference
from app.domain.landcover import LANDCOVER_TILE_MAX_ZOOM, LANDCOVER_TILE_MIN_ZOOM
from app.infrastructure.media_types import PNG_CONTENT_TYPE
from app.infrastructure.point_tile_layers import POINT_TILE_LAYERS
from app.services.landcover_tile_service import get_landcover_tile
from app.services.dedicated_way_values import AxisWayValueLens
from app.services.region_service import AxisInspectorService, RegionService
from app.domain.strict_model import StrictModel

router = APIRouter()

# 地域タイル（路面・点）の同時実行上限
# （settings.road_tile_max_concurrent、値の根拠はconfig.py参照）。
#
# 上限超過分は即座に429を返すルート生成とは異なり、こちらは「待たせて全件処理する」
# （semaphoreの取得をブロックさせる）方式にしている。MapLibreは失敗したタイル要求を
# 自動再試行しないため、429にすると1画面に収まる範囲で上限を超えるタイル（皇居周辺のような
# 広い範囲では珍しくない）が永久に空白のまま描画されなくなる（詳細は
# docs/modules/backend/static-road-attributes.md参照）。/healthはこのsemaphoreを
# 経由しない別の同期ハンドラのため、待機中のタイル要求に巻き込まれず応答し続けられる。
#
# 点のタイルも同じDB接続プールを取り合うため、専用semaphoreを新設せずこれを
# 共有する（プール上限15接続に対し、独立semaphoreを追加すると種類ごとのタイルの同時実行数の
# 合計がプール上限を超えうる）。
_region_tile_semaphore = asyncio.Semaphore(settings.road_tile_max_concurrent)

# 土地被覆タイルの同時実行上限。DBではなくGeoTIFFの読み取り・再投影（GDAL、スレッドプール）を
# 使うため、上のDB向けsemaphoreとは別に持つ。上限を設けないと、1画面ぶんのタイル要求が
# `asyncio.to_thread`の既定スレッドプールを占有し、同じプールを使う他のディスクI/O
# （タイルキャッシュの読み書き）まで待たされる。
_landcover_tile_semaphore = asyncio.Semaphore(settings.landcover_tile_max_concurrent)


def _check_tile_rate_limit(request: Request, prefix: str) -> None:
    """地域タイル向けの`enforce_rate_limit`の薄いラッパー。どれも「パン/ズームのたびに
    1画面ぶんが飛ぶ」同じ負荷の形のため同じ上限値（settings.road_tile_rate_limit_per_minute）
    を使うが、キー・記録先の`prefix`は種別ごとに分ける。
    """
    enforce_rate_limit(request, prefix, settings.road_tile_rate_limit_per_minute)


@router.get("/api/region/road-surface-tiles/{z}/{x}/{y}.pbf")
async def region_road_surface_tile(
    z: int,
    x: int,
    y: int,
    request: Request,
    region_service: RegionService = Depends(get_region_service),
) -> Response:
    _check_tile_rate_limit(request, "road-tile")
    validate_tile_coords(z, x, y)
    # 同時実行数の上限（_region_tile_semaphoreのコメント参照）は、超過分を待たせて
    # 全件処理する（即座に429で拒否しない）。キャッシュヒットは軽量（実測数ms）なので
    # すぐ解放され、実質的に重い（PostGIS問い合わせを伴う）リクエストだけが待ち行列の
    # 原因になる。
    async with _region_tile_semaphore:
        tile = await region_service.get_road_surface_tile(z, x, y)
    return tile_response(tile)


@router.get("/api/region/point-tiles/{layer}/{z}/{x}/{y}.pbf")
async def region_point_tile(
    layer: str,
    z: int,
    x: int,
    y: int,
    request: Request,
    region_service: RegionService = Depends(get_region_service),
) -> Response:
    """点のレイヤー（`infrastructure/point_tile_layers.py`の名前。例: 停止要因・補給休憩のPOI、事故）。
    宣言に無いレイヤーは404。路面タイルと同じ歯止め・同時実行制御を使い、レート制限のキーはレイヤーごとに分ける。
    """
    point_layer = POINT_TILE_LAYERS.get(layer)
    if point_layer is None:
        raise HTTPException(status_code=404, detail="未知の点のレイヤーです。")
    _check_tile_rate_limit(request, f"{layer}-tile")
    validate_tile_coords(z, x, y)
    async with _region_tile_semaphore:
        tile = await region_service.get_point_tile(point_layer, z, x, y)
    return tile_response(tile)


@router.get("/api/region/landcover-tiles/{z}/{x}/{y}.png")
async def region_landcover_tile(z: int, x: int, y: int, request: Request) -> Response:
    """土地被覆ラスタ（Esri×Impact Observatory 10m LULC）をそのまま面で塗ったラスタタイル。

    DBを読まないため`_region_tile_semaphore`（DB接続プールの取り合いを抑えるもの）には
    乗せず、CPU/ディスクI/Oの上限は`landcover_tile_max_concurrent`の専用semaphoreで持つ。
    """
    _check_tile_rate_limit(request, "landcover-tile")
    validate_tile_coords(z, x, y, LANDCOVER_TILE_MIN_ZOOM, LANDCOVER_TILE_MAX_ZOOM)
    async with _landcover_tile_semaphore:
        tile = await get_landcover_tile(z, x, y)
    if tile is None:
        raise HTTPException(status_code=503, detail="土地被覆データが利用できません")
    return tile_response(tile, PNG_CONTENT_TYPE)


@router.get("/api/region/dynamic-way-values/{axis_id}/{z}/{x}/{y}")
async def region_dedicated_way_values(
    axis_id: str,
    z: int,
    x: int,
    y: int,
    request: Request,
    bearing_deg: float | None = None,
    at: datetime | None = None,
    speed_kmh: float | None = None,
    lens: AxisWayValueLens | None = Depends(get_dedicated_way_value_service),
) -> dict[str, float | None]:
    """「評価軸」グループとしての動的材料（風・勾配・雨等）。指定タイル内のフィーチャーごとの
    値（風=wind_drag_ratio[backend/app/domain/wind.py]、勾配=effective_gradient
    [backend/app/domain/gradient.py]、雨=最寄りの雨量計の観測[backend/app/domain/rain.py]）を
    まとめて返す軽量なJSONエンドポイント。値がnullの道は、その走行方位では値が決まらない道（勾配の
    直角付近）で、値の無い道（鍵ごと無い）とは別に塗る。この
    エンドポイントはルート未確定時（視界内の全道路への一律適用）専用——ルート確定後は
    ルート自身の実進行方向・実到達時刻/実値から計算済みの`axis_difficulties`
    （`RouteSegmentDetail`）を使うため、フロントはこのエンドポイントを呼ばない。

    パスパラメータは**軸id**（`axis_definitions.axis_id`）で、配信サービスが返す生値の材料id
    （`wind_drag_ratio`等）とは別の名前空間である。サービスはその軸が参照する材料から引き、
    地図が塗る値（難易度か符号付き材料か）へ軸定義から変える（`services/dedicated_way_values.py: AxisWayValueLens`）。専用配信を持たない・未知のaxis_idと、配信を実装した材料を
    参照していない軸は404。クエリパラメータ（`bearing_deg`・`at`・`speed_kmh`）のうち何が要るかは
    材料のサービスが受け取る条件の型が決め（`domain/dynamic_way_values.py: assemble_conditions`）、
    要るものを省略すると422。要らないものは渡しても無視される（例: 勾配は時刻と速度に依らない。
    風は時刻を省略すると現在時刻[Asia/Tokyo]を使う）。

    静的な路面タイル（`/api/region/road-surface-tiles`、MVT、本エンドポイントとは無関係）
    とは別経路——受け取る側は同じz/x/yについて両方を取り、way_idで突き合わせて重ねる。
    勾配はタイル単位の値を地図表示専用のディスクキャッシュ（`dynamic_way_value_cache.py`）に
    持つため、パン・ズームで同じタイルが再び視界に入っても、同じ向きバケットの範囲内では
    DBへの再問い合わせは発生しない（風は計算が軽いためキャッシュしない）。

    路面・点のタイルと同じレート制限・座標検証・DB接続プールのsemaphoreを共有する
    （本ファイルの`_region_tile_semaphore`のコメント参照——MVTエンコードは
    伴わないが同じPostGISコネクションプールを取り合うため）。
    """
    if lens is None:
        raise HTTPException(status_code=404, detail="未知のaxis_idです。")
    _check_tile_rate_limit(request, f"{axis_id}-way-values")
    validate_tile_coords(z, x, y)
    async with _region_tile_semaphore:
        values = await lens.values(z, x, y, WayValueQuery(at=at, bearing_deg=bearing_deg, speed_kmh=speed_kmh))
    if isinstance(values, MissingConditions):
        raise HTTPException(status_code=422, detail=f"この軸には{'・'.join(values.names)}が必須です。")
    return values


class AxisInspectorRequest(StrictModel):
    osm_way_id: int
    # クリックされたフィーチャーの識別子（路面タイルが焼く`feature_key`）。区間単位の
    # ズームでは区間のid、way単位のズームではosm_way_idの文字列になる。**どちらでも
    # そのまま送ってよい**——後者は`road_edges`に一致せず、way単位の読み出しへ落ちる。
    # 省略すると区間が特定できず、地図が区間単位で塗っていても内訳はway単位になる。
    feature_key: str | None = None
    # 進行方向に依存する材料（勾配・風）を出すのに要るもの。**1本の道は往復2方向で値が
    # 違う**ため、方向が決まらないと算出できない。地図が指定している値をそのまま送る
    # （`/dynamic-way-values`へ送っているものと同じ）。時刻・速度を省くと、それを要る材料の軸は「データなし」。
    # `z`/`x`/`y`はクリックしたタイル——地図は既に知っており、way idから逆算するより
    # 確かで、同じタイルの値がキャッシュに載っていれば追加のDBアクセスも要らない。
    z: int
    x: int
    y: int
    bearing_deg: float
    at: datetime | None = None
    speed_kmh: float | None = None
    # 合成に使う重み。利用者がいま設定している重み（ルート生成へ送るのと同じ形・同じ検証）を送る。省略すると既定の重み。
    route_preference: RoutePreferenceWeights | None = None


@router.post("/api/region/axis-inspector")
async def region_axis_inspector(
    body: AxisInspectorRequest,
    http_request: Request,
    axis_inspector: AxisInspectorService = Depends(get_axis_inspector_service),
) -> AxisInspectorResult | None:
    """区間インスペクタ。クリックされた道路（osm_way_id）について、
    一次属性（highway/tags）→二次軸スコア（取得可能な軸のみ）→
    合成コスト（取得可能な軸だけの参考値。重みは送られた`route_preference`、省略時は既定）を返す。
    POST+JSONボディ・osm_way_id完全一致で引く理由はRegionService.get_axis_inspectorの
    docstring参照（交差点付近での取り違え対策）。進行方向に依存する軸（勾配・風）は、
    地図が指定している走行方位・時刻・想定速度から算出する。時刻・速度を送らなければ、
    それを要る軸はavailable=falseで返る。
    """
    # 座標なしの単発リクエストのためタイル向け_check_tile_rate_limit
    # （road_tile_rate_limit_per_minuteと結合）を流用せず、専用の設定値を直接使う
    # （config.py: axis_inspector_rate_limit_per_minuteのコメント参照）。
    enforce_rate_limit(http_request, "axis-inspector", settings.axis_inspector_rate_limit_per_minute)
    preference = None if body.route_preference is None else RoutePreference(weights=dict(body.route_preference.root))
    return await axis_inspector.inspect(
        body.osm_way_id, body.feature_key, body.z, body.x, body.y,
        body.at, body.bearing_deg, body.speed_kmh, preference)
