import type { ValueDistribution } from "@/features/admin/AxisStudio/scoreDistribution";
import { API_BASE_URL } from "@/lib/apiBaseUrl";
import {
  CATALOG_API_TIMEOUT_MS,
  DEFAULT_API_TIMEOUT_MS,
  DISTRIBUTION_API_TIMEOUT_MS,
  HEAVY_ADMIN_API_TIMEOUT_MS,
  STATUS_API_TIMEOUT_MS,
} from "@/lib/apiTimeouts";
import { fetchJson, requestJson } from "@/lib/fetchJson";
import type { components, paths } from "@/types/generated/api";
import type {
  AxisDefinitionPayload,
  AxisDefinitionResponse,
  DbStatusResponse,
  DerivedDataFreshnessResponse,
  MaterialCoverageResponse,
  MaterialValuesResponse,
} from "@/types/route";

type Schemas = components["schemas"];

interface AdminRequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  timeoutMs?: number;
  /** 失敗の文言の主語（例: "DB状態の取得"→「DB状態の取得に失敗しました」）。 */
  label: string;
}

/** backendの管理API`/api/admin<path>`を、同一オリジンの口`/admin/api<path>`経由で呼ぶ（/adminのBasic認証を
 * そのまま使う。`app/admin/api/[...path]/route.ts`）。区間の値は呼び出し側が`encodeURIComponent`する。 */
function adminRequest<T>(
  path: string,
  { method = "GET", body, timeoutMs = DEFAULT_API_TIMEOUT_MS, label }: AdminRequestOptions,
) {
  return requestJson<T>(`/admin/api${path}`, {
    method,
    body,
    timeoutMs,
    category: "api:admin",
    messages: { failure: `${label}に失敗しました`, parseFailure: `${label}の結果を解析できませんでした` },
    startLabel: `${method} ${path}`,
    ...(body !== undefined ? { requestMeta: { body } } : {}),
    logMeta: { path },
  });
}

const segment = encodeURIComponent;

// 軸の定義

export function listAxisDefinitions() {
  return adminRequest<AxisDefinitionResponse[]>("/axis-definitions", { label: "軸の一覧の取得" });
}

export function createAxisDefinition(payload: AxisDefinitionPayload) {
  return adminRequest<AxisDefinitionResponse>("/axis-definitions", {
    method: "POST",
    body: payload,
    label: "軸の保存",
  });
}

export function updateAxisDefinition(axisId: string, payload: AxisDefinitionPayload) {
  return adminRequest<AxisDefinitionResponse>(`/axis-definitions/${segment(axisId)}`, {
    method: "PUT",
    body: payload,
    label: "軸の保存",
  });
}

export function deleteAxisDefinition(axisId: string) {
  return adminRequest<void>(`/axis-definitions/${segment(axisId)}`, { method: "DELETE", label: "軸の削除" });
}

export function unpublishAxisDefinition(axisId: string) {
  return adminRequest<AxisDefinitionResponse>(`/axis-definitions/${segment(axisId)}/unpublish`, {
    method: "POST",
    label: "軸の非公開化",
  });
}

// 軸の編集中のプレビュー。分布は初回にWayの抽選と材料の組み立てを伴う。しきい値と点数はDBを読まない。

/** 編集中のshapeで、折れ点を通す前の生値がどう分布するか。 */
export function fetchAxisValueDistribution(shape: unknown) {
  return adminRequest<ValueDistribution>("/axis-definitions/preview-distribution", {
    method: "POST",
    body: { shape },
    timeoutMs: DISTRIBUTION_API_TIMEOUT_MS,
    label: "分布の取得",
  });
}

export type DisplayThresholdsPreviewRequest = Schemas["DisplayThresholdsPreviewRequest"];

/** 人が刻んだ段の境界が地図でどうなるか。`bandsOnMap`は地図の各段が入力のどの段に当たるか
 * （入力の段の番号、下から0始まり）で、nullは判定が無い（入力どおりの段で出す）。 */
export interface MapBandsOfThresholds {
  droppedOnMap: readonly number[];
  bandsOnMap: readonly number[] | null;
}

/** 編集中の軸で、人が刻んだ段の境界のうち地図では段にならないものと、地図に残る段。判定はbackendが地図の段を
 * 作るのと同じ関数で行う。 */
export async function fetchMapBandsOfThresholds(body: DisplayThresholdsPreviewRequest): Promise<MapBandsOfThresholds> {
  const response = await adminRequest<Schemas["DisplayThresholdsPreviewResponse"]>(
    "/axis-definitions/preview-display-thresholds",
    { method: "POST", body, label: "しきい値の確認" },
  );
  return { droppedOnMap: response.dropped_on_map, bandsOnMap: response.bands_on_map };
}

export type ScoresPreviewRequest = Schemas["ScoresPreviewRequest"];
export type ScoresPreview = Schemas["ScoresPreviewResponse"];

