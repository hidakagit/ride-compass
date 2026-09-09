import { proxyToBackendAdmin } from "@/lib/adminApiProxy";
import { DISTRIBUTION_API_TIMEOUT_MS } from "@/lib/apiTimeouts";

// backend: GET /api/admin/material-catalog/{material_id}/distribution（材料の値が実データで
// どの範囲に散らばっているか、Basic認証必須）。分布プレビューと同じ抽選サンプルを使うため、
// 初回だけ時間がかかる。
// Next.js 16ではdynamic route paramsがPromiseになった（frontend/AGENTS.md参照）。
type Params = { params: Promise<{ materialId: string }> };

export async function GET(request: Request, { params }: Params) {
  const { materialId } = await params;
  return proxyToBackendAdmin(
    request,
    `/api/admin/material-catalog/${encodeURIComponent(materialId)}/distribution`,
    { timeoutMs: DISTRIBUTION_API_TIMEOUT_MS },
  );
}
