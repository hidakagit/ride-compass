import { proxyToBackendAdmin } from "@/lib/adminApiProxy";
import { DISTRIBUTION_API_TIMEOUT_MS } from "@/lib/apiTimeouts";

// backend: POST /api/admin/axis-definitions/preview-distribution（編集中のshapeで
// 実データの生値がどう分布するかを返す、Basic認証必須）。初回はWayの抽選と材料の
// 組み立てを伴うため、既定より長い転送タイムアウトを取る。
const BACKEND_PATH = "/api/admin/axis-definitions/preview-distribution";

export async function POST(request: Request) {
  return proxyToBackendAdmin(request, BACKEND_PATH, { timeoutMs: DISTRIBUTION_API_TIMEOUT_MS });
}
