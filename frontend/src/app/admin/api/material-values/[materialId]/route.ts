import { proxyToBackendAdmin } from "@/lib/adminApiProxy";

// backend: GET /api/admin/material-catalog/{material_id}/values（材料の実データ値一覧、
// Basic認証必須）。索引の効かないSELECT DISTINCTをタイル配信と同じ接続プール上で実行する
// ため、coverageと同じくadminパス側に置いてある。
// Next.js 16ではdynamic route paramsがPromiseになった（frontend/AGENTS.md参照）。
type Params = { params: Promise<{ materialId: string }> };

export async function GET(request: Request, { params }: Params) {
  const { materialId } = await params;
  return proxyToBackendAdmin(request, `/api/admin/material-catalog/${encodeURIComponent(materialId)}/values`);
}
