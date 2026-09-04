import type { MaterialCoverageResponse } from "@/types/route";
import { debugLog } from "@/lib/debugLog";
import { formatErrorDetail } from "@/lib/apiError";

// 材料ごとの欠損割合（backend GET /api/admin/material-catalog/coverage、Basic認証必須）の
// クライアント。axisAdminApi.ts/debugAdminApi.tsと同じ理由で同一オリジンのNext.js
// route handler（app/admin/api/material-coverage/、lib/adminApiProxy.ts参照）を経由し、
// /adminページのブラウザ標準Basic認証セッションをそのまま再利用する。
// backend側で全表走査を伴うため、他の管理APIより長いタイムアウトを持つ（route handler側の
// 転送タイムアウトと揃える）。

const API_PATH = "/admin/api/material-coverage";
const TIMEOUT_MS = 90000;

export async function getMaterialCoverage(): Promise<MaterialCoverageResponse> {
  const startedAt = performance.now();
  debugLog("api:materialCoverage", `GET ${API_PATH}`);
  let response: Response;
  try {
    response = await fetch(API_PATH, { signal: AbortSignal.timeout(TIMEOUT_MS) });
  } catch (error) {
    const detail = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    debugLog("api:materialCoverage", "失敗 (通信エラー)", { path: API_PATH, error: detail }, "error");
    throw new Error(`材料の欠損割合の取得に失敗しました: ${detail}`);
  }
  const durationMs = Math.round(performance.now() - startedAt);

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    const detail =
      formatErrorDetail(errorBody?.detail) ?? `材料の欠損割合の取得に失敗しました[HTTP ${response.status}]`;
    debugLog("api:materialCoverage", "失敗", { path: API_PATH, status: response.status, durationMs, detail }, "error");
    throw new Error(detail);
  }

  const data = (await response.json()) as MaterialCoverageResponse;
  debugLog("api:materialCoverage", "成功", { durationMs, materials: data.materials.length });
  return data;
}
