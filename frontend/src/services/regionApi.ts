import type { AxisInspectorResult } from "@/types/traffic";
import { API_BASE_URL } from "@/lib/apiBaseUrl";
import { tileBaseUrl } from "@/lib/tileBaseUrl";
import { debugLog } from "@/lib/debugLog";
import { formatErrorDetail } from "@/lib/apiError";

interface PostRequestOptions {
  category: string;
  /** 「{errorLabel}に失敗しました」の形でエラーメッセージに使う対象名。 */
  errorLabel: string;
  /** 指定時はJSONボディとして送る（Content-Type: application/jsonも自動で付く）。
   * 省略時はボディ無しのPOST（refreshBasemapCacheのような操作系エンドポイント向け）。 */
  body?: unknown;
  timeoutMs?: number;
}

// 改善計画T470: fetchAxisInspector・refreshBasemapCacheが、fetch()自体の失敗（通信エラー）→
// !response.okの判定→エラーボディ解析→整形したErrorをthrow、という同じ約20行のPOST用骨格を
// 独立に持っていた（lib/fetchJson.tsのGET専用ラッパーと同型だが、POSTはボディ・成功時の
// レスポンス解釈が呼び出しごとに異なるため、GET側のfetchJsonとは別に本ファイル内へ持つ——
// routeApi.ts: postJsonと同じ判断）。成功時のレスポンス本体解析・成功ログのfields組み立ては
// 呼び出し側ごとに異なる（fetchAxisInspectorはJSONボディを持ちcompositeを追加ログするが
// refreshBasemapCacheはボディ無しでレスポンス本体も読まない）ため、ここでは「fetch→
// 通信エラー処理→ok確認→失敗時throw」までを共通化し、成功時のResponseはそのまま返す。
async function postAndCheckOk(
  path: string,
  { category, errorLabel, body, timeoutMs = 15000 }: PostRequestOptions,
): Promise<{ response: Response; durationMs: number; requestId: string | null }> {
  const startedAt = performance.now();
  const url = `${API_BASE_URL}${path}`;
  debugLog(category, "リクエスト開始", body !== undefined ? { url, body } : { url });

  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      ...(body !== undefined ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    debugLog(
      category,
      "失敗 (通信エラー)",
      { durationMs: Math.round(performance.now() - startedAt), error: error instanceof Error ? error.message : String(error) },
      "error",
    );
    throw error instanceof Error ? error : new Error(`${errorLabel}に失敗しました`);
  }
  const durationMs = Math.round(performance.now() - startedAt);
  // バックエンドが全リクエストに付与するリクエストID(backend/app/infrastructure/request_log.py)。
  const requestId = response.headers.get("x-request-id");

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    debugLog(category, `失敗 (HTTP ${response.status})`, { durationMs, requestId, errorBody }, "error");
    const detail = formatErrorDetail(errorBody?.detail) ?? `${errorLabel}に失敗しました[HTTP ${response.status}]`;
    throw new Error(requestId ? `${detail}[req: ${requestId}]` : detail);
  }
  return { response, durationMs, requestId };
}

const ROAD_SURFACE_TILE_PATH = "/api/region/road-surface-tiles/{z}/{x}/{y}.pbf";
const ACCIDENT_TILE_PATH = "/api/region/accident-tiles/{z}/{x}/{y}.pbf";
const POI_TILE_PATH = "/api/region/poi-tiles/{z}/{x}/{y}.pbf";

