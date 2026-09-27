import { adminApiClient, backendApi, fetchJson, getOptions, requestApi } from "@/lib/apiClient";
import {
  CATALOG_API_TIMEOUT_MS,
  DEFAULT_API_TIMEOUT_MS,
  DISTRIBUTION_API_TIMEOUT_MS,
  HEAVY_ADMIN_API_TIMEOUT_MS,
  STATUS_API_TIMEOUT_MS,
} from "@/lib/apiTimeouts";
import type { components, paths } from "@/types/generated/api";
import type { AxisDefinitionPayload, AxisShape } from "@/types/route";

type Schemas = components["schemas"];

/** 管理APIの呼び出しの骨格の設定。`label`は失敗の文言の主語（例: "DB状態の取得"→「DB状態の取得に失敗しました」）。
 * 本文を送る呼び出しは`body`を渡すと開始のログに載る。 */
function adminOptions(
  label: string,
  { timeoutMs = DEFAULT_API_TIMEOUT_MS, body }: { timeoutMs?: number; body?: unknown } = {},
) {
  return {
    timeoutMs,
    category: "api:admin",
    messages: { failure: `${label}に失敗しました`, parseFailure: `${label}の結果を解析できませんでした` },
    ...(body !== undefined ? { requestMeta: { body } } : {}),
  };
}

// 軸の定義

export function listAxisDefinitions() {
  return requestApi((init) => adminApiClient.GET("/axis-definitions", init), adminOptions("軸の一覧の取得"));
}

export function createAxisDefinition(payload: AxisDefinitionPayload) {
  return requestApi(
    (init) => adminApiClient.POST("/axis-definitions", { body: payload, ...init }),
    adminOptions("軸の保存", { body: payload }),
  );
}

export function updateAxisDefinition(axisId: string, payload: AxisDefinitionPayload) {
  return requestApi(
    (init) =>
      adminApiClient.PUT("/axis-definitions/{axis_id}", {
        params: { path: { axis_id: axisId } },
        body: payload,
        ...init,
      }),
    adminOptions("軸の保存", { body: payload }),
  );
}

export async function deleteAxisDefinition(axisId: string): Promise<void> {
  await requestApi(
    (init) => adminApiClient.DELETE("/axis-definitions/{axis_id}", { params: { path: { axis_id: axisId } }, ...init }),
    adminOptions("軸の削除"),
  );
}

export function unpublishAxisDefinition(axisId: string) {
  return requestApi(
    (init) =>
      adminApiClient.POST("/axis-definitions/{axis_id}/unpublish", { params: { path: { axis_id: axisId } }, ...init }),
    adminOptions("軸の非公開化"),
  );
}

// 軸の編集中のプレビュー。分布は初回にWayの抽選と材料の組み立てを伴う。しきい値と点数はDBを読まない。

/** 編集中のshapeで、折れ点を通す前の生値がどう分布するか。 */
export function fetchAxisValueDistribution(shape: AxisShape) {
  const body = { shape };
  return requestApi(
    (init) => adminApiClient.POST("/axis-definitions/preview-distribution", { body, ...init }),
    adminOptions("分布の取得", { timeoutMs: DISTRIBUTION_API_TIMEOUT_MS, body }),
  );
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
  const response = await requestApi(
    (init) => adminApiClient.POST("/axis-definitions/preview-display-thresholds", { body, ...init }),
    adminOptions("しきい値の確認", { body }),
  );
  return { droppedOnMap: response.dropped_on_map, bandsOnMap: response.bands_on_map };
}

export type ScoresPreviewRequest = Schemas["ScoresPreviewRequest"];
export type ScoresPreview = Schemas["ScoresPreviewResponse"];

/** 編集中の折れ点で、値がそれぞれ何点になるか。点数はbackendが評価と同じ計算で出す。 */
export function fetchScoresPreview(body: ScoresPreviewRequest) {
  return requestApi(
    (init) => adminApiClient.POST("/axis-definitions/preview-scores", { body, ...init }),
    adminOptions("点数の確認", { body }),
  );
}

// 材料

