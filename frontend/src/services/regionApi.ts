import type { TrafficStressBreakdown } from "@/types/traffic";
import type { TrafficStressRecipeOverride } from "@/types/route";
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
// v9: 交通ストレスレシピ外出し基盤。計算済みのtraffic_stress最終値プロパティを廃止し、
// 材料タグ（cycleway_class/maxspeed_kmh/lanes_count/motor_vehicle_no）へ差し替えた
// （最終値の計算はtrafficStressExpression.tsがMapLibre expressionとして行う）。
// v2〜v8はプロパティ追加のみで旧フロントとの後方互換が保たれていたが、v9はプロパティ削除を
// 伴う初めての非互換変更。backend（road_graph_repository.py）がこの世代へ切り替わるより先に
// この変更を含むfrontendをデプロイすること（逆順だと、この世代のtraffic_stress前提の凡例
// フィルタが全地物に一致し、交通ストレスレイヤーが一時的に全線「不明・他」表示になる。
// docs/architecture.md「Renderデプロイの反映確認」参照）。
// v8: 改善計画T93（統合レビュー2026-08-17 F-1）。T92のtraffic_stress判定ロジック変更
// （secondary系base値4→3、shared_lane/share_busway・lanes<=1補正）がタイル世代の対上げを
// 伴っていなかったため、キャッシュ陳腐化を断つために世代のみ更新（プロパティ構成は不変）。
// v7: 改善計画T90。交通ストレスの区間別判定内訳表示のため、osm_way_idプロパティを追加した。
// v6: 改善計画T74。designation_attributesをosm_way_id基準（road_edges遅延構築非依存）へ
// 変更し、designationプロパティの3値目"both"（N10・N12両方該当）を追加した。
// v5: 指定路線コンフレーション機構（外部静的データソース T51）でdesignationプロパティを
// 追加し、traffic_stressへKSJ N10/N12該当の+1補正を組み込んだ。
// v4: 静的道路属性P0（docs/static-road-attributes-plan.md）でsmoothness/tunnel/bridge/
// traffic_stress/bicycle_infraプロパティを追加した。
// v3: surface正準分類の拡充（chipseal/bricks=良い、rock/unhewn_cobblestone=悪い、T7）で
// surface_goodの値が変わった。
// v2: surface（正規化済み生タグ）・highwayプロパティ追加（色分けモード用）。
const ROAD_SURFACE_TILE_VERSION = "9";

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

// 停止要因POI・交差点密度レイヤー（改善計画T54）の世代。バックエンド（region_service.py:
// POI_TILE_VERSION）と対で上げる。ROAD_SURFACE_TILE_VERSIONと同じ理由（ブラウザHTTP
// キャッシュのバスト用）。
// v1: 初版（stop_poi・intersectionの2レイヤー）。
const POI_TILE_VERSION = "1";

// 停止要因POI・交差点密度の地域レイヤー（改善計画T54）のベクタタイルURL。
// roadSurfaceTileUrlと同じ理由（MapLibreのWeb Worker内取得のため絶対URL化が必要）で
// 呼び出し時に評価する関数として提供する。
export function poiTileUrl(): string {
  return `${window.location.origin}${POI_TILE_PATH}?v=${POI_TILE_VERSION}`;
}

// バックエンド（domain/region.py）のROAD_TILE_MIN_ZOOM/MAX_ZOOMと一致させる。
// POI/交差点密度レイヤーもT54で同じズーム範囲に準拠する（api/routers/region.py参照）。
export const ROAD_TILE_MIN_ZOOM = 12;
export const ROAD_TILE_MAX_ZOOM = 15;

// 交通ストレスの区間別判定内訳（改善計画T90）。地図上の道路クリックで得たosm_way_id
// （路面タイルのMVTプロパティに含まれる識別子）から判定根拠（ベース値・各補正・最終値）を
// 取得するAPI。緯度経度の空間マッチではなくosm_way_id完全一致にしている理由は
// backend/app/services/region_service.py: get_traffic_stress_breakdownのdocstring参照
// （交差点付近での取り違えを実機確認で発見し、この方式にした）。タイルURL系
// （roadSurfaceTileUrl等）と違いMapLibreのWeb Worker経由ではなくアプリのfetch()から
// 直接呼ぶため、ここだけ絶対URL化（window.location.origin）が不要（weatherApi.ts等と同じ）。
//
// GETではなくPOST+JSONボディなのは、`recipe`（交通ストレスレシピの上書き、研究モードで
// レシピを上書き中はここにも渡して地図・ルート採点と表示を一致させる）という複雑な
// オブジェクトをクエリパラメータで渡すのが不自然なため（backend/app/api/routers/region.py参照）。
export async function fetchTrafficStressBreakdown(
  osmWayId: number,
  recipe?: TrafficStressRecipeOverride,
): Promise<TrafficStressBreakdown | null> {
  const url = `${API_BASE_URL}/api/region/traffic-stress-breakdown`;
  const startedAt = performance.now();
  debugLog("api:traffic-stress-breakdown", "リクエスト開始", { url, osmWayId });

  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ osm_way_id: osmWayId, traffic_stress_recipe: recipe ?? null }),
    signal: AbortSignal.timeout(15000),
  });
  const durationMs = Math.round(performance.now() - startedAt);
  const requestId = response.headers.get("x-request-id");

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    debugLog("api:traffic-stress-breakdown", `失敗 (HTTP ${response.status})`, { durationMs, requestId, errorBody }, "error");
    const detail = formatErrorDetail(errorBody?.detail) ?? `交通ストレスの内訳取得に失敗しました[HTTP ${response.status}]`;
    throw new Error(requestId ? `${detail}[req: ${requestId}]` : detail);
  }

  const data: TrafficStressBreakdown | null = await response.json();
  debugLog("api:traffic-stress-breakdown", "成功", { durationMs, requestId, level: data?.level });
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
