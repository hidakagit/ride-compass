import type { DbStatusResponse } from "@/types/route";
import { fetchJson } from "@/lib/fetchJson";
import { HEAVY_ADMIN_API_TIMEOUT_MS } from "@/lib/apiTimeouts";

// 本番DBの状態（backend GET /api/admin/db-status、Basic認証必須）のクライアント。
// derivedDataFreshnessApi.tsと同じく同一オリジンのroute handlerを経由し、/adminページの
// ブラウザ標準Basic認証セッションをそのまま再利用する。

const API_PATH = "/admin/api/db-status";

export async function getDbStatus(): Promise<DbStatusResponse> {
  return fetchJson<DbStatusResponse>(API_PATH, {
    timeoutMs: HEAVY_ADMIN_API_TIMEOUT_MS,
    category: "api:dbStatus",
    errorLabel: "DB状態",
  });
}