export type MaterialDistribution = Schemas["MaterialDistributionResponse"];

/** 1材料の値が実データでどの範囲に散らばっているか。 */
export function fetchMaterialDistribution(materialId: string) {
  return requestApi(
    (init) =>
      adminApiClient.GET("/material-catalog/{material_id}/distribution", {
        params: { path: { material_id: materialId } },
        ...init,
      }),
    adminOptions("分布の取得", { timeoutMs: DISTRIBUTION_API_TIMEOUT_MS }),
  );
}

/** categoricalの材料が実データで取る値の一覧。 */
export function getMaterialValues(materialId: string) {
  return requestApi(
    (init) =>
      adminApiClient.GET("/material-catalog/{material_id}/values", {
        params: { path: { material_id: materialId } },
        ...init,
      }),
    adminOptions("材料の値一覧の取得", { timeoutMs: CATALOG_API_TIMEOUT_MS }),
  );
}

export function getMaterialCoverage() {
  return requestApi(
    (init) => adminApiClient.GET("/material-catalog/coverage", init),
    adminOptions("材料の欠損割合の取得", { timeoutMs: HEAVY_ADMIN_API_TIMEOUT_MS }),
  );
}

// データ保守

export function getDerivedDataFreshness() {
  return requestApi(
    (init) => adminApiClient.GET("/derived-data/freshness", init),
    adminOptions("派生データ鮮度台帳の取得", { timeoutMs: HEAVY_ADMIN_API_TIMEOUT_MS }),
  );
}

export function getDbStatus() {
  return requestApi(
    (init) => adminApiClient.GET("/db-status", init),
    adminOptions("DB状態の取得", { timeoutMs: HEAVY_ADMIN_API_TIMEOUT_MS }),
  );
}

export async function refreshTileCache(): Promise<void> {
  await requestApi((init) => adminApiClient.POST("/basemap/refresh", init), adminOptions("タイルキャッシュの消去"));
}

// 較正値

/** 較正値1件の宣言と、いま効いている値。項目はbackendが宣言から導く。 */
export type TuningParameter = Schemas["TuningParameterView"];

export function listTuningParameters() {
  return requestApi((init) => adminApiClient.GET("/tuning", init), adminOptions("較正値の取得"));
}

/** 1件を書き換える。`value`にnullを渡すと既定へ戻す。 */
export function updateTuningParameter(paramId: string, value: number | null) {
  const body = { value };
  return requestApi(
    (init) => adminApiClient.PUT("/tuning/{param_id}", { params: { path: { param_id: paramId } }, body, ...init }),
    adminOptions("較正値の保存", { body }),
  );
}

// ログ

type LogsQuery = NonNullable<paths["/api/admin/debug/logs"]["get"]["parameters"]["query"]>;

/** Python標準loggingのレベル名。正本はbackendで、契約から引く。 */
export type LogLevelName = NonNullable<LogsQuery["min_level"]>;

/** 直近のログ行（プロセス内リングバッファ）。debug_modeがOFFの間もWARNING以上は常に含まれる。 */
export function getRecentLogs(query: LogsQuery = {}) {
  return requestApi(
    (init) => adminApiClient.GET("/debug/logs", { params: { query }, ...init }),
    adminOptions("ログの取得"),
  );
}

// 稼働状況（認証の要らない口）

export type DebugStats = Schemas["DebugStatsResponse"];

export function getDebugStats() {
  return requestApi(
    (init) => backendApi.GET("/api/debug/stats", init),
    getOptions({ timeoutMs: STATUS_API_TIMEOUT_MS, category: "api:debug-stats", errorLabel: "システム状況" }),
  );
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
 * `requestApi`がdebugLogへ残す。 */
export async function checkBackendHealth(): Promise<boolean> {
  const failure = "バックエンドへの疎通確認に失敗しました";
  try {
    const data = await requestApi((init) => backendApi.GET("/health", init), {
      timeoutMs: STATUS_API_TIMEOUT_MS,
      category: "api:health",
      messages: { failure, parseFailure: failure },
    });
    return data.status === "ok";
  } catch {
    return false;
  }
}
