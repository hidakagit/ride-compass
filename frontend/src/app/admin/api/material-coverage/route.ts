import { proxyToBackendAdmin } from "@/lib/adminApiProxy";

// backend: GET /api/admin/material-catalog/coverage（材料ごとの欠損割合、Basic認証必須）。
// osm_raw_ways/road_edgesの全表走査を伴うため、既定の15秒より長いタイムアウトで転送する
// （backend側のセッションもルート生成用の長いcommand_timeoutを使う）。
const BACKEND_PATH = "/api/admin/material-catalog/coverage";
export const COVERAGE_PROXY_TIMEOUT_MS = 90000;

export async function GET(request: Request) {
  return proxyToBackendAdmin(request, BACKEND_PATH, { timeoutMs: COVERAGE_PROXY_TIMEOUT_MS });
}
