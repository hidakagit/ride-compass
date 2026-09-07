import type { MaterialCoverageResponse } from "@/types/route";
import { fetchJson } from "@/lib/fetchJson";

// 材料ごとの欠損割合（backend GET /api/admin/material-catalog/coverage、Basic認証必須）の
// クライアント。axisAdminApi.ts/debugAdminApi.tsと同じ理由で同一オリジンのNext.js
// route handler（app/admin/api/material-coverage/、lib/adminApiProxy.ts参照）を経由し、
// /adminページのブラウザ標準Basic認証セッションをそのまま再利用する。
// backend側で全表走査を伴うため、他の管理APIより長いタイムアウトを持つ（route handler側の
// 転送タイムアウトと揃える）。

const API_PATH = "/admin/api/material-coverage";
const TIMEOUT_MS = 90000;

export async function getMaterialCoverage(): Promise<MaterialCoverageResponse> {
  return fetchJson<MaterialCoverageResponse>(API_PATH, {
    timeoutMs: TIMEOUT_MS,
    category: "api:materialCoverage",
    errorLabel: "材料の欠損割合",
  });
}