// タイル内容の世代。タイルへ焼き込むプロパティが増えた（内容の互換性が変わった）ときに
// 上げると、URLが変わることでブラウザHTTPキャッシュ（Cache-Control: max-age=3600）に残る
// 旧世代タイルを踏まなくなる。バックエンドのファイルキャッシュ側の世代
// （region_service.pyの_tile_cache_path）と対で更新すること。
// プロパティの追加・削除のみ（既存プロパティの意味を変えない）なら後方互換で、世代を
// 上げるだけでよい。既存プロパティの意味自体を変える非互換変更は、backend
// （road_graph_repository.py）がこの世代へ切り替わるより先にこの変更を含むfrontendを
// デプロイすること（逆順だと、新世代前提の凡例フィルタが全地物に一致し、対象レイヤーが
// 一時的に全線「不明・他」表示になる。docs/architecture.md「Renderデプロイの反映確認」
// 参照）。
const ROAD_SURFACE_TILE_VERSION = "18";

// 路面の地域レイヤー（Step10）のベクタタイルURL。オリジンは`tileBaseUrl()`
// （lib/tileBaseUrl.ts: 既定はフロント自身のオリジン＝Next.jsのrewrites経由、
// `NEXT_PUBLIC_TILE_BASE_URL`設定時はbackend直接）に従う。ベクタタイルの取得はMapLibreが
// Web Worker内で行うため相対パスでは解決できず絶対URLが必要で、`window`をSSR時に参照しない
// よう呼び出し時（クライアントサイドのみ）に評価する関数として提供する。
export function roadSurfaceTileUrl(): string {
  return `${tileBaseUrl()}${ROAD_SURFACE_TILE_PATH}?v=${ROAD_SURFACE_TILE_VERSION}`;
}

// 事故レイヤー（外部静的データソース）のタイル世代。バックエンド側
// （accident_service.pyのACCIDENT_TILE_VERSION）と対で更新すること。
const ACCIDENT_TILE_VERSION = "1";

export function accidentTileUrl(): string {
  return `${tileBaseUrl()}${ACCIDENT_TILE_PATH}?v=${ACCIDENT_TILE_VERSION}`;
}

// 停止要因POIレイヤーの世代。バックエンド（region_service.py: POI_TILE_VERSION）と対で
// 上げる。ROAD_SURFACE_TILE_VERSIONと同じ理由（ブラウザHTTPキャッシュのバスト用）。
// stop_poiのみの1レイヤー構成（交差点密度は地図上の独立可視化レイヤーとしては提供しない、
// staticAttributeLayers.ts参照）。
const POI_TILE_VERSION = "3";

// 停止要因POIの地域レイヤーのベクタタイルURL。
// roadSurfaceTileUrlと同じ理由（MapLibreのWeb Worker内取得のため絶対URL化が必要）で
// 呼び出し時に評価する関数として提供する。
export function poiTileUrl(): string {
  return `${tileBaseUrl()}${POI_TILE_PATH}?v=${POI_TILE_VERSION}`;
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
  const { response, durationMs, requestId } = await postAndCheckOk("/api/region/axis-inspector", {
    category: "api:axis-inspector",
    errorLabel: "内訳取得",
    body: { osm_way_id: osmWayId },
  });
  const data: AxisInspectorResult | null = await response.json();
  debugLog("api:axis-inspector", "成功", { durationMs, requestId, composite: data?.composite_difficulty });
  return data;
}

// way_id→動的値配信層（風・勾配、改善計画T405→T414→T423、docs/tasks/T400.md「2. 動的要素…の
// 二重表現」節）。「評価軸」グループ向けに、指定タイル内のway_idごとの値（風=wind_drag_ratio、
// 勾配=effective_gradient）をまとめて取得する。road-surface-tiles（MapLibreのWeb Worker
// 経由）とは別経路で、fetchAxisInspectorと同じくアプリのfetch()から直接呼ぶ（絶対URL化は
// 不要）。バージョンクエリを持たない（road-surface-tilesと異なりブラウザHTTPキャッシュに
// 乗せない想定の軽量JSON、値自体はbackend側のRedis TTLで新鮮さを管理するため）。
//
// 改善計画T423（T411の実施）: エンドポイントパスを`wind`固定から`{material_id}`駆動へ
// 一本化したのに合わせ、フロント側の関数も`fetchWindWayPenalties`から材料id引数を取る
// `fetchDynamicWayValues`へ汎用化した。
const DYNAMIC_WAY_VALUES_PATH = "/api/region/dynamic-way-values";

