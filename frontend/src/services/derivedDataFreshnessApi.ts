import type { DerivedDataFreshnessResponse } from "@/types/route";
import { debugLog } from "@/lib/debugLog";
import { formatErrorDetail } from "@/lib/apiError";

// 派生データ鮮度台帳（backend GET /api/admin/derived-data/freshness、Basic認証必須）の
// クライアント。materialCoverageApi.tsと同じ理由で同一オリジンのNext.js route handler
// （app/admin/api/derived-data-freshness/、lib/adminApiProxy.ts参照）を経由し、
// /adminページのブラウザ標準Basic認証セッションをそのまま再利用する。
// backend側で全表走査を伴うため、他の管理APIより長いタイムアウトを持つ（route handler側の
// 転送タイムアウトと揃える）。

const API_PATH = "/admin/api/derived-data-freshness";
const TIMEOUT_MS = 90000;

export async function getDerivedDataFreshness(): Promise<DerivedDataFreshnessResponse> {
  const startedAt = performance.now();
  debugLog("api:derivedDataFreshness", `GET ${API_PATH}`);
  let response: Response;
  try {
    response = await fetch(API_PATH, { signal: AbortSignal.timeout(TIMEOUT_MS) });
  } catch (error) {
    const detail = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    debugLog("api:derivedDataFreshness", "失敗 (通信エラー)", { path: API_PATH, error: detail }, "error");
    throw new Error(`派生データ鮮度台帳の取得に失敗しました: ${detail}`);
  }
  const durationMs = Math.round(performance.now() - startedAt);

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    const detail =
      formatErrorDetail(errorBody?.detail) ?? `派生データ鮮度台帳の取得に失敗しました[HTTP ${response.status}]`;
    debugLog(
      "api:derivedDataFreshness",
      "失敗",
      { path: API_PATH, status: response.status, durationMs, detail },
      "error",
    );
    throw new Error(detail);
  }

  const data = (await response.json()) as DerivedDataFreshnessResponse;
  debugLog("api:derivedDataFreshness", "成功", { durationMs, generations: data.generations.length });
  return data;
}
