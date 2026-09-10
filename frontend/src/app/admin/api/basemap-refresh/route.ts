import { proxyToBackendAdmin } from "@/lib/adminApiProxy";

// backend: POST /api/admin/basemap/refresh（タイルファイルキャッシュの全消去、Basic認証必須）。
const BACKEND_PATH = "/api/admin/basemap/refresh";

export async function POST(request: Request) {
  return proxyToBackendAdmin(request, BACKEND_PATH);
}
