import { proxyToBackendAdmin } from "@/lib/adminApiProxy";

// backend: GET /api/admin/debug/logs。limit/containsクエリは
// proxyToBackendAdminがrequest.urlからそのまま転送する。
const BACKEND_PATH = "/api/admin/debug/logs";

export async function GET(request: Request) {
  return proxyToBackendAdmin(request, BACKEND_PATH);
}
