import { proxyToBackendAdmin } from "@/lib/adminApiProxy";

// Next.js 16ではdynamic route paramsがPromiseになった（frontend/AGENTS.md参照）。
type Params = { params: Promise<{ paramId: string }> };

export async function PUT(request: Request, { params }: Params) {
  const { paramId } = await params;
  return proxyToBackendAdmin(request, `/api/admin/tuning/${encodeURIComponent(paramId)}`);
}
