import { proxyToBackendAdmin } from "@/lib/adminApiProxy";

// backend: POST /api/admin/axis-definitions/preview-scores（編集中の折れ点で、値がそれぞれ何点になるかを
// 返す、Basic認証必須）。DBを読まないため既定の転送タイムアウトで足りる。
const BACKEND_PATH = "/api/admin/axis-definitions/preview-scores";

export async function POST(request: Request) {
  return proxyToBackendAdmin(request, BACKEND_PATH);
}
