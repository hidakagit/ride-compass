import { proxyToBackendAdmin } from "@/lib/adminApiProxy";
import { HEAVY_ADMIN_API_TIMEOUT_MS } from "@/lib/apiTimeouts";

// backend: GET /api/admin/derived-data/freshness（派生データ鮮度台帳、Basic認証必須）。
// edge_attribute_counts等の全表走査を伴うため、既定より長いタイムアウトで転送する
// （backend側のセッションもルート生成用の長いcommand_timeoutを使う）。値はブラウザ側の
// クライアント（services/derivedDataFreshnessApi.ts）と同じ定数を使う。
const BACKEND_PATH = "/api/admin/derived-data/freshness";

export async function GET(request: Request) {
  return proxyToBackendAdmin(request, BACKEND_PATH, { timeoutMs: HEAVY_ADMIN_API_TIMEOUT_MS });
}
