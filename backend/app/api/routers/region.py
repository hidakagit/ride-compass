import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.api.dependencies import enforce_rate_limit, get_dedicated_way_value_service, get_region_service
from app.api.routers._tile_http import tile_response, validate_tile_coords
from app.config import settings
from app.domain.axis_definitions import AXIS_DEFINITIONS
from app.domain.dynamic_way_values import dedicated_way_value_axes, transform_dedicated_way_values
from app.domain.axis_inspector import AxisInspectorResult
from app.services.region_service import RegionService

router = APIRouter()

# 地域タイル（路面・停止要因POI）の同時実行上限
# （settings.road_tile_max_concurrent、値の根拠はconfig.py参照）。
#
# 上限超過分は即座に429を返すルート生成とは異なり、こちらは「待たせて全件処理する」
# （semaphoreの取得をブロックさせる）方式にしている。MapLibreは失敗したタイル要求を
# 自動再試行しないため、429にすると1画面に収まる範囲で上限を超えるタイル（皇居周辺のような
# 広い範囲では珍しくない）が永久に空白のまま描画されなくなる（詳細は
# docs/modules/backend/static-road-attributes.md参照）。/healthはこのsemaphoreを
# 経由しない別の同期ハンドラのため、待機中のタイル要求に巻き込まれず応答し続けられる。
#
# 停止要因POIタイルも同じDB接続プールを取り合うため、専用semaphoreを新設せずこれを
# 共有する（プール上限15接続に対し、独立semaphoreを追加すると2種のタイルの同時実行数の
# 合計がプール上限を超えうる）。
_region_tile_semaphore = asyncio.Semaphore(settings.road_tile_max_concurrent)


def _check_tile_rate_limit(request: Request, prefix: str) -> None:
    """路面・POIタイル向けの`enforce_rate_limit`薄いラッパー。両タイルとも同じ
    上限値（settings.road_tile_rate_limit_per_minute）を使うが、キー・記録先の
    `prefix`は種別ごとに分ける。
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


@router.get("/api/region/poi-tiles/{z}/{x}/{y}.pbf")
async def region_poi_tile(
    z: int,
    x: int,
    y: int,
    request: Request,
    region_service: RegionService = Depends(get_region_service),
) -> Response:
    """停止要因POI（信号・横断歩道・一時停止・踏切）レイヤー。静的道路属性P1で評価にのみ
    使われていたosm_raw_poisの可視化（材料`intersection_count_per_km`の集計には
    `get_intersection_counts`等を引き続き使う）。路面タイルと同じ歯止め・同時実行制御を
    そのまま流用する。
    """
    _check_tile_rate_limit(request, "poi-tile")
    validate_tile_coords(z, x, y)
    async with _region_tile_semaphore:
        tile = await region_service.get_poi_tile(z, x, y)
    return tile_response(tile)


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
    service=Depends(get_dedicated_way_value_service),
) -> dict[int, float]:
    """「評価軸」グループとしての動的＋向きあり材料（風・勾配）。指定タイル内のway_idごとの
    値（風=wind_drag_ratio[backend/app/domain/wind.py]、勾配=effective_gradient
    [backend/app/domain/gradient.py]）をまとめて返す軽量なJSONエンドポイント。この
    エンドポイントはルート未確定時（視界内の全道路への一律適用）専用——ルート確定後は
    ルート自身の実進行方向・実到達時刻/実値から計算済みの`axis_difficulties`
    （`RouteSegmentDetail`）を使うため、フロントはこのエンドポイントを呼ばない。

    パスパラメータは**軸id**（`axis_definitions.axis_id`、例: `wind`/`gradient`）で、
    サービスが返す生値の材料id（`wind_drag_ratio`等、下の`service.material_id`）とは別の
    名前空間である。`domain/dynamic_way_values.py: dedicated_way_value_axes()`に無い未知の
    axis_idは404。`bearing_deg`（クエリパラメータ）はその軸が向きに依存する場合のみ
    必須（現状は風・勾配のどちらも必須、`needs_bearing`参照）——省略すると422。`at`は
    その軸が時刻に依存する場合のみ意味を持つ（風は必須ではなく省略時は現在時刻[Asia/Tokyo]
    を使う、勾配は時刻に依存しないため渡しても無視される）。`speed_kmh`（想定速度）は
    その軸が走行速度に依存する場合（`needs_speed`）のみ必須で、それ以外は無視される。

    静的な路面タイル（`/api/region/road-surface-tiles`、MVT、本エンドポイントとは無関係）
    とは別経路——フロントは同じz/x/yに対して両方を取得し、MapLibreの`setFeatureState`で
    合成する（`frontend/src/components/Map/dedicatedWayValueLayer.ts`参照）。
    タイル単位の値が地図表示専用のRedisキャッシュ（`dynamic_way_value_cache.py`）を経由する
    ため、パン・ズームで同じタイルが再び視界に入っても、同じ時刻バケット・向きバケットの
    範囲内では風グリッド・DBへの再問い合わせは発生しない。

    路面・POIタイルと同じレート制限・座標検証・DB接続プールのsemaphoreを共有する
    （本ファイルの`_region_tile_semaphore`のコメント参照——MVTエンコードは
    伴わないが同じPostGISコネクションプールを取り合うため）。
    """
    axis = dedicated_way_value_axes().get(axis_id)
    if axis is None or service is None:
        raise HTTPException(status_code=404, detail="未知のaxis_idです。")
    if axis.needs_bearing and bearing_deg is None:
        raise HTTPException(status_code=422, detail="この軸にはbearing_degが必須です。")
    if axis.needs_speed and speed_kmh is None:
        raise HTTPException(status_code=422, detail="この軸にはspeed_kmhが必須です。")
    _check_tile_rate_limit(request, f"{axis_id}-way-values")
    validate_tile_coords(z, x, y)
    async with _region_tile_semaphore:
        values = await service.get_way_values(z, x, y, at, bearing_deg, speed_kmh)
    # サービスは材料の生値を返しキャッシュも生値のまま持つ。地図が塗る値（難易度か符号付き
    # 材料か）への変換は軸定義から都度行うため、軸スタジオでbreakpointsを変えても
    # キャッシュを捨てずに即座に反映される。
    return transform_dedicated_way_values(AXIS_DEFINITIONS[axis_id], service.material_id, values)


class AxisInspectorRequest(BaseModel):
    osm_way_id: int


@router.post("/api/region/axis-inspector")
async def region_axis_inspector(
    body: AxisInspectorRequest,
    http_request: Request,
    region_service: RegionService = Depends(get_region_service),
) -> AxisInspectorResult | None:
    """区間インスペクタ。クリックされた道路（osm_way_id）について、
    一次属性（highway/tags/is_designated）→二次軸スコア（取得可能な軸のみ）→
    合成コスト（取得可能な軸だけの参考値、既定route_preference重み）を返す。
    POST+JSONボディ・osm_way_id完全一致で引く理由はRegionService.get_axis_inspectorの
    docstring参照（交差点付近での取り違え対策）。gradient/wind軸は単独wayでは算出不能
    なため常にavailable=falseで返る（ルートに含まれる区間の正確な値はルート生成結果
    自体を見る）。
    """
    # 座標なしの単発リクエストのためタイル向け_check_tile_rate_limit
    # （road_tile_rate_limit_per_minuteと結合）を流用せず、専用の設定値を直接使う
    # （config.py: axis_inspector_rate_limit_per_minuteのコメント参照）。
    enforce_rate_limit(http_request, "axis-inspector", settings.axis_inspector_rate_limit_per_minute)
    return await region_service.get_axis_inspector(body.osm_way_id)
