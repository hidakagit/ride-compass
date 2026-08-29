import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from app.api.dependencies import get_region_service, get_wind_way_service
from app.api.routers._tile_validation import check_tile_rate_limit, validate_tile_coords
from app.config import settings
from app.domain.evaluation import AxisInspectorResult
from app.services.region_service import RegionService
from app.services.wind_way_service import WindWayService

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
    """路面・POIタイル向けの`check_tile_rate_limit`薄いラッパー。両タイルとも同じ
    上限値（settings.road_tile_rate_limit_per_minute）を使うが、キー・記録先の
    `prefix`は種別ごとに分ける（実処理・事故タイルとの共有は_tile_validation.py参照）。
    """
    check_tile_rate_limit(request, prefix, settings.road_tile_rate_limit_per_minute)


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


@router.get("/api/region/dynamic-way-values/wind/{z}/{x}/{y}")
async def region_dynamic_way_values_wind(
    z: int,
    x: int,
    y: int,
    request: Request,
    at: datetime | None = None,
    wind_way_service: WindWayService = Depends(get_wind_way_service),
) -> dict[int, float]:
    """「評価軸」グループとしての風（改善計画T405、docs/tasks/T400.md「2. 動的要素…の
    二重表現」節）。指定タイル内のway_idごとのwind_penalty（正=向かい風・負=追い風、
    backend/app/domain/wind.py: WindCalculator.wind_penalty参照）をまとめて返す軽量な
    JSONエンドポイント。

    静的な路面タイル（`/api/region/road-surface-tiles`、MVT、本エンドポイント新設に伴う
    変更なし）とは別経路——フロントは同じz/x/yに対して両方を取得し、MapLibreの
    `setFeatureState`で合成する（`frontend/src/components/Map/windAxisLayer.ts`参照）。
    `way_id`が地図表示専用のRedisキャッシュ（`wind_way_penalty_cache.py`）を経由するため、
    パン・ズームで同じ道路が再び視界に入っても風グリッド・DBへの再問い合わせは1時間
    バケットの範囲内では発生しない。

    `at`（クエリパラメータ）省略時は現在時刻（Asia/Tokyo）を使う。路面・POIタイルと同じ
    レート制限・座標検証・DB接続プールのsemaphoreを共有する（`region_service.py`の
    `_region_tile_semaphore`のコメント参照——MVTエンコードは伴わないが同じPostGIS
    コネクションプールを取り合うため）。
    """
    _check_tile_rate_limit(request, "wind-way-penalty")
    validate_tile_coords(z, x, y)
    async with _region_tile_semaphore:
        return await wind_way_service.get_way_wind_penalties(z, x, y, at)


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
    _check_tile_rate_limit(http_request, "axis-inspector")
    return await region_service.get_axis_inspector(body.osm_way_id)
