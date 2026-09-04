import { proxyToBackendAdmin } from "@/lib/adminApiProxy";

// backend: GET /api/admin/derived-data/freshness（派生データ鮮度台帳、Basic認証必須）。
// edge_attribute_counts等の全表走査を伴うため、既定の15秒より長いタイムアウトで転送する
// （backend側のセッションもルート生成用の長いcommand_timeoutを使う）。
const BACKEND_PATH = "/api/admin/derived-data/freshness";
export const FRESHNESS_PROXY_TIMEOUT_MS = 90000;

export async function GET(request: Request) {
  return proxyToBackendAdmin(request, BACKEND_PATH, { timeoutMs: FRESHNESS_PROXY_TIMEOUT_MS });
}
