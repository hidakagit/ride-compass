import type { AxisInspectorResult } from "@/types/traffic";
import { debugLog } from "@/lib/debugLog";
import { formatErrorDetail } from "@/lib/apiError";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const ROAD_SURFACE_TILE_PATH = "/api/region/road-surface-tiles/{z}/{x}/{y}.pbf";
const ACCIDENT_TILE_PATH = "/api/region/accident-tiles/{z}/{x}/{y}.pbf";
const POI_TILE_PATH = "/api/region/poi-tiles/{z}/{x}/{y}.pbf";

// タイル内容の世代。タイルへ焼き込むプロパティが増えた（内容の互換性が変わった）ときに
// 上げると、URLが変わることでブラウザHTTPキャッシュ（Cache-Control: max-age=3600）に残る
// 旧世代タイルを踏まなくなる。バックエンドのファイルキャッシュ側の世代
// （region_service.pyの_tile_cache_path）と対で更新すること。
// v11: 改善計画T122。shoulder材料タグ（付与率0.0%の死に補正、T102実測）を撤去した。
// プロパティ削除を伴うが、shoulderは元々全fetchで実質未使用だったため、v9のような
// 厳格なデプロイ順序制約はない。
// v10: 安全度レシピ（T148で削除済み）。当時の材料タグ（shoulder/lit、tunnelは既存
// プロパティを再利用）追加のため世代を上げた。lit自体はT139でnight軸へ転用され現在も使用中。
// v9: 車ストレスレシピ外出し基盤。計算済みのcar_stress最終値プロパティを廃止し、
// 材料タグ（cycleway_class/maxspeed_kmh/lanes_count/motor_vehicle_no）へ差し替えた
// （最終値の計算は改善計画T292以降、components/Map/axisLayers.tsの汎用rampパイプラインが
// MapLibre expressionとして行う。専用手書きexpression`carStressExpression.ts`は廃止済み）。
// v2〜v8はプロパティ追加のみで旧フロントとの後方互換が保たれていたが、v9はプロパティ削除を
// 伴う初めての非互換変更。backend（road_graph_repository.py）がこの世代へ切り替わるより先に
// この変更を含むfrontendをデプロイすること（逆順だと、この世代のcar_stress前提の凡例
// フィルタが全地物に一致し、車ストレスレイヤーが一時的に全線「不明・他」表示になる。
// docs/architecture.md「Renderデプロイの反映確認」参照）。
// v8: 改善計画T93（統合レビュー2026-08-17 F-1）。T92のcar_stress判定ロジック変更
// （secondary系base値4→3、shared_lane/share_busway・lanes<=1補正）がタイル世代の対上げを
// 伴っていなかったため、キャッシュ陳腐化を断つために世代のみ更新（プロパティ構成は不変）。
// v7: 改善計画T90。車ストレスの区間別判定内訳表示のため、osm_way_idプロパティを追加した。
// v6: 改善計画T74。designation_attributesをosm_way_id基準（road_edges遅延構築非依存）へ
// 変更し、designationプロパティの3値目"both"（N10・N12両方該当）を追加した。
// v5: 指定路線コンフレーション機構（外部静的データソース T51）でdesignationプロパティを
// 追加し、car_stressへKSJ N10/N12該当の+1補正を組み込んだ。
// v4: 静的道路属性P0（docs/static-road-attributes-plan.md）でsmoothness/tunnel/bridge/
// car_stress/bicycle_infraプロパティを追加した。
// v3: surface正準分類の拡充（chipseal/bricks=良い、rock/unhewn_cobblestone=悪い、T7）で
// surface_goodの値が変わった。
// v2: surface（正規化済み生タグ）・highwayプロパティ追加（色分けモード用）。
// v12: 改善計画T145b。二次軸rampレイヤー用の事前集計密度プロパティ
// （accident_per_km/stop_per_km/intersection_per_km）を追加。
// v13: 改善計画T289。一方通行（一次属性、oneway）プロパティを追加。
const ROAD_SURFACE_TILE_VERSION = "13";

// 路面の地域レイヤー（Step10）のベクタタイルURL。基礎地図タイルと同じ理由でフロントエンド
// 自身のオリジン（Next.jsのrewrites経由でバックエンドにプロキシ）を使う。ベクタタイルの
// 取得はMapLibreがWeb Worker内で行うため、相対パスのままだと「ページのオリジンに対して
// 解決する」というラスタタイル（Image要素の読み込み、メインスレッド）の挙動が通用せず、
// URLの構築に失敗することを実機確認した。window.location.originで明示的に絶対URL化する
// 必要があるため、モジュール読み込み時ではなく呼び出し時（クライアントサイドのみ）に
// 評価する関数として提供する。
export function roadSurfaceTileUrl(): string {
  return `${window.location.origin}${ROAD_SURFACE_TILE_PATH}?v=${ROAD_SURFACE_TILE_VERSION}`;
}

// 事故レイヤー（外部静的データソース T50）のタイル世代。バックエンド側
// （accident_service.pyのACCIDENT_TILE_VERSION）と対で更新すること。
// v1: 初回実装（involves_bicycle/fatal/occurred_yearプロパティ）。
const ACCIDENT_TILE_VERSION = "1";

export function accidentTileUrl(): string {
  return `${window.location.origin}${ACCIDENT_TILE_PATH}?v=${ACCIDENT_TILE_VERSION}`;
}

