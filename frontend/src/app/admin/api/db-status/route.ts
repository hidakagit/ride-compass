import { proxyToBackendAdmin } from "@/lib/adminApiProxy";
import { HEAVY_ADMIN_API_TIMEOUT_MS } from "@/lib/apiTimeouts";

// backend: GET /api/admin/db-status（本番DBの状態、Basic認証必須）。全テーブルの実数
// カウントを伴うため、派生データ鮮度台帳と同じ長いタイムアウトで転送する。
const BACKEND_PATH = "/api/admin/db-status";

export async function GET(request: Request) {
  return proxyToBackendAdmin(request, BACKEND_PATH, { timeoutMs: HEAVY_ADMIN_API_TIMEOUT_MS });
}
