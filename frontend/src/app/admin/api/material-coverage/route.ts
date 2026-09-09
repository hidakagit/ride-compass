import { proxyToBackendAdmin } from "@/lib/adminApiProxy";
import { HEAVY_ADMIN_API_TIMEOUT_MS } from "@/lib/apiTimeouts";

// backend: GET /api/admin/material-catalog/coverage（材料ごとの欠損割合、Basic認証必須）。
// osm_raw_ways/road_edgesの全表走査を伴うため、既定より長いタイムアウトで転送する
// （backend側のセッションもルート生成用の長いcommand_timeoutを使う）。値はブラウザ側の
// クライアント（services/materialCoverageApi.ts）と同じ定数を使う。
const BACKEND_PATH = "/api/admin/material-catalog/coverage";

export async function GET(request: Request) {
  return proxyToBackendAdmin(request, BACKEND_PATH, { timeoutMs: HEAVY_ADMIN_API_TIMEOUT_MS });
}
