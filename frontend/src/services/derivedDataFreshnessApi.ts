import type { DerivedDataFreshnessResponse } from "@/types/route";
import { fetchJson } from "@/lib/fetchJson";

// 派生データ鮮度台帳（backend GET /api/admin/derived-data/freshness、Basic認証必須）の
// クライアント。materialCoverageApi.tsと同じ理由で同一オリジンのNext.js route handler
// （app/admin/api/derived-data-freshness/、lib/adminApiProxy.ts参照）を経由し、
// /adminページのブラウザ標準Basic認証セッションをそのまま再利用する。
// backend側で全表走査を伴うため、他の管理APIより長いタイムアウトを持つ（route handler側の
// 転送タイムアウトと揃える）。

const API_PATH = "/admin/api/derived-data-freshness";
const TIMEOUT_MS = 90000;

export async function getDerivedDataFreshness(): Promise<DerivedDataFreshnessResponse> {
  return fetchJson<DerivedDataFreshnessResponse>(API_PATH, {
    timeoutMs: TIMEOUT_MS,
    category: "api:derivedDataFreshness",
    errorLabel: "派生データ鮮度台帳",
  });
}