/** 編集中の折れ点で、値がそれぞれ何点になるか。点数はbackendが評価と同じ計算で出す。 */
export function fetchScoresPreview(body: ScoresPreviewRequest) {
  return adminRequest<ScoresPreview>("/axis-definitions/preview-scores", {
    method: "POST",
    body,
    label: "点数の確認",
  });
}

// 材料

export interface MaterialDistribution extends ValueDistribution {
  available: boolean;
}

/** 1材料の値が実データでどの範囲に散らばっているか。 */
export function fetchMaterialDistribution(materialId: string) {
  return adminRequest<MaterialDistribution>(`/material-catalog/${segment(materialId)}/distribution`, {
    timeoutMs: DISTRIBUTION_API_TIMEOUT_MS,
    label: "分布の取得",
  });
}

/** categoricalの材料が実データで取る値の一覧。 */
export function getMaterialValues(materialId: string) {
  return adminRequest<MaterialValuesResponse>(`/material-catalog/${segment(materialId)}/values`, {
    timeoutMs: CATALOG_API_TIMEOUT_MS,
    label: "材料の値一覧の取得",
  });
}

export function getMaterialCoverage() {
  return adminRequest<MaterialCoverageResponse>("/material-catalog/coverage", {
    timeoutMs: HEAVY_ADMIN_API_TIMEOUT_MS,
    label: "材料の欠損割合の取得",
  });
}

// データ保守

export function getDerivedDataFreshness() {
  return adminRequest<DerivedDataFreshnessResponse>("/derived-data/freshness", {
    timeoutMs: HEAVY_ADMIN_API_TIMEOUT_MS,
    label: "派生データ鮮度台帳の取得",
  });
}

export function getDbStatus() {
  return adminRequest<DbStatusResponse>("/db-status", { timeoutMs: HEAVY_ADMIN_API_TIMEOUT_MS, label: "DB状態の取得" });
}

export async function refreshTileCache(): Promise<void> {
  await adminRequest<unknown>("/basemap/refresh", { method: "POST", label: "タイルキャッシュの消去" });
}

// 較正値

/** 較正値1件の宣言と、いま効いている値。項目はbackendが宣言から導く。 */
export type TuningParameter = Schemas["TuningParameterView"];

export function listTuningParameters() {
  return adminRequest<TuningParameter[]>("/tuning", { label: "較正値の取得" });
}

/** 1件を書き換える。`value`にnullを渡すと既定へ戻す。 */
export function updateTuningParameter(paramId: string, value: number | null) {
  return adminRequest<TuningParameter>(`/tuning/${segment(paramId)}`, {
    method: "PUT",
    body: { value },
    label: "較正値の保存",
  });
}

// ログ

type LogsQuery = NonNullable<paths["/api/admin/debug/logs"]["get"]["parameters"]["query"]>;

/** Python標準loggingのレベル名。正本はbackendで、契約から引く。 */
export type LogLevelName = NonNullable<LogsQuery["min_level"]>;

/** 直近のログ行（プロセス内リングバッファ）。debug_modeがOFFの間もWARNING以上は常に含まれる。 */
export function getRecentLogs(query: LogsQuery = {}) {
  const params = new URLSearchParams(
    Object.entries(query).flatMap(([key, value]) => (value == null || value === "" ? [] : [[key, String(value)]])),
  ).toString();
  return adminRequest<string[]>(`/debug/logs${params ? `?${params}` : ""}`, { label: "ログの取得" });
}

// 稼働状況（認証の要らない口）

export type DebugStats = Schemas["DebugStatsResponse"];

export function getDebugStats() {
  return fetchJson<DebugStats>(`${API_BASE_URL}/api/debug/stats`, {
    timeoutMs: STATUS_API_TIMEOUT_MS,
    category: "api:debug-stats",
    errorLabel: "システム状況",
  });
}

/** `app/api/version/route.ts`の応答。 */
export interface FrontendVersion {
  commit: string | null;
  started_at: string;
}

export function getFrontendVersion() {
  return fetchJson<FrontendVersion>("/api/version", {
    timeoutMs: STATUS_API_TIMEOUT_MS,
    category: "api:version",
    errorLabel: "フロントエンドのバージョン",
  });
}

/** backendへ疎通できるか。画面は「OK/接続できません」の2値しか出さないため失敗の種類は返さないが、中身は
 * `requestJson`がdebugLogへ残す。 */
export async function checkBackendHealth(): Promise<boolean> {
  try {
    const data = await requestJson<{ status?: string }>(`${API_BASE_URL}/health`, {
      timeoutMs: STATUS_API_TIMEOUT_MS,
      category: "api:health",
      messages: {
        failure: "バックエンドへの疎通確認に失敗しました",
        parseFailure: "バックエンドへの疎通確認に失敗しました",
      },
    });
    return data?.status === "ok";
  } catch {
    return false;
  }
}
