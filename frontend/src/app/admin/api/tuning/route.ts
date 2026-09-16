import { proxyToBackendAdmin } from "@/lib/adminApiProxy";

// backend: GET /api/admin/tuning（較正値の一覧、Basic認証必須）。
const BACKEND_PATH = "/api/admin/tuning";

export async function GET(request: Request) {
  return proxyToBackendAdmin(request, BACKEND_PATH);
}