export interface DynamicWayValuesResult {
  values: Record<string, number>;
  /** 通信失敗（HTTPエラー・ネットワークエラー・タイムアウト）ならtrue。backendが正常応答で
   * 空オブジェクトを返した場合（対象範囲に本当にway_idが無い）はfalseのまま——呼び出し側が
   * 「取得失敗」と「本当に空」を区別できるようにする。 */
  error: boolean;
}

/** 指定タイル（road-surface-tilesと同じz/x/y）内のway_idごとの動的値（風=wind_drag_ratio、
 * 勾配=effective_gradient）をまとめて取得する。失敗時は例外を投げず`error: true`へ
 * フォールバックする——背景の色分けレイヤーという補助的な機能のため、道路タイル自体の
 * 表示・他レイヤーを巻き込んで止めない（useWeatherGridのdetailGrid取得と同じ
 * 「補助機能はサイレントにフォールバック」方針。ただし失敗そのものは`error`で呼び出し側へ
 * 伝える——道路タイルは止めないが、道路の色分け自体が失敗したことは利用者へ示せるように
 * するため）。
 *
 * `bearingDeg`（ユーザーがコンパススライダーで指定した走行方位、0〜360度、北=0・時計回り）を
 * 必須クエリパラメータとして渡す。`at`は環境グループ（矢印・gridFill）と共有する時刻
 * （省略時はbackend側が現在時刻を使う。勾配は時刻に依存しないため常に省略）。 */
export async function fetchDynamicWayValues(
  materialId: string,
  z: number,
  x: number,
  y: number,
  bearingDeg: number,
  at?: Date,
  speedKmh?: number
): Promise<DynamicWayValuesResult> {
  const params = new URLSearchParams({ bearing_deg: String(bearingDeg) });
  if (at) params.set("at", at.toISOString());
  // 走行速度に依存する材料（needs_speed）だけがbackend側で使う。他の材料へ渡しても無視される。
  if (speedKmh !== undefined && Number.isFinite(speedKmh)) params.set("speed_kmh", String(speedKmh));
  const url = `${API_BASE_URL}${DYNAMIC_WAY_VALUES_PATH}/${materialId}/${z}/${x}/${y}?${params.toString()}`;
  const logCategory = `api:${materialId}-way-values`;
  const startedAt = performance.now();
  debugLog(logCategory, "リクエスト開始", { url });
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(15000) });
    const durationMs = Math.round(performance.now() - startedAt);
    if (!response.ok) {
      debugLog(logCategory, `失敗 (HTTP ${response.status})`, { durationMs }, "error");
      return { values: {}, error: true };
    }
    const data = (await response.json()) as Record<string, number>;
    debugLog(logCategory, "成功", { durationMs, wayCount: Object.keys(data).length });
    return { values: data, error: false };
  } catch (error) {
    debugLog(
      logCategory,
      "失敗 (通信エラー)",
      {
        durationMs: Math.round(performance.now() - startedAt),
        error: error instanceof Error ? error.message : String(error),
      },
      "error",
    );
    return { values: {}, error: true };
  }
}

export async function refreshBasemapCache(): Promise<void> {
  // 以前はtry/catchも!response.okのチェックも無く、ネットワークエラー時は
  // 未処理のPromise rejectionになり、失敗時に呼び出し元(MapView.tsx)へ何も伝わらず
  // 「変わらないデータを更新」ボタンが無反応に見えていた（改善計画T328で発見・修正）。
  const { durationMs, requestId } = await postAndCheckOk("/api/basemap/refresh", {
    category: "api:basemap-refresh",
    errorLabel: "地図キャッシュの更新",
  });
  debugLog("api:basemap-refresh", "成功", { durationMs, requestId });
}
