import { proxyToBackendAdmin } from "@/lib/adminApiProxy";

// backend: POST /api/admin/axis-definitions/preview-distribution（編集中のshapeで
// 実データの生値がどう分布するかを返す、Basic認証必須）。初回はWayの抽選と材料の
// 組み立てを伴うため、既定（15秒）より長い転送タイムアウトを取る。
const BACKEND_PATH = "/api/admin/axis-definitions/preview-distribution";
export const PREVIEW_PROXY_TIMEOUT_MS = 60000;

export async function POST(request: Request) {
  return proxyToBackendAdmin(request, BACKEND_PATH, { timeoutMs: PREVIEW_PROXY_TIMEOUT_MS });
}
