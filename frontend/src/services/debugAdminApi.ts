import { debugLog } from "@/lib/debugLog";
import { formatErrorDetail } from "@/lib/apiError";

// backendの直近ログ取得API（GET /api/admin/debug/logs、改善計画T379）のクライアント
// （改善計画T517）。axisAdminApi.tsと同じ理由で、同一オリジンのNext.js route handler
// （app/admin/api/debug/logs/、lib/adminApiProxy.ts参照）を経由する——/adminページの
// ブラウザ標準Basic認証セッションをそのまま再利用でき、この画面専用の認証情報入力欄が
// 不要になる。backendのレスポンス形（list[str]、debug_admin.py: read_recent_logs）は
// Pydanticモデルを持たない素の配列のため、生成型（types/generated/api.d.ts）を経由せず
// string[]を直接使う。

const API_BASE_URL = "/admin/api/debug/logs";

// backend/app/api/routers/debug_admin.py: _LOG_LEVEL_NAMEと同じ名称の集合
// （Python標準loggingのレベル名）。値そのものはbackend側が単一の情報源。
export type LogLevelName = "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";

export interface GetRecentLogsParams {
  /** 末尾からN件に絞り込む（省略時はbackend側の既定=保持している全件）。 */
  limit?: number;
  /** 部分一致フィルタ（例: "jma-tile"）。 */
  contains?: string;
  /** このレベル以上だけに絞り込む（例: "WARNING"でWARNING/ERROR/CRITICALだけになる、
   * 改善計画T517）。 */
  minLevel?: LogLevelName;
}

/** 直近のログ行（プロセス内リングバッファ、既定最大1000件）を取得する。debug_modeが
 * OFFの間はDEBUGレベルの行が記録されないが、WARNING以上（エラー・429拒否等、
 * docs/logging.md「常時出す」方針）は常に含まれる。 */
export async function getRecentLogs(params: GetRecentLogsParams = {}): Promise<string[]> {
  const query = new URLSearchParams();
  if (params.limit != null) query.set("limit", String(params.limit));
  if (params.contains) query.set("contains", params.contains);
  if (params.minLevel) query.set("min_level", params.minLevel);
  const queryString = query.toString();
  const path = queryString ? `${API_BASE_URL}?${queryString}` : API_BASE_URL;

  debugLog("api:debugAdminLogs", `GET ${path}`);
  let response: Response;
  try {
    response = await fetch(path, { signal: AbortSignal.timeout(15000) });
  } catch (error) {
    const detail = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    debugLog("api:debugAdminLogs", "失敗 (通信エラー)", { path, error: detail }, "error");
    throw new Error(`ログの取得に失敗しました: ${detail}`);
  }

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    const detail = formatErrorDetail(errorBody?.detail) ?? `ログの取得に失敗しました[HTTP ${response.status}]`;
    debugLog("api:debugAdminLogs", "失敗", { path, status: response.status, detail }, "error");
    throw new Error(detail);
  }

  const lines = (await response.json()) as string[];
  debugLog("api:debugAdminLogs", "成功", { count: lines.length });
  return lines;
}
