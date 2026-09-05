import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.api.dependencies import enforce_rate_limit, get_dynamic_way_value_service, get_region_service
from app.api.routers._tile_validation import validate_tile_coords
from app.config import settings
from app.domain.axis_definitions import AXIS_DEFINITIONS
from app.domain.dynamic_way_values import dynamic_way_value_materials, transform_dedicated_way_values
from app.domain.evaluation import AxisInspectorResult
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
    validate_tile_coords(z, x, y)
    async with _region_tile_semaphore:
        tile_bytes = await region_service.get_poi_tile(z, x, y)
    return Response(
        content=tile_bytes,
        media_type="application/vnd.mapbox-vector-tile",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/api/region/dynamic-way-values/{material_id}/{z}/{x}/{y}")
async def region_dynamic_way_values(
    material_id: str,
    z: int,
    x: int,
    y: int,
    request: Request,
    bearing_deg: float | None = None,
    at: datetime | None = None,
    speed_kmh: float | None = None,
    service=Depends(get_dynamic_way_value_service),
) -> dict[int, float]:
    """「評価軸」グループとしての動的＋向きあり材料（風・勾配、改善計画T405→T414→T423、
    docs/tasks/T400.md「2. 動的要素…は状態（ルートの有無）に応じてパラメータの出所と塗る
    対象が変わる」節）。指定タイル内のway_idごとの値（風=wind_penalty[backend/app/domain/
    wind.py]、勾配=effective_gradient[backend/app/domain/gradient.py]）をまとめて返す
    軽量なJSONエンドポイント。このエンドポイントはルート未確定時（視界内の全道路への
    一律適用）専用——ルート確定後はルート自身の実進行方向・実到達時刻/実値から計算済みの
    `axis_difficulties`（`RouteSegmentDetail`）を使うため、フロントはこのエンドポイントを
    呼ばない。

    `material_id`はパスパラメータ（改善計画T411の実施: `wind`専用の固定パスをT423で
    材料id駆動へ一本化した）。`domain/dynamic_way_values.py: dynamic_way_value_materials()`
    に無い未知のidは404。`bearing_deg`（クエリパラメータ）はその材料が向きに依存する場合のみ
    必須（現状は風・勾配のどちらも必須、`needs_bearing`参照）——省略すると422。`at`は
    その材料が時刻に依存する場合のみ意味を持つ（風は必須ではなく省略時は現在時刻[Asia/Tokyo]
    を使う、勾配は時刻に依存しないため渡しても無視される）。`speed_kmh`（想定速度）は
    その材料が走行速度に依存する場合（`needs_speed`）のみ必須で、それ以外は無視される。

    静的な路面タイル（`/api/region/road-surface-tiles`、MVT、本エンドポイントとは無関係）
    とは別経路——フロントは同じz/x/yに対して両方を取得し、MapLibreの`setFeatureState`で
    合成する（`frontend/src/components/Map/windAxisLayer.ts`・`gradientAxisLayer.ts`参照）。
    タイル単位の値が地図表示専用のRedisキャッシュ（`dynamic_way_value_cache.py`）を経由する
    ため、パン・ズームで同じタイルが再び視界に入っても、同じ時刻バケット・向きバケットの
    範囲内では風グリッド・DBへの再問い合わせは発生しない。

    路面・POIタイルと同じレート制限・座標検証・DB接続プールのsemaphoreを共有する
    （`region_service.py`の`_region_tile_semaphore`のコメント参照——MVTエンコードは
    伴わないが同じPostGISコネクションプールを取り合うため）。
    """
    material = dynamic_way_value_materials().get(material_id)
    if material is None or service is None:
        raise HTTPException(status_code=404, detail="未知のmaterial_idです。")
    if material.needs_bearing and bearing_deg is None:
        raise HTTPException(status_code=422, detail="この材料にはbearing_degが必須です。")
    if material.needs_speed and speed_kmh is None:
        raise HTTPException(status_code=422, detail="この材料にはspeed_kmhが必須です。")
    _check_tile_rate_limit(request, f"{material_id}-way-values")
    validate_tile_coords(z, x, y)
    async with _region_tile_semaphore:
        values = await service.get_way_values(z, x, y, at, bearing_deg, speed_kmh)
    # サービスは材料の生値を返しキャッシュも生値のまま持つ。地図が塗る値（難易度か符号付き
    # 材料か）への変換は軸定義から都度行うため、軸スタジオでbreakpointsを変えても
    # キャッシュを捨てずに即座に反映される。
    return transform_dedicated_way_values(AXIS_DEFINITIONS[material_id], service.material_id, values)


class AxisInspectorRequest(BaseModel):
    osm_way_id: int


@router.post("/api/region/axis-inspector")
async def region_axis_inspector(
    body: AxisInspectorRequest,
    http_request: Request,
    region_service: RegionService = Depends(get_region_service),
) -> AxisInspectorResult | None:
    """区間インスペクタ（改善計画T146）。クリックされた道路（osm_way_id）について、
    一次属性（highway/tags/is_designated）→二次軸スコア（取得可能な軸のみ）→
    合成コスト（取得可能な軸だけの参考値、既定route_preference重み）を返す。
    POST+JSONボディ・osm_way_id完全一致で引く理由はRegionService.get_axis_inspectorの
    docstring参照（交差点付近での取り違え対策）。gradient/wind軸は単独wayでは算出不能
    なため常にavailable=falseで返る（ルートに含まれる区間の正確な値はルート生成結果
    自体を見る）。

    改善計画T292: 車ストレス専用レシピ（旧`/api/region/car-stress-breakdown`、
    `CarStressBreakdown`）は廃止し、本エンドポイント（軸別の汎用内訳）へ統合した。
    レシピ上書きパラメータ（旧car_stress_recipe等）も、専用Pythonレシピの廃止に伴い
    廃止した。
    """
    # 改善計画T467: 座標なしの単発リクエストのためタイル向け_check_tile_rate_limit
    # （road_tile_rate_limit_per_minuteと結合）を流用せず、専用の設定値を直接使う
    # （config.py: axis_inspector_rate_limit_per_minuteのコメント参照。値自体は変更なし）。
    enforce_rate_limit(http_request, "axis-inspector", settings.axis_inspector_rate_limit_per_minute)
    return await region_service.get_axis_inspector(body.osm_way_id)
