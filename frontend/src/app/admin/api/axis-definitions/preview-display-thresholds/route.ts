import { proxyToBackendAdmin } from "@/lib/adminApiProxy";

// backend: POST /api/admin/axis-definitions/preview-display-thresholds（編集中の軸で、
// 人が刻んだ段の境界のうち地図では段にならないものを返す、Basic認証必須）。
const BACKEND_PATH = "/api/admin/axis-definitions/preview-display-thresholds";

export async function POST(request: Request) {
  return proxyToBackendAdmin(request, BACKEND_PATH);
}