// 停止要因POIレイヤー（改善計画T54）の世代。バックエンド（region_service.py:
// POI_TILE_VERSION）と対で上げる。ROAD_SURFACE_TILE_VERSIONと同じ理由（ブラウザHTTP
// キャッシュのバスト用）。
// v3: T101（補給・休憩ポイントPOIレイヤー）。osm_raw_pois.kindへコンビニ・自販機・
// トイレ・給水・駐輪場を追加。
// v2: T97。地図の独立可視化レイヤーとしては使われなくなっていた（T96）intersectionレイヤーの
// 配信自体をバックエンドから削除し、stop_poiのみの1レイヤー構成へ変更した世代。
// v1: 初版（stop_poi・intersectionの2レイヤー）。
const POI_TILE_VERSION = "3";

// 停止要因POIの地域レイヤー（改善計画T54）のベクタタイルURL。
// roadSurfaceTileUrlと同じ理由（MapLibreのWeb Worker内取得のため絶対URL化が必要）で
// 呼び出し時に評価する関数として提供する。
export function poiTileUrl(): string {
  return `${window.location.origin}${POI_TILE_PATH}?v=${POI_TILE_VERSION}`;
}

// バックエンド（domain/region.py）のROAD_TILE_MIN_ZOOM/MAX_ZOOMと一致させる。
// POI/交差点密度レイヤーもT54で同じズーム範囲に準拠する（api/routers/region.py参照）。
export const ROAD_TILE_MIN_ZOOM = 12;
export const ROAD_TILE_MAX_ZOOM = 15;

// 区間インスペクタ（改善計画T146）。地図上の道路クリックで得たosm_way_id（路面タイルの
// MVTプロパティに含まれる識別子）から一次属性・全二次軸（車の圧迫感を含む）・合成コストを
// 取得するAPI。緯度経度の空間マッチではなくosm_way_id完全一致にしている理由は
// backend/app/services/region_service.py: get_axis_inspectorのdocstring参照
// （交差点付近での取り違えを実機確認で発見し、この方式にした）。タイルURL系
// （roadSurfaceTileUrl等）と違いMapLibreのWeb Worker経由ではなくアプリのfetch()から
// 直接呼ぶため、ここだけ絶対URL化（window.location.origin）が不要（weatherApi.ts等と同じ）。
// POST+JSONボディなのはosm_way_idを本文で渡す既存の設計を踏襲（backend/app/api/routers/
// region.py参照）。改善計画T292: 車ストレス専用の内訳取得（旧fetchCarStressBreakdown、
// レシピ上書きパラメータ）は専用Pythonレシピの廃止に伴い削除し、このAPIへ一本化した。
export async function fetchAxisInspector(osmWayId: number): Promise<AxisInspectorResult | null> {
  const url = `${API_BASE_URL}/api/region/axis-inspector`;
  const startedAt = performance.now();
  debugLog("api:axis-inspector", "リクエスト開始", { url, osmWayId });

  // fetch()自体の失敗（タイムアウト・通信エラー）はresponse.okのチェック以前の例外のため、
  // ここで捕まえないとdebugLogに一切残らない（refreshBasemapCacheで確立したパターン）。
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ osm_way_id: osmWayId }),
      signal: AbortSignal.timeout(15000),
    });
  } catch (error) {
    debugLog(
      "api:axis-inspector",
      "失敗 (通信エラー)",
      { durationMs: Math.round(performance.now() - startedAt), error: error instanceof Error ? error.message : String(error) },
      "error",
    );
    throw error instanceof Error ? error : new Error("内訳取得に失敗しました");
  }
  const durationMs = Math.round(performance.now() - startedAt);
  const requestId = response.headers.get("x-request-id");

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    debugLog("api:axis-inspector", `失敗 (HTTP ${response.status})`, { durationMs, requestId, errorBody }, "error");
    const detail = formatErrorDetail(errorBody?.detail) ?? `内訳取得に失敗しました[HTTP ${response.status}]`;
    throw new Error(requestId ? `${detail}[req: ${requestId}]` : detail);
  }

  const data: AxisInspectorResult | null = await response.json();
  debugLog("api:axis-inspector", "成功", { durationMs, requestId, composite: data?.composite_difficulty });
  return data;
}

export async function refreshBasemapCache(): Promise<void> {
  const startedAt = performance.now();
  debugLog("api:basemap-refresh", "リクエスト開始");
  // 以前はtry/catchも!response.okのチェックも無く、ネットワークエラー時は
  // 未処理のPromise rejectionになり、失敗時に呼び出し元(MapView.tsx)へ何も伝わらず
  // 「変わらないデータを更新」ボタンが無反応に見えていた。
  try {
    const response = await fetch(`${API_BASE_URL}/api/basemap/refresh`, {
      method: "POST",
      signal: AbortSignal.timeout(15000),
    });
    const durationMs = Math.round(performance.now() - startedAt);
    const requestId = response.headers.get("x-request-id");
    debugLog(
      "api:basemap-refresh",
      response.ok ? "成功" : `失敗 (HTTP ${response.status})`,
      { durationMs, requestId },
      response.ok ? "info" : "error",
    );
    if (!response.ok) {
      throw new Error(`地図キャッシュの更新に失敗しました[HTTP ${response.status}]`);
    }
  } catch (error) {
    debugLog(
      "api:basemap-refresh",
      "失敗 (通信エラー)",
      {
        durationMs: Math.round(performance.now() - startedAt),
        error: error instanceof Error ? error.message : String(error),
      },
      "error",
    );
    throw error instanceof Error ? error : new Error("地図キャッシュの更新に失敗しました");
  }
}
